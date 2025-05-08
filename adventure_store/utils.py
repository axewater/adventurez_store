import hashlib
import datetime
import sqlite3
from flask import current_app, session
from .db import get_db
import os
import zipfile
import json

def hash_password(password):
    """Hashes a password using SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()

def parse_datetime(date_string):
    """Safely parse a datetime string or return a datetime object if already parsed."""
    if not date_string:
        return None
    # If it's already a datetime object, return it directly
    if isinstance(date_string, datetime.datetime):
        return date_string
    try:
        # Try parsing with microseconds first
        return datetime.datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S.%f')
    except ValueError:
        try:
            # Fallback to parsing without microseconds
            return datetime.datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            current_app.logger.warning(f"Could not parse date string: {date_string}. Returning as is.")
            return date_string # Return original string if parsing fails

def get_site_settings():
    """Helper function to get site settings from the database."""
    conn = get_db()
    settings = {}
    try:
        for row in conn.execute('SELECT setting_name, setting_value FROM site_settings').fetchall():
            settings[row['setting_name']] = row['setting_value']
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching settings: {e}")
    # No conn.close() here, managed by app context teardown
    return settings

def get_pending_moderation_count():
    """Helper function to get the count of adventures pending moderation."""
    if 'user_id' not in session:
        return 0

    conn = get_db()
    count = 0
    try:
        user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if user and user['role'] in ['admin', 'moderator']:
            count_row = conn.execute('SELECT COUNT(*) as count FROM adventures WHERE approved = 0').fetchone()
            if count_row:
                count = count_row['count']
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching pending count: {e}")
    # No conn.close() here
    return count

def log_statistic(stat_name, increment=1):
    """Helper function to log statistics."""
    conn = get_db()
    today = datetime.datetime.now().strftime('%Y-%m-%d')

    try:
        # Check if stat exists for today
        stat = conn.execute(
            'SELECT id, stat_value FROM statistics WHERE stat_name = ? AND date(date) = ?',
            (stat_name, today)
        ).fetchone()

        if stat:
            conn.execute(
                'UPDATE statistics SET stat_value = stat_value + ? WHERE id = ?',
                (increment, stat['id'])
            )
        else:
            conn.execute(
                'INSERT INTO statistics (stat_name, stat_value, date) VALUES (?, ?, ?)',
                (stat_name, increment, datetime.datetime.now()) # Use full datetime for insertion
            )

        conn.commit()
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error logging statistic '{stat_name}': {e}")
    # No conn.close() here

def extract_and_save_thumbnail(zip_file_path, adventure_id):
    """
    Extracts a thumbnail image from an adventure ZIP file and saves it.

    Tries to find common thumbnail names first (thumbnail.png, cover.jpg, etc.).
    If not found, it looks for 'game_info.start_image_path' in 'game_data.json'
    within the ZIP and uses that image if it exists in the ZIP.

    Args:
        zip_file_path (str): The path to the adventure ZIP file.
        adventure_id (int): The ID of the adventure, used for naming the thumbnail.

    Returns:
        str: The filename of the saved thumbnail if successful, None otherwise.
    """
    common_thumbnail_names = [
        'thumbnail.png', 'thumbnail.jpg', 'thumbnail.jpeg',
        'cover.png', 'cover.jpg', 'cover.jpeg',
        'thumb.png', 'thumb.jpg', 'thumb.jpeg'
    ]
    image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp') # Common image extensions

    try:
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            zip_contents = zip_ref.namelist()
            image_to_extract = None
            original_ext = None

            # 1. Check for common thumbnail names
            for common_name in common_thumbnail_names:
                # Check for case-insensitive matches
                for item_in_zip in zip_contents:
                    if item_in_zip.lower().endswith(common_name.lower()): # Check filename part
                        # Ensure it's at the root or in a common image folder (optional, for now root is fine)
                        # For simplicity, we'll assume if the name matches, it's a candidate.
                        # More robust check: if os.path.basename(item_in_zip).lower() == common_name.lower():
                        if os.path.basename(item_in_zip).lower() == common_name.lower():
                            image_to_extract = item_in_zip
                            break
                if image_to_extract:
                    break

            # 2. If not found, check game_data.json for start_image_path
            if not image_to_extract and 'game_data.json' in zip_contents:
                try:
                    with zip_ref.open('game_data.json') as gd_file:
                        game_data = json.load(gd_file)
                        start_image_path = game_data.get('game_info', {}).get('start_image_path')
                        if start_image_path and start_image_path.lower().endswith(image_extensions):
                            # Ensure the path from game_data.json actually exists in the zip
                            # It might be a relative path like "images/cover.png"
                            # We need to handle potential path separators (normalize)
                            normalized_start_image_path = start_image_path.replace('\\', '/')
                            if normalized_start_image_path in zip_contents:
                                image_to_extract = normalized_start_image_path
                            else: # Try matching just the basename if full path not found
                                base_start_image = os.path.basename(normalized_start_image_path)
                                for item_in_zip in zip_contents:
                                    if os.path.basename(item_in_zip) == base_start_image:
                                        image_to_extract = item_in_zip
                                        break
                except json.JSONDecodeError:
                    current_app.logger.warning(f"Could not parse game_data.json in {zip_file_path} for thumbnail.")
                except Exception as e_gd:
                    current_app.logger.warning(f"Error reading start_image_path from game_data.json in {zip_file_path}: {e_gd}")

            if image_to_extract:
                original_ext = os.path.splitext(image_to_extract)[1]
                thumbnail_filename = f"thumb_adv_{adventure_id}{original_ext}"
                thumbnail_save_path = os.path.join(current_app.config['THUMBNAIL_FOLDER'], thumbnail_filename)

                with zip_ref.open(image_to_extract) as source_image, open(thumbnail_save_path, 'wb') as target_file:
                    target_file.write(source_image.read())
                current_app.logger.info(f"Thumbnail '{thumbnail_filename}' extracted and saved for adventure {adventure_id}.")
                return thumbnail_filename

    except zipfile.BadZipFile:
        current_app.logger.error(f"Bad ZIP file: {zip_file_path} when trying to extract thumbnail.")
    except Exception as e:
        current_app.logger.error(f"Error extracting thumbnail for adventure {adventure_id} from {zip_file_path}: {e}", exc_info=True)

    return None

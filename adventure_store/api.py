from flask import (
    Blueprint, request, jsonify, current_app, g
)
from werkzeug.utils import secure_filename
from .db import get_db
from .utils import log_statistic, get_site_settings
import os
import datetime
import zipfile
import json
from packaging.version import parse as parse_version
import sqlite3

api_bp = Blueprint('api', __name__, url_prefix='/api')

def log_api_request(api_key_name, endpoint, status_code, success):
    """Helper function to log API requests."""
    conn = get_db()
    ip_address = request.remote_addr
    try:
        conn.execute(
            'INSERT INTO api_logs (api_key_name, ip_address, endpoint, status_code, success) VALUES (?, ?, ?, ?, ?)',
            (api_key_name, ip_address, endpoint, status_code, success)
        )
        conn.commit()
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error logging API request: {e}")
    # No conn.close() here

# --- API Key Authentication ---
@api_bp.before_request
def require_api_key():
    api_key = request.headers.get('X-API-Key')
    g.api_key_info = None # Store key info in g for access in the route

    if not api_key:
        log_api_request(None, request.path, 401, False)
        return jsonify({"error": "API key required."}), 401

    conn = get_db()
    try:
        key_info = conn.execute(
            'SELECT id, name, user_id, is_active FROM api_keys WHERE key = ?', (api_key,)
        ).fetchone()

        if not key_info or not key_info['is_active']:
            log_api_request(key_info['name'] if key_info else 'Invalid Key', request.path, 403, False)
            return jsonify({"error": "Invalid or inactive API key."}), 403

        # Store key info for use in the view function
        g.api_key_info = dict(key_info)

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error checking API key: {e}")
        log_api_request('DB Error', request.path, 500, False)
        return jsonify({"error": "Internal server error during authentication."}), 500
    # No conn.close() here

# --- API Routes ---

@api_bp.route('/submit', methods=['POST'])
def submit_adventure():
    # API key is validated by the before_request handler
    key_info = g.api_key_info
    api_key_name = key_info['name'] if key_info else 'Unknown' # Should always have info here

    # --- Basic Request Validation ---
    if 'adventure_file' not in request.files:
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "Missing 'adventure_file' in request."}), 400

    file = request.files['adventure_file']
    if file.filename == '':
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "No selected file."}), 400

    if not file.filename.lower().endswith('.zip'):
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "Only ZIP files are allowed."}), 400

    # --- File Size Check ---
    site_settings = get_site_settings()
    max_mb = int(site_settings.get('max_upload_size', 50)) # Default 50MB if not set
    max_bytes = max_mb * 1024 * 1024
    file.seek(0, os.SEEK_END) # Go to end of file
    file_size = file.tell() # Get size
    file.seek(0) # Reset pointer to beginning
    if file_size > max_bytes:
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": f"File size ({file_size // (1024 * 1024)}MB) exceeds the maximum allowed size ({max_mb}MB)."}), 400

    description = request.form.get('description')
    tags_str = request.form.get('tags') # e.g., "1,5,8" or ["Fantasy", "Sci-Fi"] - needs parsing

    # --- Process Tags ---
    # Assuming tags are sent as a comma-separated string of tag IDs
    tag_ids = []
    try:
        tag_ids = [int(tid.strip()) for tid in tags_str.split(',') if tid.strip()]
        if not tag_ids: raise ValueError("No valid tag IDs provided")
    except (ValueError, TypeError): # Catch if tags_str is None or not splittable
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "Invalid or missing 'tags'. Expected comma-separated IDs (e.g., '1,5,8')."}), 400

    conn = get_db()
    # Validate tag IDs exist
    try:
        if tag_ids: # Only validate if tag_ids were provided
            placeholders = ','.join('?' * len(tag_ids))
            valid_tags_count_row = conn.execute(f'SELECT COUNT(*) as count FROM tags WHERE id IN ({placeholders})', tag_ids).fetchone()
            if not valid_tags_count_row or valid_tags_count_row['count'] != len(tag_ids):
                log_api_request(api_key_name, request.path, 400, False)
                return jsonify({"error": "One or more provided tag IDs are invalid."}), 400

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error validating tags during API submit: {e}")
        log_api_request(api_key_name, request.path, 500, False)
        return jsonify({"error": "Database error validating tags."}), 500

    # --- File Handling & Processing ---
    user_id = key_info['user_id']
    # Get username for filename (optional, could just use user_id)
    user = conn.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
    username = user['username'] if user else f"user_{user_id}"

    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    safe_base_filename = secure_filename(f"{username}_api_{timestamp}.zip")
    upload_folder = current_app.config['UPLOAD_FOLDER']
    file_path = os.path.join(upload_folder, safe_base_filename)

    try:
        # Save file
        file.save(file_path)

        # Extract metadata from game_data.json inside the zip
        new_adventure_name = None
        new_game_version = "1.0.0"
        version_compat = "Unknown"
        # Use description from form if provided, otherwise fallback to game_data.json or default
        new_description = description if description else "No description provided."

        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                if 'game_data.json' in zip_ref.namelist():
                    with zip_ref.open('game_data.json') as game_data_file:
                        game_data = json.load(game_data_file)
                        game_info = game_data.get('game_info', {})
                        new_adventure_name = game_info.get('name')
                        # Game's own version (e.g., "2.0.0")
                        new_game_version = game_info.get('version', '1.0.0')
                        # Engine/Builder version (e.g., "1.1.0")
                        version_compat = game_info.get('builder_version', 'Unknown')
                        if not description and game_info.get('description'): # Use description from game_data if not in form
                            new_description = game_info.get('description')
                else:
                    os.remove(file_path) # Clean up saved file
                    log_api_request(api_key_name, request.path, 400, False)
                    return jsonify({"error": "Missing 'game_data.json' inside the ZIP file."}), 400

                if not new_adventure_name: # Name from game_data.json is mandatory
                    os.remove(file_path)
                    log_api_request(api_key_name, request.path, 400, False)
                    return jsonify({"error": "Adventure 'name' not found in 'game_data.json'."}), 400

        except (zipfile.BadZipFile, json.JSONDecodeError) as e_zip:
            os.remove(file_path) # Clean up saved file
            current_app.logger.warning(f"Error processing zip file {safe_base_filename}: {e_zip}")
            log_api_request(api_key_name, request.path, 400, False)
            return jsonify({"error": f"Could not process ZIP file or game_data.json: {e_zip}"}), 400

        # --- Ownership and Version Check ---
        existing_active_adventure = conn.execute(
            'SELECT id, author_id, game_version FROM adventures WHERE LOWER(name) = LOWER(?) AND approved = 1',
            (new_adventure_name,)
        ).fetchone()

        if existing_active_adventure:
            # Adventure with this name exists and is active. Check ownership and version.
            if existing_active_adventure['author_id'] != user_id:
                os.remove(file_path) # Clean up uploaded file
                log_api_request(api_key_name, request.path, 403, False)
                return jsonify({"error": f"Adventure name '{new_adventure_name}' is already in use by another author."}), 403

            # It's the owner, check version
            try:
                current_version = parse_version(existing_active_adventure['game_version'])
                submitted_version = parse_version(new_game_version)
                if not (submitted_version > current_version):
                    os.remove(file_path) # Clean up
                    log_api_request(api_key_name, request.path, 400, False)
                    return jsonify({"error": f"New version ({new_game_version}) must be higher than the current active version ({existing_active_adventure['game_version']})."}), 400
            except Exception as e_ver: # Catches InvalidVersion from packaging.version.parse
                os.remove(file_path) # Clean up
                current_app.logger.warning(f"Version comparison error for '{new_adventure_name}': {e_ver}")
                log_api_request(api_key_name, request.path, 400, False)
                return jsonify({"error": f"Invalid version format for new ('{new_game_version}') or existing ('{existing_active_adventure['game_version']}') adventure."}), 400
        # If no active adventure, or if it's an update by the owner with a higher version, proceed.

        # --- Database Insertion ---
        cursor = conn.execute(
            'INSERT INTO adventures (name, description, author_id, file_path, file_size, game_version, version_compat, approved) VALUES (?, ?, ?, ?, ?, ?, ?, 0)',
            (new_adventure_name, new_description, user_id, file_path, file_size, new_game_version, version_compat)
        )
        adventure_id = cursor.lastrowid

        # Add tags
        for tag_id in tag_ids:
            conn.execute('INSERT INTO adventure_tags (adventure_id, tag_id) VALUES (?, ?)', (adventure_id, tag_id))

        # Notify moderators
        moderators = conn.execute("SELECT id FROM users WHERE role IN ('admin', 'moderator')").fetchall()
        for mod in moderators:
            conn.execute(
                'INSERT INTO notifications (user_id, content, type, related_id) VALUES (?, ?, ?, ?)',
                (mod['id'], f"New API submission '{new_adventure_name}' needs approval", 'moderation', adventure_id)
            )

        conn.commit()
        log_statistic('uploads') # Log general upload stat
        log_api_request(api_key_name, request.path, 201, True) # Log successful API request

        return jsonify({
            "message": "Adventure submitted successfully and is pending approval.",
            "adventure_id": adventure_id
        }), 201

    except sqlite3.Error as e:
        conn.rollback()
        current_app.logger.error(f"Database error during API submission: {e}")
        # Clean up saved file if DB insert failed
        if os.path.exists(file_path):
             try: os.remove(file_path)
             except OSError: pass
        log_api_request(api_key_name, request.path, 500, False)
        return jsonify({"error": "Database error during submission."}), 500
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Unexpected error during API submission: {e}")
        # Clean up saved file on any unexpected error
        if os.path.exists(file_path):
             try: os.remove(file_path)
             except OSError: pass
        log_api_request(api_key_name, request.path, 500, False)
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

@api_bp.route('/tags', methods=['GET'])
def get_tags():
    # API key is validated by the before_request handler
    key_info = g.api_key_info
    api_key_name = key_info['name'] if key_info else 'Unknown' # Should always have info here

    conn = get_db()
    try:
        tags_data = conn.execute(
            'SELECT id, name FROM tags ORDER BY name ASC'
        ).fetchall()

        tags_list = [{"id": tag['id'], "name": tag['name']} for tag in tags_data]

        log_api_request(api_key_name, request.path, 200, True)
        return jsonify(tags_list), 200

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching tags for API: {e}")
        log_api_request(api_key_name, request.path, 500, False)
        return jsonify({"error": "Database error fetching tags."}), 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error fetching tags for API: {e}")
        log_api_request(api_key_name, request.path, 500, False)
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

@api_bp.route('/check_title_availability', methods=['GET'])
def check_title_availability():
    # API key is validated by the before_request handler
    key_info = g.api_key_info
    api_key_name = key_info['name'] if key_info else 'Unknown'

    title_to_check = request.args.get('title')

    if not title_to_check:
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "Missing 'title' query parameter."}), 400

    conn = get_db()
    try:
        # Perform a case-insensitive check for the adventure name
        # The LOWER() function makes the comparison case-insensitive
        # We only care about *active* (approved = 1) or *pending* (approved = 0) versions for availability.
        # Superseded (approved = 2) versions don't block a new submission by a different author,
        # but if an active version exists, only the owner can submit.
        existing_adventure = conn.execute(
            'SELECT id, author_id, approved FROM adventures WHERE LOWER(name) = LOWER(?) AND approved IN (0, 1)',
            (title_to_check,)
        ).fetchone()

        if existing_adventure:
            # If the adventure exists and is approved (active), and the querier is not the owner, it's "Not Available"
            # The API key user_id is in g.api_key_info['user_id']
            if existing_adventure['approved'] == 1 and existing_adventure['author_id'] != g.api_key_info['user_id']:
                log_api_request(api_key_name, request.path, 200, True)
                return jsonify({"status": "Not Available", "message": "This title is in use by another author."}), 200
            # If it's pending, or approved and owned by the querier, it's effectively "Not Available" for a *new* submission,
            # but the submit endpoint will handle the update logic. For a simple availability check, this is fine.
            log_api_request(api_key_name, request.path, 200, True)
            return jsonify({"status": "Not Available", "message": "This title is already in use or pending."}), 200
        else:
            log_api_request(api_key_name, request.path, 200, True)
            return jsonify({"status": "Available", "message": "This title can be used."}), 200

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error checking title availability: {e}")
        log_api_request(api_key_name, request.path, 500, False)
        return jsonify({"error": "Database error during title check."}), 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error checking title availability: {e}")
        log_api_request(api_key_name, request.path, 500, False)
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

import hashlib
import datetime
import sqlite3
from flask import current_app, session
from .db import get_db

def hash_password(password):
    """Hashes a password using SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()

def parse_datetime(date_string):
    """Safely parse a datetime string from SQLite."""
    if not date_string:
        return None
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

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
        return jsonify({"error": "API key required"}), 401

    conn = get_db()
    try:
        key_info = conn.execute(
            'SELECT id, name, user_id, is_active FROM api_keys WHERE key = ?', (api_key,)
        ).fetchone()

        if not key_info or not key_info['is_active']:
            log_api_request(key_info['name'] if key_info else 'Invalid Key', request.path, 403, False)
            return jsonify({"error": "Invalid or inactive API key"}), 403

        # Store key info for use in the view function
        g.api_key_info = dict(key_info)

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error checking API key: {e}")
        log_api_request('DB Error', request.path, 500, False)
        return jsonify({"error": "Internal server error during authentication"}), 500
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
        return jsonify({"error": "Missing 'adventure_file' in request"}), 400

    file = request.files['adventure_file']
    if file.filename == '':
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "No selected file"}), 400

    if not file.filename.lower().endswith('.zip'):
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "Only ZIP files are allowed"}), 400

    # --- File Size Check ---
    site_settings = get_site_settings()
    max_mb = int(site_settings.get('max_upload_size', 50)) # Default 50MB if not set
    max_bytes = max_mb * 1024 * 1024
    file.seek(0, os.SEEK_END) # Go to end of file
    file_size = file.tell() # Get size
    file.seek(0) # Reset pointer to beginning
    if file_size > max_bytes:
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": f"File size ({file_size // 1024 // 1024}MB) exceeds the maximum allowed size ({max_mb}MB)."}), 400

    # --- Metadata Handling (Example: Expecting JSON in 'metadata' form field) ---
    # Decide how metadata like name, description, tags are sent.
    # Option 1: Inside the ZIP (game_data.json) - Preferred for version
    # Option 2: Separate form fields/JSON body
    # Let's assume name, description, tags are sent as form fields for this example.
    name = request.form.get('name')
    description = request.form.get('description')
    tags_str = request.form.get('tags') # e.g., "1,5,8" or ["Fantasy", "Sci-Fi"] - needs parsing

    if not name or not description or not tags_str:
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "Missing required metadata: name, description, tags"}), 400

    # --- Process Tags ---
    # Assuming tags are sent as a comma-separated string of tag IDs
    tag_ids = []
    try:
        tag_ids = [int(tid.strip()) for tid in tags_str.split(',') if tid.strip()]
        if not tag_ids: raise ValueError("No valid tag IDs provided")
    except ValueError:
        log_api_request(api_key_name, request.path, 400, False)
        return jsonify({"error": "Invalid format for 'tags'. Expected comma-separated IDs (e.g., '1,5,8')."}), 400

    conn = get_db()
    # Validate tag IDs exist
    try:
        placeholders = ','.join('?' * len(tag_ids))
        valid_tags_count = conn.execute(f'SELECT COUNT(*) as count FROM tags WHERE id IN ({placeholders})', tag_ids).fetchone()['count']
        if valid_tags_count != len(tag_ids):
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

        # Extract version compatibility from game_data.json inside the zip
        version_compat = "Unknown"
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                if 'game_data.json' in zip_ref.namelist():
                    with zip_ref.open('game_data.json') as game_data_file:
                        game_data = json.load(game_data_file)
                        version_compat = game_data.get('version', 'Unknown')
                else:
                    # If game_data.json is missing, reject the submission? Or allow "Unknown"?
                    # Let's reject for now to enforce structure.
                    os.remove(file_path) # Clean up saved file
                    log_api_request(api_key_name, request.path, 400, False)
                    return jsonify({"error": "Missing 'game_data.json' inside the ZIP file."}), 400
        except (zipfile.BadZipFile, json.JSONDecodeError, Exception) as e:
            os.remove(file_path) # Clean up saved file
            current_app.logger.warning(f"Error processing zip file {safe_base_filename}: {e}")
            log_api_request(api_key_name, request.path, 400, False)
            return jsonify({"error": f"Could not process ZIP file or game_data.json: {e}"}), 400

        # --- Database Insertion ---
        cursor = conn.execute(
            'INSERT INTO adventures (name, description, author_id, file_path, file_size, version_compat, approved) VALUES (?, ?, ?, ?, ?, ?, 0)',
            (name, description, user_id, file_path, file_size, version_compat)
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
                (mod['id'], f"New API submission '{name}' needs approval", 'moderation', adventure_id)
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

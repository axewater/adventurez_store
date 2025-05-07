from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
)
from .db import get_db
from .utils import parse_datetime, log_statistic, hash_password, get_site_settings
from .decorators import admin_required
import secrets  # For generating API keys
import datetime
import sqlite3
import os
import zipfile
import json
from werkzeug.utils import secure_filename

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@admin_required
def admin_panel():
    return render_template('admin/index.html')

@admin_bp.route('/users')
@admin_required
def admin_users():
    conn = get_db()
    processed_users = []
    try:
        users_data = conn.execute('SELECT id, username, email, role, created_at, last_login FROM users ORDER BY created_at DESC').fetchall()
        for user_row in users_data:
            user_dict = dict(user_row)
            user_dict['created_at'] = parse_datetime(user_dict['created_at'])
            user_dict['last_login'] = parse_datetime(user_dict['last_login'])
            processed_users.append(user_dict)
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching users for admin panel: {e}")
        flash("Could not load users due to a database error.", "error")

    return render_template('admin/users.html', users=processed_users)

@admin_bp.route('/user/add', methods=['POST'])
@admin_required
def admin_add_user():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    role = request.form.get('role')

    if not all([username, email, password, confirm_password, role]):
        flash('All fields are required', 'error')
        return redirect(url_for('admin.admin_users'))
    if password != confirm_password:
        flash('Passwords do not match', 'error')
        return redirect(url_for('admin.admin_users'))
    if role not in ['user', 'moderator', 'admin']:
        flash('Invalid role specified', 'error')
        return redirect(url_for('admin.admin_users'))

    conn = get_db()
    try:
        existing_user = conn.execute('SELECT id FROM users WHERE username = ? OR email = ?', (username, email)).fetchone()
        if existing_user:
            flash('Username or email already exists', 'error')
            return redirect(url_for('admin.admin_users'))

        hashed_password = hash_password(password)
        conn.execute('INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)', (username, email, hashed_password, role))
        conn.commit()
        log_statistic('registrations')  # Log admin-added user
        flash(f'User "{username}" added successfully', 'success')
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error adding user via admin: {e}")
        flash('A database error occurred while adding the user.', 'error')

    return redirect(url_for('admin.admin_users'))

@admin_bp.route('/user/update/<int:user_id>', methods=['POST'])
@admin_required
def admin_update_user(user_id):
    new_role = request.form.get('role')
    if new_role not in ['user', 'moderator', 'admin']:
        flash('Invalid role specified', 'error')
        return redirect(url_for('admin.admin_users'))

    conn = get_db()
    try:
        user = conn.execute('SELECT id, username FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
            flash('User not found', 'error')
            return redirect(url_for('admin.admin_users'))

        # Prevent admin from accidentally removing the last admin role (basic check)
        if user['username'] == 'admin' and new_role != 'admin':
             admin_count = conn.execute("SELECT COUNT(*) as count FROM users WHERE role = 'admin'").fetchone()['count']
             if admin_count <= 1:
                 flash('Cannot remove the last admin role.', 'error')
                 return redirect(url_for('admin.admin_users'))

        conn.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
        conn.commit()
        flash(f'User "{user["username"]}" role updated successfully to {new_role}', 'success')
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error updating user role (ID: {user_id}): {e}")
        flash('A database error occurred while updating the user role.', 'error')

    return redirect(url_for('admin.admin_users'))

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    conn = get_db()
    if request.method == 'POST':
        theme = request.form.get('theme')
        max_upload_size_str = request.form.get('max_upload_size')

        if theme not in ['light', 'dark']:
            flash('Invalid theme selected', 'error')
            return redirect(url_for('admin.admin_settings'))

        try:
            max_upload_size = int(max_upload_size_str)
            if max_upload_size <= 0:
                raise ValueError("Max upload size must be positive.")
        except (ValueError, TypeError):
            flash('Invalid maximum upload size. Please enter a positive number.', 'error')
            return redirect(url_for('admin.admin_settings'))

        try:
            conn.execute("UPDATE site_settings SET setting_value = ? WHERE setting_name = 'theme'", (theme,))
            conn.execute("INSERT OR REPLACE INTO site_settings (setting_name, setting_value) VALUES (?, ?)", ('max_upload_size', str(max_upload_size)))
            conn.commit()
            flash('Settings updated successfully', 'success')
        except sqlite3.Error as e:
            current_app.logger.error(f"Database error updating settings: {e}")
            flash('A database error occurred while updating settings.', 'error')
        return redirect(url_for('admin.admin_settings'))

    # GET request handled by context processor, just render template
    return render_template('admin/settings.html')

# --- API Key Management ---

@admin_bp.route('/api-keys')
@admin_required
def admin_api_keys():
    conn = get_db()
    processed_keys = []
    users = []
    try:
        keys_data = conn.execute('''
            SELECT k.id, k.key, k.name, k.is_active, k.created_at, u.username
            FROM api_keys k JOIN users u ON k.user_id = u.id
            ORDER BY k.created_at DESC
        ''').fetchall()
        for key_row in keys_data:
            key_dict = dict(key_row)
            key_dict['created_at'] = parse_datetime(key_dict['created_at'])
            processed_keys.append(key_dict)

        # Fetch users for the 'Add Key' modal dropdown
        users = conn.execute('SELECT id, username, email FROM users ORDER BY username').fetchall()

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching API keys: {e}")
        flash("Could not load API keys due to a database error.", "error")

    return render_template('admin/api_keys.html', api_keys=processed_keys, users=users)

@admin_bp.route('/api-keys/create', methods=['POST'])
@admin_required
def admin_create_api_key():
    name = request.form.get('name')
    user_id = request.form.get('user_id', type=int)

    if not name or not user_id:
        flash('Key name and associated user are required.', 'error')
        return redirect(url_for('admin.admin_api_keys'))

    conn = get_db()
    try:
        # Check if user exists
        user = conn.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
            flash('Selected user does not exist.', 'error')
            return redirect(url_for('admin.admin_api_keys'))

        new_key = secrets.token_urlsafe(32)  # Generate a secure random key
        conn.execute('INSERT INTO api_keys (key, name, user_id) VALUES (?, ?, ?)', (new_key, name, user_id))
        conn.commit()
        flash(f'API Key "{name}" created successfully.', 'success')
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error creating API key: {e}")
        flash('A database error occurred while creating the API key.', 'error')

    return redirect(url_for('admin.admin_api_keys'))

@admin_bp.route('/api-keys/toggle/<int:key_id>', methods=['POST'])
@admin_required
def admin_toggle_api_key(key_id):
    conn = get_db()
    try:
        key = conn.execute('SELECT id, is_active FROM api_keys WHERE id = ?', (key_id,)).fetchone()
        if not key:
            flash('API Key not found.', 'error')
            return redirect(url_for('admin.admin_api_keys'))

        new_status = 0 if key['is_active'] else 1
        conn.execute('UPDATE api_keys SET is_active = ? WHERE id = ?', (new_status, key_id))
        conn.commit()
        status_text = "deactivated" if new_status == 0 else "activated"
        flash(f'API Key {status_text} successfully.', 'success')
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error toggling API key (ID: {key_id}): {e}")
        flash('A database error occurred while updating the key status.', 'error')

    return redirect(url_for('admin.admin_api_keys'))

@admin_bp.route('/api-keys/delete/<int:key_id>', methods=['POST'])
@admin_required
def admin_delete_api_key(key_id):
    conn = get_db()
    try:
        # Optional: Check if key exists first
        key = conn.execute('SELECT id FROM api_keys WHERE id = ?', (key_id,)).fetchone()
        if not key:
            flash('API Key not found.', 'error')
            return redirect(url_for('admin.admin_api_keys'))

        # Optional: Consider deleting related logs? For now, we keep them.
        conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
        conn.commit()
        flash('API Key deleted successfully.', 'success')
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error deleting API key (ID: {key_id}): {e}")
        flash('A database error occurred while deleting the API key.', 'error')

    return redirect(url_for('admin.admin_api_keys'))

# --- End API Key Management ---

@admin_bp.route('/dashboard-data')
@admin_required
def admin_dashboard_data():
    conn = get_db()
    data = {
        'total_users': 0, 'total_adventures': 0, 'total_downloads': 0,
        'today_stats': {'page_views': 0, 'logins': 0, 'registrations': 0, 'downloads': 0, 'uploads': 0},
        'trends': {'page_views': 0, 'logins': 0, 'registrations': 0, 'downloads': 0, 'uploads': 0}
    }
    try:
        data['total_users'] = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
        data['total_adventures'] = conn.execute('SELECT COUNT(*) as count FROM adventures WHERE approved = 1').fetchone()['count']
        data['total_downloads'] = conn.execute('SELECT SUM(downloads) as count FROM adventures WHERE approved = 1').fetchone()['count'] or 0

        today = datetime.date.today().isoformat()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

        stat_names = ['page_views', 'logins', 'registrations', 'downloads', 'uploads']
        today_stats = {}
        yesterday_stats = {}

        for stat_name in stat_names:
            today_val_row = conn.execute('SELECT SUM(stat_value) as value FROM statistics WHERE stat_name = ? AND date(date) = ?', (stat_name, today)).fetchone()
            today_stats[stat_name] = today_val_row['value'] if today_val_row and today_val_row['value'] else 0

            yesterday_val_row = conn.execute('SELECT SUM(stat_value) as value FROM statistics WHERE stat_name = ? AND date(date) = ?', (stat_name, yesterday)).fetchone()
            yesterday_stats[stat_name] = yesterday_val_row['value'] if yesterday_val_row and yesterday_val_row['value'] else 0

            # Calculate trend
            today_val = today_stats[stat_name]
            yesterday_val = yesterday_stats[stat_name]
            if yesterday_val == 0:
                data['trends'][stat_name] = 100 if today_val > 0 else 0
            else:
                change = ((today_val - yesterday_val) / yesterday_val) * 100
                data['trends'][stat_name] = round(change)

        data['today_stats'] = today_stats

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching dashboard data: {e}")
        # Return empty/default data on error, maybe set an error flag?
        return jsonify({"error": "Could not fetch dashboard data"}), 500

    return jsonify(data)


@admin_bp.route('/stats')
@admin_required
def admin_stats():
    conn = get_db()
    stats_data = {
        'total_users': 0, 'user_roles': [], 'total_adventures': 0,
        'pending_adventures': 0, 'total_downloads': 0, 'tag_usage': [], 'api_usage': {},
        'daily_stats': {}
    }
    try:
        stats_data['total_users'] = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
        stats_data['user_roles'] = conn.execute('SELECT role, COUNT(*) as count FROM users GROUP BY role').fetchall()
        stats_data['total_adventures'] = conn.execute('SELECT COUNT(*) as count FROM adventures WHERE approved = 1').fetchone()['count']
        stats_data['pending_adventures'] = conn.execute('SELECT COUNT(*) as count FROM adventures WHERE approved = 0').fetchone()['count']
        stats_data['total_downloads'] = conn.execute('SELECT SUM(downloads) as count FROM adventures').fetchone()['count'] or 0
        stats_data['tag_usage'] = conn.execute('''
            SELECT t.name, COUNT(at.adventure_id) as count FROM tags t
            JOIN adventure_tags at ON t.id = at.tag_id JOIN adventures a ON at.adventure_id = a.id
            WHERE a.approved = 1 GROUP BY t.id ORDER BY count DESC LIMIT 10
        ''').fetchall()

        daily_stats = {}
        stat_names = ['page_views', 'logins', 'registrations', 'downloads', 'uploads']
        thirty_days_ago = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

        for stat_name in stat_names:
            rows = conn.execute('''
                SELECT date(date) as day, SUM(stat_value) as value FROM statistics
                WHERE stat_name = ? AND date(date) >= ?
                GROUP BY day ORDER BY day
            ''', (stat_name, thirty_days_ago)).fetchall()
            daily_stats[stat_name] = {'days': [row['day'] for row in rows], 'values': [row['value'] for row in rows]}
        stats_data['daily_stats'] = daily_stats

        # Fetch API usage data (last 30 days, grouped by key name and success)
        api_usage = {}
        api_log_rows = conn.execute('''
            SELECT date(timestamp) as day, api_key_name, success, COUNT(*) as count
            FROM api_logs
            WHERE date(timestamp) >= ?
            GROUP BY day, api_key_name, success
            ORDER BY day
        ''', (thirty_days_ago,)).fetchall()

        # Process API logs into a structure suitable for Chart.js
        # Example structure: { 'KeyName1': {'days': [...], 'success': [...], 'failure': [...]}, ... }
        for row in api_log_rows:
            key_name = row['api_key_name'] if row['api_key_name'] else 'Invalid/Unknown'
            if key_name not in api_usage:
                api_usage[key_name] = {'days': [], 'success': [], 'failure': []}
            # This aggregation might need refinement for charting (e.g., filling missing days)
            # For simplicity, we'll just store counts per day found in logs
            api_usage[key_name]['days'].append(row['day'])
            if row['success']:
                api_usage[key_name]['success'].append(row['count'])
            else:
                api_usage[key_name]['failure'].append(row['count'])
        stats_data['api_usage'] = api_usage

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching admin stats: {e}")
        flash("Could not load statistics due to a database error.", "error")
        # Render template with potentially partial data or defaults

    return render_template('admin/stats.html', **stats_data)

# --- Adventure Management ---

@admin_bp.route('/manage-adventures')
@admin_required
def admin_manage_adventures():
    conn = get_db()
    adventures_list = []
    try:
        # Fetch all adventures, regardless of approval status, along with author username and rating info
        adventures_data = conn.execute('''
            SELECT a.id, a.name, a.description, u.username as author_username, a.author_id,
                   a.creation_date, a.file_path, a.file_size, a.game_version, a.version_compat, a.downloads,
                   a.approved, COALESCE(AVG(r.rating), 0) as avg_rating, COUNT(DISTINCT r.id) as rating_count
            FROM adventures a
            JOIN users u ON a.author_id = u.id
            LEFT JOIN ratings r ON a.id = r.adventure_id
            GROUP BY a.id
            ORDER BY a.creation_date DESC
        ''').fetchall()

        for adv_row in adventures_data:
            adv_dict = dict(adv_row)
            adv_dict['creation_date'] = parse_datetime(adv_dict['creation_date'])
            adventures_list.append(adv_dict)

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching adventures for admin management: {e}")
        flash("Could not load adventures due to a database error.", "danger")

    return render_template('admin/admin_adventures.html', adventures=adventures_list)


@admin_bp.route('/adventure/edit/<int:adventure_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_adventure(adventure_id):
    conn = get_db()
    adventure = conn.execute('SELECT * FROM adventures WHERE id = ?', (adventure_id,)).fetchone()

    if not adventure:
        flash('Adventure not found.', 'danger')
        return redirect(url_for('admin.admin_manage_adventures'))

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        new_tag_ids_str = request.form.getlist('tags')  # List of tag IDs as strings
        game_version = request.form.get('game_version')
        version_compat = request.form.get('version_compat')
        approved = request.form.get('approved', type=int)  # 0 or 1
        file = request.files.get('adventure_file')

        if not name or not description or not game_version or not version_compat or approved not in [0, 1] or not new_tag_ids_str:
            flash('All fields (Name, Description, Tags, Game Version, Engine Compatibility, Approval) are required.', 'danger')
            # Re-fetch data for rendering the form again
            all_tags = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
            current_tag_ids = [row['tag_id'] for row in conn.execute('SELECT tag_id FROM adventure_tags WHERE adventure_id = ?', (adventure_id,)).fetchall()]
            return render_template('admin/edit_adventure.html', adventure=dict(adventure), all_tags=all_tags, current_tag_ids=current_tag_ids, settings=get_site_settings())

        new_tag_ids = [int(tid) for tid in new_tag_ids_str]

        try:
            # Handle file update if a new file is provided
            new_file_path = adventure['file_path']
            new_file_size = adventure['file_size']
            new_game_version = game_version  # Use form input by default
            new_version_compat = version_compat  # Use form input by default

            if file and file.filename:
                if not file.filename.lower().endswith('.zip'):
                    flash('Only ZIP files are allowed for adventure file.', 'danger')
                    # Re-render form
                    all_tags = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
                    current_tag_ids = [row['tag_id'] for row in conn.execute('SELECT tag_id FROM adventure_tags WHERE adventure_id = ?', (adventure_id,)).fetchall()]
                    return render_template('admin/edit_adventure.html', adventure=dict(adventure), all_tags=all_tags, current_tag_ids=current_tag_ids, settings=get_site_settings())

                # File Size Check
                site_settings = get_site_settings()
                max_mb = int(site_settings.get('max_upload_size', 50))
                max_bytes = max_mb * 1024 * 1024
                file.seek(0, os.SEEK_END)
                file_size_new_file = file.tell()
                file.seek(0)
                if file_size_new_file > max_bytes:
                    flash(f'New file size ({file_size_new_file // 1024 // 1024}MB) exceeds the maximum allowed size ({max_mb}MB).', 'danger')
                    all_tags = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
                    current_tag_ids = [row['tag_id'] for row in conn.execute('SELECT tag_id FROM adventure_tags WHERE adventure_id = ?', (adventure_id,)).fetchall()]
                    return render_template('admin/edit_adventure.html', adventure=dict(adventure), all_tags=all_tags, current_tag_ids=current_tag_ids, settings=get_site_settings())

                # Delete old file
                if adventure['file_path'] and os.path.exists(adventure['file_path']):
                    try:
                        os.remove(adventure['file_path'])
                    except OSError as e:
                        current_app.logger.warning(f"Could not delete old file {adventure['file_path']}: {e}")

                # Save new file
                author_username = conn.execute('SELECT username FROM users WHERE id = ?', (adventure['author_id'],)).fetchone()['username']
                timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                safe_base_filename = secure_filename(f"{author_username}_adminedit_{timestamp}.zip")
                upload_folder = current_app.config['UPLOAD_FOLDER']
                new_file_path = os.path.join(upload_folder, safe_base_filename)
                file.save(new_file_path)
                new_file_size = file_size_new_file

                # Extract game_version and version_compat from new zip
                try:
                    with zipfile.ZipFile(new_file_path, 'r') as zip_ref:
                        if 'game_data.json' in zip_ref.namelist():
                            with zip_ref.open('game_data.json') as game_data_file:
                                game_data = json.load(game_data_file)
                                game_info = game_data.get('game_info', {})
                                # Prioritize new zip, fallback to form input
                                new_game_version = game_info.get('version', game_version)
                                new_version_compat = game_info.get('builder_version', version_compat)
                        else:  # If new zip has no game_data.json, keep versions from form
                            flash("Warning: New ZIP file does not contain 'game_data.json'. Versions from form used.", "warning")
                except Exception as e:
                    current_app.logger.warning(f"Could not extract version from new zip {safe_base_filename}: {e}")
                    flash(f"Warning: Could not read 'game_data.json' from new ZIP: {e}. Versions from form used.", "warning")

            # Update adventure details
            conn.execute('''
                UPDATE adventures 
                SET name = ?, description = ?, game_version = ?, version_compat = ?, approved = ?, file_path = ?, file_size = ?
                WHERE id = ?
            ''', (name, description, new_game_version, new_version_compat, approved, new_file_path, new_file_size, adventure_id))

            # Update tags: remove old, add new
            conn.execute('DELETE FROM adventure_tags WHERE adventure_id = ?', (adventure_id,))
            for tag_id in new_tag_ids:
                conn.execute('INSERT INTO adventure_tags (adventure_id, tag_id) VALUES (?, ?)', (adventure_id, tag_id))

            conn.commit()
            flash('Adventure updated successfully.', 'success')
            return redirect(url_for('admin.admin_manage_adventures'))

        except sqlite3.Error as e:
            conn.rollback()
            current_app.logger.error(f"Database error editing adventure {adventure_id}: {e}")
            flash('A database error occurred while updating the adventure.', 'danger')
        except Exception as e:
            conn.rollback()
            current_app.logger.error(f"Error editing adventure {adventure_id}: {e}")
            flash(f'An unexpected error occurred: {e}', 'danger')

    # GET request
    all_tags = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
    current_tag_ids_rows = conn.execute('SELECT tag_id FROM adventure_tags WHERE adventure_id = ?', (adventure_id,)).fetchall()
    current_tag_ids = [row['tag_id'] for row in current_tag_ids_rows]
    
    # Add basename filter to Jinja environment if not already present
    # This is usually done in create_app, but for simplicity here:
    current_app.jinja_env.filters['basename'] = os.path.basename

    return render_template('admin/edit_adventure.html', adventure=dict(adventure), all_tags=all_tags, current_tag_ids=current_tag_ids, settings=get_site_settings())


@admin_bp.route('/adventure/delete/<int:adventure_id>', methods=['POST'])
@admin_required
def admin_delete_adventure(adventure_id):
    conn = get_db()
    try:
        adventure = conn.execute('SELECT file_path, name FROM adventures WHERE id = ?', (adventure_id,)).fetchone()
        if not adventure:
            flash('Adventure not found.', 'danger')
            return redirect(url_for('admin.admin_manage_adventures'))

        # Start transaction
        conn.execute('BEGIN TRANSACTION')
        conn.execute('DELETE FROM adventure_tags WHERE adventure_id = ?', (adventure_id,))
        conn.execute('DELETE FROM ratings WHERE adventure_id = ?', (adventure_id,))
        conn.execute('DELETE FROM reviews WHERE adventure_id = ?', (adventure_id,))
        conn.execute('DELETE FROM notifications WHERE related_id = ? AND (type = "moderation" OR type = "approval" OR type = "rejection")', (adventure_id,))  # Delete related notifications
        conn.execute('DELETE FROM adventures WHERE id = ?', (adventure_id,))

        # Delete the file
        if adventure['file_path'] and os.path.exists(adventure['file_path']):
            try:
                os.remove(adventure['file_path'])
                current_app.logger.info(f"Admin deleted adventure file: {adventure['file_path']}")
            except OSError as e:
                current_app.logger.error(f"Error deleting adventure file {adventure['file_path']} by admin: {e}")
                # Non-critical, proceed with DB deletion but warn admin
                flash(f"Adventure '{adventure['name']}' database entries deleted, but failed to delete the associated file: {e}", 'warning')

        conn.commit()
        flash(f"Adventure '{adventure['name']}' and all its associated data deleted successfully.", 'success')

    except sqlite3.Error as e:
        conn.rollback()
        current_app.logger.error(f"Database error deleting adventure {adventure_id}: {e}")
        flash('A database error occurred while deleting the adventure.', 'danger')
    except Exception as e:
        conn.rollback()
        current_app.logger.error(f"Unexpected error deleting adventure {adventure_id}: {e}")
        flash(f'An unexpected error occurred: {e}', 'danger')

    return redirect(url_for('admin.admin_manage_adventures'))

# --- End Adventure Management ---

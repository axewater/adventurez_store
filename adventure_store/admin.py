from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
)
from .db import get_db
from .utils import parse_datetime, log_statistic, hash_password
from .decorators import admin_required
import datetime
import sqlite3

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
        log_statistic('registrations') # Log admin-added user
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
        if theme not in ['light', 'dark']:
            flash('Invalid theme selected', 'error')
            return redirect(url_for('admin.admin_settings'))
        try:
            conn.execute("UPDATE site_settings SET setting_value = ? WHERE setting_name = 'theme'", (theme,))
            conn.commit()
            flash('Settings updated successfully', 'success')
        except sqlite3.Error as e:
            current_app.logger.error(f"Database error updating settings: {e}")
            flash('A database error occurred while updating settings.', 'error')
        return redirect(url_for('admin.admin_settings'))

    # GET request handled by context processor, just render template
    return render_template('admin/settings.html')

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
        'pending_adventures': 0, 'total_downloads': 0, 'tag_usage': [],
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

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching admin stats: {e}")
        flash("Could not load statistics due to a database error.", "error")
        # Render template with potentially partial data or defaults

    return render_template('admin/stats.html', **stats_data)

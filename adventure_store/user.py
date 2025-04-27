from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, current_app
)
from werkzeug.utils import secure_filename
from .db import get_db
from .utils import parse_datetime, log_statistic
from .decorators import login_required
import os
import datetime
import zipfile
import json
import sqlite3

user_bp = Blueprint('user', __name__)

@user_bp.route('/rate/<int:adventure_id>', methods=['POST'])
@login_required
def rate_adventure(adventure_id):
    rating = request.form.get('rating', type=int)
    if not rating or not 1 <= rating <= 5:
        flash('Invalid rating value.', 'error')
        return redirect(url_for('main.adventure_detail', adventure_id=adventure_id))

    conn = get_db()
    try:
        adventure = conn.execute('SELECT id FROM adventures WHERE id = ? AND approved = 1', (adventure_id,)).fetchone()
        if not adventure:
            flash('Adventure not found or not approved.', 'error')
            return redirect(url_for('main.adventures'))

        existing_rating = conn.execute('SELECT id FROM ratings WHERE adventure_id = ? AND user_id = ?', (adventure_id, session['user_id'])).fetchone()
        if existing_rating:
            conn.execute('UPDATE ratings SET rating = ?, created_at = ? WHERE id = ?', (rating, datetime.datetime.now(), existing_rating['id']))
        else:
            conn.execute('INSERT INTO ratings (adventure_id, user_id, rating) VALUES (?, ?, ?)', (adventure_id, session['user_id'], rating))
        conn.commit()
        flash('Rating submitted successfully.', 'success')
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error rating adventure (ID: {adventure_id}): {e}")
        flash('Could not submit rating due to a database error.', 'error')

    return redirect(url_for('main.adventure_detail', adventure_id=adventure_id))


@user_bp.route('/review/<int:adventure_id>', methods=['POST'])
@login_required
def add_review(adventure_id):
    content = request.form.get('content')
    if not content:
        flash('Review content cannot be empty.', 'error')
        return redirect(url_for('main.adventure_detail', adventure_id=adventure_id))

    conn = get_db()
    try:
        adventure = conn.execute('SELECT id FROM adventures WHERE id = ? AND approved = 1', (adventure_id,)).fetchone()
        if not adventure:
            flash('Adventure not found or not approved.', 'error')
            return redirect(url_for('main.adventures'))

        conn.execute('INSERT INTO reviews (adventure_id, user_id, content) VALUES (?, ?, ?)', (adventure_id, session['user_id'], content))
        conn.commit()
        flash('Review added successfully.', 'success')
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error adding review (Adventure ID: {adventure_id}): {e}")
        flash('Could not add review due to a database error.', 'error')

    return redirect(url_for('main.adventure_detail', adventure_id=adventure_id))


@user_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_adventure():
    conn = get_db()
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        tags = request.form.getlist('tags') # List of tag IDs
        file = request.files.get('adventure_file')

        if not name or not description or not tags or not file or file.filename == '':
            flash('All fields and a file are required.', 'error')
            # Fetch tags again for rendering the form with error
            tags_data = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
            return render_template('upload.html', tags=tags_data)

        if not file.filename.lower().endswith('.zip'):
            flash('Only ZIP files are allowed.', 'error')
            tags_data = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
            return render_template('upload.html', tags=tags_data)

        # Secure filename and create path
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        safe_base_filename = secure_filename(f"{session['username']}_{timestamp}.zip")
        # Store path relative to instance or static/uploads? Let's use UPLOAD_FOLDER config
        upload_folder = current_app.config['UPLOAD_FOLDER']
        file_path = os.path.join(upload_folder, safe_base_filename)

        try:
            # Save file
            file.save(file_path)
            file_size = os.path.getsize(file_path)

            # Extract version compatibility
            version_compat = "Unknown"
            try:
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    if 'game_data.json' in zip_ref.namelist():
                        with zip_ref.open('game_data.json') as game_data_file:
                            game_data = json.load(game_data_file)
                            version_compat = game_data.get('version', 'Unknown')
            except Exception as e:
                current_app.logger.warning(f"Could not extract version from {safe_base_filename}: {e}")

            # Insert into DB
            cursor = conn.execute(
                'INSERT INTO adventures (name, description, author_id, file_path, file_size, version_compat, approved) VALUES (?, ?, ?, ?, ?, ?, 0)',
                (name, description, session['user_id'], file_path, file_size, version_compat)
            )
            adventure_id = cursor.lastrowid

            # Add tags
            for tag_id in tags:
                conn.execute('INSERT INTO adventure_tags (adventure_id, tag_id) VALUES (?, ?)', (adventure_id, tag_id))

            # Notify moderators
            moderators = conn.execute("SELECT id FROM users WHERE role IN ('admin', 'moderator')").fetchall()
            for mod in moderators:
                conn.execute(
                    'INSERT INTO notifications (user_id, content, type, related_id) VALUES (?, ?, ?, ?)',
                    (mod['id'], f"New adventure '{name}' needs approval", 'moderation', adventure_id)
                )

            conn.commit()
            log_statistic('uploads')
            flash('Adventure uploaded successfully and is pending approval.', 'success')
            return redirect(url_for('user.my_adventures'))

        except sqlite3.Error as e:
            current_app.logger.error(f"Database error uploading adventure: {e}")
            flash('A database error occurred during upload.', 'error')
        except Exception as e:
            current_app.logger.error(f"File handling error during upload: {e}")
            flash(f'An error occurred: {e}', 'error')
            # Clean up potentially saved file if DB insert failed
            if 'adventure_id' not in locals() and os.path.exists(file_path):
                 try: os.remove(file_path)
                 except OSError: pass

        # If we reached here, an error occurred, fetch tags and render form again
        tags_data = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
        return render_template('upload.html', tags=tags_data)

    # GET request
    tags_data = []
    try:
        tags_data = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching tags for upload form: {e}")
        flash('Could not load tags for the upload form.', 'error')
    return render_template('upload.html', tags=tags_data)


@user_bp.route('/my-adventures')
@login_required
def my_adventures():
    conn = get_db()
    processed_adventures = []
    try:
        adventures_data = conn.execute('''
            SELECT a.id, a.name, a.description, a.creation_date, a.approved,
                   COALESCE(AVG(r.rating), 0) as avg_rating, COUNT(DISTINCT r.id) as rating_count,
                   a.downloads
            FROM adventures a
            LEFT JOIN ratings r ON a.id = r.adventure_id
            WHERE a.author_id = ?
            GROUP BY a.id
            ORDER BY a.creation_date DESC
        ''', (session['user_id'],)).fetchall()

        for adv in adventures_data:
            adv_dict = dict(adv)
            adv_dict['creation_date'] = parse_datetime(adv_dict['creation_date'])
            processed_adventures.append(adv_dict)
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching user's adventures: {e}")
        flash("Could not load your adventures due to a database error.", "error")

    return render_template('my_adventures.html', adventures=processed_adventures)


@user_bp.route('/notifications')
@login_required
def notifications():
    conn = get_db()
    processed_notifications = []
    try:
        notifications_data = conn.execute('''
            SELECT id, content, type, related_id, is_read, created_at
            FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (session['user_id'],)).fetchall()

        for notif in notifications_data:
            notif_dict = dict(notif)
            notif_dict['created_at'] = parse_datetime(notif_dict['created_at'])
            processed_notifications.append(notif_dict)

        # Mark all as read (consider doing this via AJAX on page load instead)
        conn.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0', (session['user_id'],))
        conn.commit()

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching notifications: {e}")
        flash("Could not load notifications due to a database error.", "error")

    return render_template('notifications.html', notifications=processed_notifications)

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    session, send_from_directory, current_app
)
from .db import get_db
from .utils import parse_datetime, log_statistic
from .decorators import login_required

import os
import sqlite3

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    log_statistic('page_views')
    conn = get_db()
    processed_featured = []
    processed_recent = []
    tags = []

    try:
        # Get featured adventures
        query_common_fields = '''a.id, a.name, a.description, u.username as author, a.creation_date, a.file_size,
                   a.game_version, a.version_compat, a.downloads, COALESCE(AVG(r.rating), 0) as avg_rating,'''
        featured = conn.execute(f'''
            SELECT {query_common_fields}
                   COUNT(DISTINCT r.id) as rating_count
            FROM adventures a
            JOIN users u ON a.author_id = u.id
            LEFT JOIN ratings r ON a.id = r.adventure_id
            WHERE a.approved = 1
            GROUP BY a.id
            ORDER BY avg_rating DESC, downloads DESC
            LIMIT 6
        ''').fetchall()
        for adv in featured:
            adv_dict = dict(adv)
            adv_dict['creation_date'] = parse_datetime(adv_dict['creation_date'])
            processed_featured.append(adv_dict)

        # Get recent adventures
        recent = conn.execute('''
            SELECT a.id, a.name, a.description, u.username as author, a.creation_date, a.game_version, a.version_compat
            FROM adventures a 
            JOIN users u ON a.author_id = u.id
            WHERE a.approved = 1
            ORDER BY a.creation_date DESC
            LIMIT 6
        ''').fetchall()
        processed_recent = [dict(adv) for adv in recent]
        for adv in processed_recent:
            adv['creation_date'] = parse_datetime(adv['creation_date'])

        # Get popular tags
        tags = conn.execute('''
            SELECT t.id, t.name, COUNT(at.adventure_id) as adventure_count
            FROM tags t
            JOIN adventure_tags at ON t.id = at.tag_id
            JOIN adventures a ON at.adventure_id = a.id
            WHERE a.approved = 1
            GROUP BY t.id
            ORDER BY adventure_count DESC
            LIMIT 10
        ''').fetchall()

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error on index page: {e}")
        flash("Could not load page data. Please try again later.", "error")

    return render_template('index.html', featured=processed_featured, recent=processed_recent, tags=tags)


@main_bp.route('/adventures')
def adventures():
    log_statistic('page_views')
    tag_id = request.args.get('tag', type=int)
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'newest')
    conn = get_db()
    processed_adventures = []
    tags = []

    try:
        query = '''
            SELECT a.id, a.name, a.description, u.username as author, a.creation_date, a.file_size, 
                   a.game_version, a.version_compat, a.downloads, COALESCE(AVG(r.rating), 0) as avg_rating,
                   COUNT(DISTINCT r.id) as rating_count
            FROM adventures a
            JOIN users u ON a.author_id = u.id
            LEFT JOIN ratings r ON a.id = r.adventure_id
        '''
        params = []
        where_clauses = ['a.approved = 1']

        if tag_id:
            query += ' JOIN adventure_tags at ON a.id = at.adventure_id'
            where_clauses.append('at.tag_id = ?')
            params.append(tag_id)
        if search:
            where_clauses.append('(a.name LIKE ? OR a.description LIKE ?)')
            search_param = f'%{search}%'
            params.extend([search_param, search_param])
        if where_clauses:
            query += ' WHERE ' + ' AND '.join(where_clauses)

        query += ' GROUP BY a.id'

        order_map = {
            'newest': ' ORDER BY a.creation_date DESC',
            'oldest': ' ORDER BY a.creation_date ASC',
            'highest_rated': ' ORDER BY avg_rating DESC',
            'most_downloaded': ' ORDER BY a.downloads DESC'
        }
        query += order_map.get(sort, ' ORDER BY a.creation_date DESC')

        adventures_data = conn.execute(query, params).fetchall()
        for adv in adventures_data:
            adv_dict = dict(adv)
            adv_dict['creation_date'] = parse_datetime(adv_dict['creation_date'])
            processed_adventures.append(adv_dict)

        tags = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error on adventures page: {e}")
        flash("Could not load adventures. Please try again later.", "error")

    return render_template('adventures.html', adventures=processed_adventures, tags=tags,
                          current_tag=tag_id, search=search, sort=sort)


@main_bp.route('/adventure/<int:adventure_id>')
def adventure_detail(adventure_id):
    log_statistic('page_views')
    conn = get_db()
    adventure_dict = None
    tags = []
    processed_reviews = []
    user_rating = None

    try:
        adventure = conn.execute('''
            SELECT a.id, a.name, a.description, u.username as author, a.author_id, 
                   a.creation_date, a.file_path, a.file_size, a.game_version, a.version_compat, a.downloads,
                   COALESCE(AVG(r.rating), 0) as avg_rating, COUNT(DISTINCT r.id) as rating_count
            FROM adventures a
            JOIN users u ON a.author_id = u.id
            LEFT JOIN ratings r ON a.id = r.adventure_id
            WHERE a.id = ? AND a.approved = 1
            GROUP BY a.id
        ''', (adventure_id,)).fetchone()

        if not adventure:
            flash('Adventure not found or not approved', 'error')
            return redirect(url_for('main.adventures'))

        adventure_dict = dict(adventure)
        adventure_dict['creation_date'] = parse_datetime(adventure_dict['creation_date'])

        tags = conn.execute('SELECT t.id, t.name FROM tags t JOIN adventure_tags at ON t.id = at.tag_id WHERE at.adventure_id = ?', (adventure_id,)).fetchall()
        reviews = conn.execute('SELECT r.id, r.content, r.created_at, u.username, r.user_id FROM reviews r JOIN users u ON r.user_id = u.id WHERE r.adventure_id = ? ORDER BY r.created_at DESC', (adventure_id,)).fetchall()
        for review in reviews:
            review_dict = dict(review)
            review_dict['created_at'] = parse_datetime(review_dict['created_at'])
            processed_reviews.append(review_dict)

        if 'user_id' in session:
            rating_row = conn.execute('SELECT rating FROM ratings WHERE adventure_id = ? AND user_id = ?', (adventure_id, session['user_id'])).fetchone()
            if rating_row:
                user_rating = rating_row['rating']

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error on adventure detail page (ID: {adventure_id}): {e}")
        flash("Could not load adventure details. Please try again later.", "error")
        return redirect(url_for('main.adventures'))

    return render_template('adventure_detail.html', adventure=adventure_dict, tags=tags,
                          reviews=processed_reviews, user_rating=user_rating)


@main_bp.route('/download/<int:adventure_id>')
@login_required
def download_adventure(adventure_id):
    conn = get_db()
    adventure = None
    try:
        adventure = conn.execute('SELECT id, name, file_path FROM adventures WHERE id = ? AND approved = 1', (adventure_id,)).fetchone()

        if not adventure:
            flash('Adventure not found or not approved', 'error')
            return redirect(url_for('main.adventures'))

        # Update download count
        conn.execute('UPDATE adventures SET downloads = downloads + 1 WHERE id = ?', (adventure_id,))
        conn.commit()
        log_statistic('downloads')

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error downloading adventure (ID: {adventure_id}): {e}")
        flash("Could not process download. Please try again later.", "error")
        return redirect(url_for('main.adventure_detail', adventure_id=adventure_id))

    if adventure and adventure['file_path']:
        try:
            # Construct absolute path from stored relative path
            # Assuming file_path is stored relative to the UPLOAD_FOLDER config
            directory = current_app.config['UPLOAD_FOLDER']
            filename = os.path.basename(adventure['file_path'])
            # Ensure the constructed path is safe and within the intended directory
            safe_path = os.path.abspath(os.path.join(directory, filename))
            if not safe_path.startswith(os.path.abspath(directory)):
                 raise ValueError("Attempted path traversal")

            return send_from_directory(directory, filename, as_attachment=True,
                                      download_name=f"{adventure['name']}.zip")
        except Exception as e:
            current_app.logger.error(f"File serving error for {adventure['file_path']}: {e}")
            flash('Error serving the file.', 'error')
            return redirect(url_for('main.adventure_detail', adventure_id=adventure_id))
    else:
        # Fallback if adventure or file_path was somehow null after initial check
        flash('Adventure file path is missing.', 'error')
        return redirect(url_for('main.adventure_detail', adventure_id=adventure_id))

@main_bp.route('/favicon.ico')
def favicon():
    # Use current_app.static_folder which points to the correct /static directory
    return send_from_directory(current_app.static_folder,
                               'favicon.ico',
                               mimetype='image/vnd.microsoft.icon')

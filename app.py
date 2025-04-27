from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
import sqlite3
import os
import hashlib
import datetime
import zipfile
import json
import secrets
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload size
app.config['DATABASE'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance/adventure_store.db')

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database helper functions
def get_db_connection():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Authentication decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'error')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'error')
            return redirect(url_for('login', next=request.url))
        
        conn = get_db_connection()
        user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if user['role'] != 'admin':
            flash('You do not have permission to access this page', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def moderator_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'error')
            return redirect(url_for('login', next=request.url))
        
        conn = get_db_connection()
        user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if user['role'] not in ['admin', 'moderator']:
            flash('You do not have permission to access this page', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Helper function to get site settings
def get_site_settings():
    conn = get_db_connection()
    settings = {}
    for row in conn.execute('SELECT setting_name, setting_value FROM site_settings').fetchall():
        settings[row['setting_name']] = row['setting_value']
    conn.close()
    return settings

# Helper function to get pending moderation count
def get_pending_moderation_count():
    if 'user_id' not in session:
        return 0
        
    conn = get_db_connection()
    user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    if user and user['role'] in ['admin', 'moderator']:
        count = conn.execute('SELECT COUNT(*) as count FROM adventures WHERE approved = 0').fetchone()['count']
    else:
        count = 0
    
    conn.close()
    return count

# Helper function to log statistics
def log_statistic(stat_name, increment=1):
    conn = get_db_connection()
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
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
            (stat_name, increment, today)
        )
    
    conn.commit()
    conn.close()

# Context processor to make settings available in all templates
@app.context_processor
def inject_settings():
    settings = get_site_settings()
    pending_count = get_pending_moderation_count()
    return dict(settings=settings, pending_moderation_count=pending_count)

# Routes
@app.route('/')
def index():
    log_statistic('page_views')
    
    conn = get_db_connection()
    # Get featured adventures (approved and with highest ratings)
    featured = conn.execute('''
        SELECT a.id, a.name, a.description, u.username as author, a.creation_date, a.file_size,
               a.version_compat, a.downloads, COALESCE(AVG(r.rating), 0) as avg_rating,
               COUNT(DISTINCT r.id) as rating_count
        FROM adventures a
        JOIN users u ON a.author_id = u.id
        LEFT JOIN ratings r ON a.id = r.adventure_id
        WHERE a.approved = 1
        GROUP BY a.id
        ORDER BY avg_rating DESC, downloads DESC
        LIMIT 6
    ''').fetchall()
    
    # Get recent adventures
    recent = conn.execute('''
        SELECT a.id, a.name, a.description, u.username as author, a.creation_date
        FROM adventures a
        JOIN users u ON a.author_id = u.id
        WHERE a.approved = 1
        ORDER BY a.creation_date DESC
        LIMIT 6
    ''').fetchall()
    
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
    
    conn.close()
    
    return render_template('index.html', featured=featured, recent=recent, tags=tags)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if not username or not email or not password:
            flash('All fields are required', 'error')
            return redirect(url_for('register'))
            
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('register'))
        
        conn = get_db_connection()
        
        # Check if username or email already exists
        existing_user = conn.execute(
            'SELECT id FROM users WHERE username = ? OR email = ?', 
            (username, email)
        ).fetchone()
        
        if existing_user:
            conn.close()
            flash('Username or email already exists', 'error')
            return redirect(url_for('register'))
        
        # Create new user
        hashed_password = hash_password(password)
        conn.execute(
            'INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)',
            (username, email, hashed_password, 'user')
        )
        conn.commit()
        
        # Get the new user's ID
        user_id = conn.execute(
            'SELECT id FROM users WHERE username = ?', (username,)
        ).fetchone()['id']
        
        conn.close()
        
        # Log the registration
        log_statistic('registrations')
        
        # Set session and redirect
        session['user_id'] = user_id
        session['username'] = username
        session['role'] = 'user'
        
        flash('Registration successful! Welcome to Text Adventure Builder Store.', 'success')
        return redirect(url_for('index'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        if not email or not password:
            flash('Email and password are required', 'error')
            return redirect(url_for('login'))
        
        conn = get_db_connection()
        hashed_password = hash_password(password)
        
        user = conn.execute(
            'SELECT id, username, role FROM users WHERE email = ? AND password = ?',
            (email, hashed_password)
        ).fetchone()
        
        if user:
            # Update last login time
            conn.execute(
                'UPDATE users SET last_login = ? WHERE id = ?',
                (datetime.datetime.now(), user['id'])
            )
            conn.commit()
            
            # Set session variables
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            # Log the login
            log_statistic('logins')
            
            conn.close()
            
            # Redirect to next page if provided, otherwise to home
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            conn.close()
            flash('Invalid email or password', 'error')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

@app.route('/adventures')
def adventures():
    log_statistic('page_views')
    
    # Get filter parameters
    tag_id = request.args.get('tag', type=int)
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'newest')
    
    conn = get_db_connection()
    
    # Base query
    query = '''
        SELECT a.id, a.name, a.description, u.username as author, a.creation_date, a.file_size,
               a.version_compat, a.downloads, COALESCE(AVG(r.rating), 0) as avg_rating,
               COUNT(DISTINCT r.id) as rating_count
        FROM adventures a
        JOIN users u ON a.author_id = u.id
        LEFT JOIN ratings r ON a.id = r.adventure_id
    '''
    
    params = []
    where_clauses = ['a.approved = 1']
    
    # Add tag filter if specified
    if tag_id:
        query += ' JOIN adventure_tags at ON a.id = at.adventure_id'
        where_clauses.append('at.tag_id = ?')
        params.append(tag_id)
    
    # Add search filter if specified
    if search:
        where_clauses.append('(a.name LIKE ? OR a.description LIKE ?)')
        search_param = f'%{search}%'
        params.extend([search_param, search_param])
    
    # Add WHERE clause
    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)
    
    # Add GROUP BY
    query += ' GROUP BY a.id'
    
    # Add ORDER BY based on sort parameter
    if sort == 'newest':
        query += ' ORDER BY a.creation_date DESC'
    elif sort == 'oldest':
        query += ' ORDER BY a.creation_date ASC'
    elif sort == 'highest_rated':
        query += ' ORDER BY avg_rating DESC'
    elif sort == 'most_downloaded':
        query += ' ORDER BY a.downloads DESC'
    else:
        query += ' ORDER BY a.creation_date DESC'
    
    adventures = conn.execute(query, params).fetchall()
    
    # Get all tags for filtering
    tags = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
    
    conn.close()
    
    return render_template('adventures.html', adventures=adventures, tags=tags, 
                          current_tag=tag_id, search=search, sort=sort)

@app.route('/adventure/<int:adventure_id>')
def adventure_detail(adventure_id):
    log_statistic('page_views')
    
    conn = get_db_connection()
    
    # Get adventure details
    adventure = conn.execute('''
        SELECT a.id, a.name, a.description, u.username as author, a.author_id,
               a.creation_date, a.file_path, a.file_size, a.version_compat, a.downloads,
               COALESCE(AVG(r.rating), 0) as avg_rating, COUNT(DISTINCT r.id) as rating_count
        FROM adventures a
        JOIN users u ON a.author_id = u.id
        LEFT JOIN ratings r ON a.id = r.adventure_id
        WHERE a.id = ? AND a.approved = 1
        GROUP BY a.id
    ''', (adventure_id,)).fetchone()
    
    if not adventure:
        conn.close()
        flash('Adventure not found', 'error')
        return redirect(url_for('adventures'))
    
    # Get tags for this adventure
    tags = conn.execute('''
        SELECT t.id, t.name
        FROM tags t
        JOIN adventure_tags at ON t.id = at.tag_id
        WHERE at.adventure_id = ?
    ''', (adventure_id,)).fetchall()
    
    # Get reviews for this adventure
    reviews = conn.execute('''
        SELECT r.id, r.content, r.created_at, u.username, r.user_id
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.adventure_id = ?
        ORDER BY r.created_at DESC
    ''', (adventure_id,)).fetchall()
    
    # Check if current user has rated this adventure
    user_rating = None
    if 'user_id' in session:
        user_rating = conn.execute('''
            SELECT rating FROM ratings
            WHERE adventure_id = ? AND user_id = ?
        ''', (adventure_id, session['user_id'])).fetchone()
        
        if user_rating:
            user_rating = user_rating['rating']
    
    conn.close()
    
    return render_template('adventure_detail.html', adventure=adventure, tags=tags, 
                          reviews=reviews, user_rating=user_rating)

@app.route('/download/<int:adventure_id>')
@login_required
def download_adventure(adventure_id):
    conn = get_db_connection()
    
    adventure = conn.execute('''
        SELECT id, name, file_path
        FROM adventures
        WHERE id = ? AND approved = 1
    ''', (adventure_id,)).fetchone()
    
    if not adventure:
        conn.close()
        flash('Adventure not found', 'error')
        return redirect(url_for('adventures'))
    
    # Update download count
    conn.execute('''
        UPDATE adventures
        SET downloads = downloads + 1
        WHERE id = ?
    ''', (adventure_id,))
    conn.commit()
    
    # Log the download
    log_statistic('downloads')
    
    conn.close()
    
    # Get the directory and filename
    directory = os.path.dirname(adventure['file_path'])
    filename = os.path.basename(adventure['file_path'])
    
    return send_from_directory(directory, filename, as_attachment=True, 
                              download_name=f"{adventure['name']}.zip")

@app.route('/rate/<int:adventure_id>', methods=['POST'])
@login_required
def rate_adventure(adventure_id):
    rating = request.form.get('rating', type=int)
    
    if not rating or rating < 1 or rating > 5:
        flash('Invalid rating', 'error')
        return redirect(url_for('adventure_detail', adventure_id=adventure_id))
    
    conn = get_db_connection()
    
    # Check if adventure exists and is approved
    adventure = conn.execute('''
        SELECT id FROM adventures
        WHERE id = ? AND approved = 1
    ''', (adventure_id,)).fetchone()
    
    if not adventure:
        conn.close()
        flash('Adventure not found', 'error')
        return redirect(url_for('adventures'))
    
    # Check if user has already rated this adventure
    existing_rating = conn.execute('''
        SELECT id FROM ratings
        WHERE adventure_id = ? AND user_id = ?
    ''', (adventure_id, session['user_id'])).fetchone()
    
    if existing_rating:
        # Update existing rating
        conn.execute('''
            UPDATE ratings
            SET rating = ?, created_at = ?
            WHERE adventure_id = ? AND user_id = ?
        ''', (rating, datetime.datetime.now(), adventure_id, session['user_id']))
    else:
        # Create new rating
        conn.execute('''
            INSERT INTO ratings (adventure_id, user_id, rating)
            VALUES (?, ?, ?)
        ''', (adventure_id, session['user_id'], rating))
    
    conn.commit()
    conn.close()
    
    flash('Rating submitted successfully', 'success')
    return redirect(url_for('adventure_detail', adventure_id=adventure_id))

@app.route('/review/<int:adventure_id>', methods=['POST'])
@login_required
def add_review(adventure_id):
    content = request.form.get('content')
    
    if not content:
        flash('Review content is required', 'error')
        return redirect(url_for('adventure_detail', adventure_id=adventure_id))
    
    conn = get_db_connection()
    
    # Check if adventure exists and is approved
    adventure = conn.execute('''
        SELECT id FROM adventures
        WHERE id = ? AND approved = 1
    ''', (adventure_id,)).fetchone()
    
    if not adventure:
        conn.close()
        flash('Adventure not found', 'error')
        return redirect(url_for('adventures'))
    
    # Add review
    conn.execute('''
        INSERT INTO reviews (adventure_id, user_id, content)
        VALUES (?, ?, ?)
    ''', (adventure_id, session['user_id'], content))
    
    conn.commit()
    conn.close()
    
    flash('Review added successfully', 'success')
    return redirect(url_for('adventure_detail', adventure_id=adventure_id))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_adventure():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        tags = request.form.getlist('tags')
        
        # Validate form data
        if not name or not description or not tags:
            flash('All fields are required', 'error')
            return redirect(url_for('upload_adventure'))
        
        # Check if file was uploaded
        if 'adventure_file' not in request.files:
            flash('No file part', 'error')
            return redirect(url_for('upload_adventure'))
            
        file = request.files['adventure_file']
        
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(url_for('upload_adventure'))
        
        if not file.filename.endswith('.zip'):
            flash('Only ZIP files are allowed', 'error')
            return redirect(url_for('upload_adventure'))
        
        # Save the file
        filename = secure_filename(f"{session['username']}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.zip")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        # Extract version compatibility from zip file
        version_compat = "Unknown"
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                if 'game_data.json' in zip_ref.namelist():
                    with zip_ref.open('game_data.json') as game_data_file:
                        game_data = json.load(game_data_file)
                        if 'version' in game_data:
                            version_compat = game_data['version']
        except Exception as e:
            app.logger.error(f"Error extracting version from zip: {e}")
        
        conn = get_db_connection()
        
        # Insert adventure
        cursor = conn.execute('''
            INSERT INTO adventures (name, description, author_id, file_path, file_size, version_compat)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, description, session['user_id'], file_path, file_size, version_compat))
        
        adventure_id = cursor.lastrowid
        
        # Add tags
        for tag_id in tags:
            conn.execute('''
                INSERT INTO adventure_tags (adventure_id, tag_id)
                VALUES (?, ?)
            ''', (adventure_id, tag_id))
        
        # Create notification for moderators
        moderators = conn.execute('''
            SELECT id FROM users
            WHERE role IN ('admin', 'moderator')
        ''').fetchall()
        
        for mod in moderators:
            conn.execute('''
                INSERT INTO notifications (user_id, content, type, related_id)
                VALUES (?, ?, ?, ?)
            ''', (mod['id'], f"New adventure '{name}' needs approval", 'moderation', adventure_id))
        
        conn.commit()
        conn.close()
        
        # Log the upload
        log_statistic('uploads')
        
        flash('Adventure uploaded successfully and is pending approval', 'success')
        return redirect(url_for('my_adventures'))
    
    # GET request - show upload form
    conn = get_db_connection()
    tags = conn.execute('SELECT id, name FROM tags ORDER BY name').fetchall()
    conn.close()
    
    return render_template('upload.html', tags=tags)

@app.route('/my-adventures')
@login_required
def my_adventures():
    conn = get_db_connection()
    
    adventures = conn.execute('''
        SELECT a.id, a.name, a.description, a.creation_date, a.approved,
               COALESCE(AVG(r.rating), 0) as avg_rating, COUNT(DISTINCT r.id) as rating_count,
               a.downloads
        FROM adventures a
        LEFT JOIN ratings r ON a.id = r.adventure_id
        WHERE a.author_id = ?
        GROUP BY a.id
        ORDER BY a.creation_date DESC
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    return render_template('my_adventures.html', adventures=adventures)

@app.route('/moderate')
@moderator_required
def moderate():
    conn = get_db_connection()
    
    # Get pending adventures
    pending = conn.execute('''
        SELECT a.id, a.name, a.description, u.username as author, a.creation_date,
               a.file_size, a.version_compat
        FROM adventures a
        JOIN users u ON a.author_id = u.id
        WHERE a.approved = 0
        ORDER BY a.creation_date ASC
    ''').fetchall()
    
    # Mark notifications as read
    if 'user_id' in session:
        conn.execute('''
            UPDATE notifications
            SET is_read = 1
            WHERE user_id = ? AND type = 'moderation'
        ''', (session['user_id'],))
        conn.commit()
    
    conn.close()
    
    return render_template('moderate.html', pending=pending)

@app.route('/moderate/<int:adventure_id>', methods=['POST'])
@moderator_required
def moderate_adventure(adventure_id):
    action = request.form.get('action')
    
    if action not in ['approve', 'reject']:
        flash('Invalid action', 'error')
        return redirect(url_for('moderate'))
    
    conn = get_db_connection()
    
    adventure = conn.execute('''
        SELECT id, name, author_id, file_path
        FROM adventures
        WHERE id = ? AND approved = 0
    ''', (adventure_id,)).fetchone()
    
    if not adventure:
        conn.close()
        flash('Adventure not found or already moderated', 'error')
        return redirect(url_for('moderate'))
    
    if action == 'approve':
        # Approve the adventure
        conn.execute('''
            UPDATE adventures
            SET approved = 1
            WHERE id = ?
        ''', (adventure_id,))
        
        # Notify the author
        conn.execute('''
            INSERT INTO notifications (user_id, content, type, related_id)
            VALUES (?, ?, ?, ?)
        ''', (adventure['author_id'], f"Your adventure '{adventure['name']}' has been approved", 'approval', adventure_id))
        
        flash('Adventure approved successfully', 'success')
    else:
        # Reject the adventure
        conn.execute('''
            DELETE FROM adventures
            WHERE id = ?
        ''', (adventure_id,))
        
        # Delete associated tags
        conn.execute('''
            DELETE FROM adventure_tags
            WHERE adventure_id = ?
        ''', (adventure_id,))
        
        # Notify the author
        conn.execute('''
            INSERT INTO notifications (user_id, content, type, related_id)
            VALUES (?, ?, ?, ?)
        ''', (adventure['author_id'], f"Your adventure '{adventure['name']}' has been rejected", 'rejection', None))
        
        # Delete the file
        try:
            os.remove(adventure['file_path'])
        except Exception as e:
            app.logger.error(f"Error deleting file: {e}")
        
        flash('Adventure rejected and deleted', 'success')
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('moderate'))

@app.route('/admin')
@admin_required
def admin_panel():
    return render_template('admin/index.html')

@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db_connection()
    
    users = conn.execute('''
        SELECT id, username, email, role, created_at, last_login
        FROM users
        ORDER BY created_at DESC
    ''').fetchall()
    
    conn.close()
    
    return render_template('admin/users.html', users=users)

@app.route('/admin/user/<int:user_id>', methods=['POST'])
@admin_required
def admin_update_user(user_id):
    role = request.form.get('role')
    
    if role not in ['user', 'moderator', 'admin']:
        flash('Invalid role', 'error')
        return redirect(url_for('admin_users'))
    
    conn = get_db_connection()
    
    # Check if user exists
    user = conn.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
    
    if not user:
        conn.close()
        flash('User not found', 'error')
        return redirect(url_for('admin_users'))
    
    # Update user role
    conn.execute('''
        UPDATE users
        SET role = ?
        WHERE id = ?
    ''', (role, user_id))
    
    conn.commit()
    conn.close()
    
    flash('User role updated successfully', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        theme = request.form.get('theme')
        
        if theme not in ['light', 'dark']:
            flash('Invalid theme', 'error')
            return redirect(url_for('admin_settings'))
        
        conn = get_db_connection()
        
        # Update theme setting
        conn.execute('''
            UPDATE site_settings
            SET setting_value = ?
            WHERE setting_name = 'theme'
        ''', (theme,))
        
        conn.commit()
        conn.close()
        
        flash('Settings updated successfully', 'success')
        return redirect(url_for('admin_settings'))
    
    return render_template('admin/settings.html')

@app.route('/admin/dashboard-data')
@admin_required
def admin_dashboard_data():
    conn = get_db_connection()
    
    # Get overall stats
    total_users = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
    total_adventures = conn.execute('SELECT COUNT(*) as count FROM adventures WHERE approved = 1').fetchone()['count']
    total_downloads = conn.execute('SELECT SUM(downloads) as count FROM adventures WHERE approved = 1').fetchone()['count'] or 0
    
    # Get today's stats
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    today_stats = {}
    for stat_name in ['page_views', 'logins', 'registrations', 'downloads', 'uploads']:
        stat = conn.execute(
            'SELECT SUM(stat_value) as value FROM statistics WHERE stat_name = ? AND date(date) = ?', 
            (stat_name, today)
        ).fetchone()
        today_stats[stat_name] = stat['value'] if stat and stat['value'] else 0
        
    # Get yesterday's stats for trend calculation
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    yesterday_stats = {}
    for stat_name in ['page_views', 'logins', 'registrations', 'downloads', 'uploads']:
        stat = conn.execute(
            'SELECT SUM(stat_value) as value FROM statistics WHERE stat_name = ? AND date(date) = ?', 
            (stat_name, yesterday)
        ).fetchone()
        yesterday_stats[stat_name] = stat['value'] if stat and stat['value'] else 0
        
    conn.close()
    
    # Calculate trends
    trends = {}
    for stat_name in ['page_views', 'logins', 'registrations', 'downloads', 'uploads']:
        today_val = today_stats[stat_name]
        yesterday_val = yesterday_stats[stat_name]
        
        if yesterday_val == 0:
            if today_val > 0:
                trends[stat_name] = 100 # Indicate significant increase if yesterday was 0
            else:
                trends[stat_name] = 0   # No change if both are 0
        else:
            change = ((today_val - yesterday_val) / yesterday_val) * 100
            trends[stat_name] = round(change)
            
    # Prepare response data
    data = {
        'total_users': total_users,
        'total_adventures': total_adventures,
        'total_downloads': total_downloads,
        'today_stats': {
            'page_views': today_stats['page_views'],
            'logins': today_stats['logins'],
            'registrations': today_stats['registrations'],
            'downloads': today_stats['downloads'],
            'uploads': today_stats['uploads']
        },
        'trends': {
            'page_views': trends['page_views'],
            'logins': trends['logins'],
            'registrations': trends['registrations'],
            'downloads': trends['downloads'],
            'uploads': trends['uploads']
        }
    }
    
    return jsonify(data)

@app.route('/admin/stats')
@admin_required
def admin_stats():
    conn = get_db_connection()
    
    # Get user statistics
    total_users = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
    user_roles = conn.execute('''
        SELECT role, COUNT(*) as count
        FROM users
        GROUP BY role
    ''').fetchall()
    
    # Get adventure statistics
    total_adventures = conn.execute('SELECT COUNT(*) as count FROM adventures WHERE approved = 1').fetchone()['count']
    pending_adventures = conn.execute('SELECT COUNT(*) as count FROM adventures WHERE approved = 0').fetchone()['count']
    total_downloads = conn.execute('SELECT SUM(downloads) as count FROM adventures').fetchone()['count'] or 0
    
    # Get tag statistics
    tag_usage = conn.execute('''
        SELECT t.name, COUNT(at.adventure_id) as count
        FROM tags t
        JOIN adventure_tags at ON t.id = at.tag_id
        JOIN adventures a ON at.adventure_id = a.id
        WHERE a.approved = 1
        GROUP BY t.id
        ORDER BY count DESC
        LIMIT 10
    ''').fetchall()
    
    # Get daily statistics for the past 30 days
    daily_stats = {}
    for stat_name in ['page_views', 'logins', 'registrations', 'downloads', 'uploads']:
        stats = conn.execute('''
            SELECT date(date) as day, SUM(stat_value) as value
            FROM statistics
            WHERE stat_name = ? AND date >= date('now', '-30 days')
            GROUP BY day
            ORDER BY day
        ''', (stat_name,)).fetchall()
        
        daily_stats[stat_name] = {
            'days': [row['day'] for row in stats],
            'values': [row['value'] for row in stats]
        }
    
    conn.close()
    
    return render_template('admin/stats.html', 
                          total_users=total_users,
                          user_roles=user_roles,
                          total_adventures=total_adventures,
                          pending_adventures=pending_adventures,
                          total_downloads=total_downloads,
                          tag_usage=tag_usage,
                          daily_stats=daily_stats)

@app.route('/notifications')
@login_required
def notifications():
    conn = get_db_connection()
    
    notifications = conn.execute('''
        SELECT id, content, type, related_id, is_read, created_at
        FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Mark all as read
    conn.execute('''
        UPDATE notifications
        SET is_read = 1
        WHERE user_id = ?
    ''', (session['user_id'],))
    
    conn.commit()
    conn.close()
    
    return render_template('notifications.html', notifications=notifications)

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('errors/500.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

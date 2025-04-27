from functools import wraps
from flask import session, flash, redirect, url_for, request, current_app
from .db import get_db
import sqlite3

def login_required(f):
    """Decorator to require login for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page', 'error')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def _check_role(required_roles):
    """Inner helper to check user role."""
    if 'user_id' not in session:
        flash('Please log in to access this page', 'error')
        return redirect(url_for('auth.login', next=request.url))

    conn = get_db()
    user = None
    try:
        user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error checking role: {e}")
        flash('An error occurred while verifying permissions.', 'error')
        return redirect(url_for('main.index')) # Redirect to a safe page

    # No conn.close() here

    if not user or user['role'] not in required_roles:
        flash('You do not have permission to access this page', 'error')
        return redirect(url_for('main.index'))
    return None # Indicates permission granted

def admin_required(f):
    """Decorator to require admin role for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        redirect_response = _check_role(['admin'])
        if redirect_response:
            return redirect_response
        return f(*args, **kwargs)
    return decorated_function

def moderator_required(f):
    """Decorator to require admin or moderator role for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        redirect_response = _check_role(['admin', 'moderator'])
        if redirect_response:
            return redirect_response
        return f(*args, **kwargs)
    return decorated_function

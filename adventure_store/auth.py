from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, current_app
)
from .db import get_db
from .utils import hash_password, log_statistic
import sqlite3
import datetime

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if not username or not email or not password:
            flash('All fields are required', 'error')
            return redirect(url_for('auth.register'))
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('auth.register'))

        conn = get_db()
        try:
            existing_user = conn.execute(
                'SELECT id FROM users WHERE username = ? OR email = ?', (username, email)
            ).fetchone()
            if existing_user:
                flash('Username or email already exists', 'error')
                return redirect(url_for('auth.register'))

            hashed_password = hash_password(password)
            cursor = conn.execute(
                'INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)',
                (username, email, hashed_password, 'user')
            )
            conn.commit()
            user_id = cursor.lastrowid

            log_statistic('registrations')
            session.clear() # Clear any previous session data
            session['user_id'] = user_id
            session['username'] = username
            session['role'] = 'user'

            flash('Registration successful! Welcome.', 'success')
            return redirect(url_for('main.index'))

        except sqlite3.Error as e:
            current_app.logger.error(f"Database error during registration: {e}")
            flash('An error occurred during registration. Please try again.', 'error')
            return redirect(url_for('auth.register'))

    return render_template('register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if not email or not password:
            flash('Email and password are required', 'error')
            return redirect(url_for('auth.login'))

        conn = get_db()
        try:
            hashed_password = hash_password(password)
            user = conn.execute(
                'SELECT id, username, role FROM users WHERE email = ? AND password = ?',
                (email, hashed_password)
            ).fetchone()

            if user:
                conn.execute(
                    'UPDATE users SET last_login = ? WHERE id = ?',
                    (datetime.datetime.now(), user['id'])
                )
                conn.commit()

                session.clear() # Clear any previous session data
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                log_statistic('logins')

                next_page = request.args.get('next')
                # Basic security check for open redirect
                if next_page and next_page.startswith('/'):
                     return redirect(next_page)
                return redirect(url_for('main.index'))
            else:
                flash('Invalid email or password', 'error')
                return redirect(url_for('auth.login'))

        except sqlite3.Error as e:
            current_app.logger.error(f"Database error during login: {e}")
            flash('An error occurred during login. Please try again.', 'error')
            return redirect(url_for('auth.login'))

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.index'))

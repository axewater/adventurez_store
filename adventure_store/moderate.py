from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, current_app
)
from .db import get_db
from .utils import parse_datetime
from .decorators import moderator_required
import os
import sqlite3

moderate_bp = Blueprint('moderate', __name__, url_prefix='/moderate')

@moderate_bp.route('/')
@moderator_required
def moderate_list():
    conn = get_db()
    processed_pending = []
    try:
        pending = conn.execute('''
            SELECT a.id, a.name, a.description, u.username as author, a.creation_date,
                   a.file_size, a.game_version, a.version_compat
            FROM adventures a JOIN users u ON a.author_id = u.id
            WHERE a.approved = 0 ORDER BY a.creation_date ASC
        ''').fetchall()

        for adventure in pending:
            adv_dict = dict(adventure)
            adv_dict['creation_date'] = parse_datetime(adv_dict['creation_date'])
            processed_pending.append(adv_dict)

        # Mark relevant notifications as read for the current moderator/admin
        if 'user_id' in session:
            conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND type = 'moderation' AND is_read = 0", (session['user_id'],))
            conn.commit()

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching pending adventures: {e}")
        flash("Could not load adventures for moderation due to a database error.", "error")

    return render_template('moderate.html', pending=processed_pending)


@moderate_bp.route('/<int:adventure_id>', methods=['POST'])
@moderator_required
def moderate_adventure(adventure_id):
    action = request.form.get('action')
    if action not in ['approve', 'reject']:
        flash('Invalid moderation action specified.', 'error')
        return redirect(url_for('moderate.moderate_list'))

    conn = get_db()
    try:
        adventure = conn.execute('SELECT id, name, author_id, file_path, game_version, version_compat FROM adventures WHERE id = ? AND approved = 0', (adventure_id,)).fetchone()
        if not adventure:
            flash('Adventure not found or already moderated.', 'error')
            return redirect(url_for('moderate.moderate_list'))

        if action == 'approve':
            conn.execute('UPDATE adventures SET approved = 1 WHERE id = ?', (adventure_id,))
            conn.execute(
                'INSERT INTO notifications (user_id, content, type, related_id) VALUES (?, ?, ?, ?)',
                (adventure['author_id'], f"Your adventure '{adventure['name']}' has been approved", 'approval', adventure_id)
            )
            flash('Adventure approved successfully.', 'success')
        else: # action == 'reject'
            # Important: Delete related data first (FK constraints)
            conn.execute('DELETE FROM adventure_tags WHERE adventure_id = ?', (adventure_id,))
            conn.execute('DELETE FROM ratings WHERE adventure_id = ?', (adventure_id,))
            conn.execute('DELETE FROM reviews WHERE adventure_id = ?', (adventure_id,))
            # Now delete the adventure itself
            conn.execute('DELETE FROM adventures WHERE id = ?', (adventure_id,))

            # Notify author
            conn.execute(
                'INSERT INTO notifications (user_id, content, type, related_id) VALUES (?, ?, ?, ?)',
                (adventure['author_id'], f"Your adventure '{adventure['name']}' has been rejected", 'rejection', None) # No related ID for rejection
            )

            # Delete the file
            try:
                if adventure['file_path'] and os.path.exists(adventure['file_path']):
                    os.remove(adventure['file_path'])
                    current_app.logger.info(f"Deleted rejected adventure file: {adventure['file_path']}")
            except OSError as e:
                current_app.logger.error(f"Error deleting rejected file {adventure['file_path']}: {e}")
                flash('Adventure rejected, but failed to delete the associated file.', 'warning') # Non-critical error

            flash('Adventure rejected and deleted.', 'success')

        conn.commit()

    except sqlite3.Error as e:
        conn.rollback() # Rollback changes on DB error
        current_app.logger.error(f"Database error moderating adventure (ID: {adventure_id}): {e}")
        flash('A database error occurred during moderation.', 'error')
    except Exception as e:
        conn.rollback() # Rollback changes on unexpected error
        current_app.logger.error(f"Unexpected error moderating adventure (ID: {adventure_id}): {e}")
        flash('An unexpected error occurred during moderation.', 'error')


    return redirect(url_for('moderate.moderate_list'))

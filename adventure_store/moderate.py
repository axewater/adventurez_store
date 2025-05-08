from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, current_app
)
from .db import get_db
from .utils import parse_datetime
from packaging.version import parse as parse_version
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
        pending_adventures_data = conn.execute('''
            SELECT a.id, a.name, a.description, u.username as author, a.author_id, a.creation_date,
                   a.file_size, a.game_version as pending_game_version, a.version_compat, a.thumbnail_filename
            FROM adventures a JOIN users u ON a.author_id = u.id
            WHERE a.approved = 0 ORDER BY a.creation_date ASC
        ''').fetchall()

        for adventure_row in pending_adventures_data:
            adv_dict = dict(adventure_row)
            adv_dict['creation_date'] = parse_datetime(adv_dict['creation_date'])
            adv_dict['game_version'] = adv_dict.pop('pending_game_version') # Rename for clarity in template

            # Check for existing active version by the same author with the same name
            existing_active_adventure = conn.execute('''
                SELECT game_version FROM adventures
                WHERE name = ? AND author_id = ? AND approved = 1
                ORDER BY id DESC LIMIT 1
            ''', (adv_dict['name'], adv_dict['author_id'])).fetchone()

            adv_dict['existing_active_game_version'] = None
            adv_dict['needs_version_warning'] = False

            if existing_active_adventure:
                adv_dict['existing_active_game_version'] = existing_active_adventure['game_version']
                try:
                    pending_v = parse_version(adv_dict['game_version'])
                    active_v = parse_version(existing_active_adventure['game_version'])
                    if pending_v <= active_v:
                        adv_dict['needs_version_warning'] = True
                except Exception as e:
                    current_app.logger.warning(
                        f"Could not parse game versions for warning (pending: {adv_dict['game_version']}, "
                        f"active: {existing_active_adventure['game_version']}) for adventure ID {adv_dict['id']}: {e}"
                    )

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
        conn.execute('BEGIN TRANSACTION') # Explicitly start a transaction
        newly_approved_adventure = conn.execute(
            'SELECT id, name, author_id, file_path, game_version, version_compat, thumbnail_filename FROM adventures WHERE id = ? AND approved = 0', 
            (adventure_id,)
        ).fetchone()

        if not newly_approved_adventure:
            flash('Adventure not found or already moderated.', 'error')
            conn.rollback()
            return redirect(url_for('moderate.moderate_list'))

        if action == 'approve':
            # 1. Set the new adventure to approved = 1
            conn.execute('UPDATE adventures SET approved = 1 WHERE id = ?', (newly_approved_adventure['id'],))

            # 2. Supersede older versions by the same author with the same name
            conn.execute('''
                UPDATE adventures SET approved = 2 
                WHERE name = ? AND author_id = ? AND id != ? AND approved = 1
            ''', (newly_approved_adventure['name'], newly_approved_adventure['author_id'], newly_approved_adventure['id']))
            
            conn.execute(
                'INSERT INTO notifications (user_id, content, type, related_id) VALUES (?, ?, ?, ?)',
                (newly_approved_adventure['author_id'], f"Your adventure '{newly_approved_adventure['name']}' has been approved", 'approval', adventure_id)
            )
            flash('Adventure approved successfully.', 'success')
        else: # action == 'reject'
            # Important: Delete related data first (FK constraints)
            conn.execute('DELETE FROM adventure_tags WHERE adventure_id = ?', (adventure_id,))
            conn.execute('DELETE FROM ratings WHERE adventure_id = ?', (adventure_id,))
            conn.execute('DELETE FROM reviews WHERE adventure_id = ?', (adventure_id,))
            # Now delete the adventure itself
            conn.execute('DELETE FROM adventures WHERE id = ?', (adventure_id,))

            # Notify author of rejection
            conn.execute(
                'INSERT INTO notifications (user_id, content, type, related_id) VALUES (?, ?, ?, ?)',
                (newly_approved_adventure['author_id'], f"Your adventure '{newly_approved_adventure['name']}' has been rejected", 'rejection', None)
            )

            # Delete the file
            try:
                if newly_approved_adventure['file_path'] and os.path.exists(newly_approved_adventure['file_path']):
                    # Delete adventure zip
                    os.remove(newly_approved_adventure['file_path'])
                    current_app.logger.info(f"Deleted rejected adventure file: {newly_approved_adventure['file_path']}")
                    # Delete thumbnail
                    if newly_approved_adventure['thumbnail_filename']:
                        thumb_path = os.path.join(current_app.config['THUMBNAIL_FOLDER'], newly_approved_adventure['thumbnail_filename'])
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                            current_app.logger.info(f"Deleted thumbnail for rejected adventure: {thumb_path}")
            except OSError as e:
                current_app.logger.error(f"Error deleting rejected file {newly_approved_adventure['file_path']}: {e}")
                flash('Adventure rejected, but failed to delete the associated file(s).', 'warning') # Non-critical error

            flash('Adventure rejected and deleted.', 'success')

        conn.commit()

    except sqlite3.Error as e:
        conn.rollback() # Rollback changes on DB error
        current_app.logger.error(f"Database error moderating adventure (ID: {adventure_id}): {e}", exc_info=True)
        flash('A database error occurred during moderation.', 'error')
    except Exception as e:
        conn.rollback() # Rollback changes on unexpected error
        current_app.logger.error(f"Unexpected error moderating adventure (ID: {adventure_id}): {e}", exc_info=True)
        flash('An unexpected error occurred during moderation.', 'error')


    return redirect(url_for('moderate.moderate_list'))

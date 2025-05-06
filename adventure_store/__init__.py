import os
import secrets
from flask import Flask, render_template, g

def create_app(test_config=None):
    """Create and configure an instance of the Flask application."""
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'static') # Point to root static folder
    )

    # --- Configuration ---
    # Default configuration
    app.config.from_mapping(
        SECRET_KEY=secrets.token_hex(16), # Generate a new key each time if not set
        DATABASE=os.path.join(app.instance_path, 'adventure_store.db'),
        UPLOAD_FOLDER=os.path.join(app.root_path, '..', 'static', 'uploads'), # Relative to app package
        MAX_CONTENT_LENGTH=500 * 1024 * 1024,  # 500MB max upload size (Increased significantly)
    )

    if test_config is None:
        # Load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
        # Load config from environment variables (optional, good practice)
        app.config.from_envvar('ADVENTURE_STORE_SETTINGS', silent=True)
    else:
        # Load the test config if passed in
        app.config.update(test_config)

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Ensure upload directory exists
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except OSError:
        pass

    # --- Database Initialization ---
    from . import db
    db.init_app(app)

    # --- Blueprints ---
    from . import main, auth, user, admin, moderate, api
    app.register_blueprint(main.main_bp)
    app.register_blueprint(auth.auth_bp)
    app.register_blueprint(user.user_bp)
    app.register_blueprint(admin.admin_bp)
    app.register_blueprint(moderate.moderate_bp)
    app.register_blueprint(api.api_bp)

    # --- Context Processors ---
    from .utils import get_site_settings, get_pending_moderation_count

    @app.context_processor
    def inject_settings():
        """Inject site settings and pending moderation count into templates."""
        settings = get_site_settings()
        pending_count = get_pending_moderation_count()
        # Provide default theme if not in DB
        if 'theme' not in settings:
            settings['theme'] = 'light' # Default theme
        return dict(settings=settings, pending_moderation_count=pending_count)

    # --- Error Handlers ---
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        # Log the error details
        app.logger.error(f"Server Error: {e}", exc_info=True)
        return render_template('errors/500.html'), 500

    return app

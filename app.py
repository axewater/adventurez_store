import os
from adventure_store import create_app

app = create_app()


if __name__ == '__main__':
    # Use environment variables for host/port/debug if available, otherwise defaults
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_RUN_PORT', 15000))
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 't']
    app.run(host=host, port=port, debug=debug)



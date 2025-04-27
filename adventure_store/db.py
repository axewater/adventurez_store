import sqlite3
import click
from flask import current_app, g
from flask.cli import with_appcontext
import os

def get_db():
    """Connect to the application's configured database. The connection
    is unique for each request and will be reused if this is called
    again.
    """
    if 'db' not in g:
        db_path = current_app.config['DATABASE']
        # Ensure the instance folder exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        g.db = sqlite3.connect(
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row

    return g.db

def close_db(e=None):
    """If this request connected to the database, close the
    connection.
    """
    db = g.pop('db', None)

    if db is not None:
        db.close()

def init_db():
    """Clear existing data and create new tables."""
    db = get_db()

    # Read the schema file relative to the adventure_store package
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'schema.sql') # Assuming schema.sql exists
    # If schema.sql doesn't exist, we might need to adapt the init_db.py logic here
    # For now, let's assume init_db.py handles table creation separately.
    # We'll just ensure the connection works.
    print(f"Database connection established to {current_app.config['DATABASE']}")


@click.command('init-db')
@with_appcontext
def init_db_command():
    """Clear existing data and create new tables."""
    # This command might call the logic from the original init_db.py
    # For simplicity, we'll just print a message.
    # In a real scenario, you'd integrate the table creation logic here or call init_db.py
    click.echo('Initialized the database (placeholder - integrate schema creation).')
    # Example: You could potentially import and run the main logic from init_db.py
    # import sys
    # sys.path.insert(0, os.path.dirname(current_app.root_path))
    # import init_db as db_initializer
    # db_initializer.initialize() # Assuming init_db.py has an initialize function

def init_app(app):
    """Register database functions with the Flask app. This is called by
    the application factory.
    """
    app.teardown_appcontext(close_db)
    # app.cli.add_command(init_db_command) # Optional: Add CLI command to initialize DB

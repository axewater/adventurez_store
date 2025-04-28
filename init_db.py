import sqlite3
import os
import hashlib
import datetime

# Function to hash passwords
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Create database directory if it doesn't exist
os.makedirs('instance', exist_ok=True)

# Connect to database
conn = sqlite3.connect('instance/adventure_store.db')
cursor = conn.cursor()

# Create users table
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
)
''')

# Create adventures table
cursor.execute('''
CREATE TABLE IF NOT EXISTS adventures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    creation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    version_compat TEXT NOT NULL,
    approved INTEGER DEFAULT 0,
    downloads INTEGER DEFAULT 0,
    FOREIGN KEY (author_id) REFERENCES users (id)
)
''')

# Create tags table
cursor.execute('''
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
)
''')

# Create adventure_tags table (many-to-many relationship)
cursor.execute('''
CREATE TABLE IF NOT EXISTS adventure_tags (
    adventure_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (adventure_id, tag_id),
    FOREIGN KEY (adventure_id) REFERENCES adventures (id),
    FOREIGN KEY (tag_id) REFERENCES tags (id)
)
''')

# Create ratings table
cursor.execute('''
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adventure_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (adventure_id) REFERENCES adventures (id),
    FOREIGN KEY (user_id) REFERENCES users (id),
    UNIQUE(adventure_id, user_id)
)
''')

# Create reviews table
cursor.execute('''
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adventure_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (adventure_id) REFERENCES adventures (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
)
''')

# Create notifications table
cursor.execute('''
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    type TEXT NOT NULL,
    related_id INTEGER,
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
)
''')

# Create site_settings table
cursor.execute('''
CREATE TABLE IF NOT EXISTS site_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_name TEXT UNIQUE NOT NULL,
    setting_value TEXT NOT NULL
)
''')

# Create statistics table
cursor.execute('''
CREATE TABLE IF NOT EXISTS statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stat_name TEXT NOT NULL,
    stat_value INTEGER NOT NULL,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# Create api_keys table
cursor.execute('''
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
)
''')

# Create api_logs table
cursor.execute('''
CREATE TABLE IF NOT EXISTS api_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_name TEXT,
    ip_address TEXT,
    endpoint TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# Insert default admin user
admin_password = hash_password("Roll14me!")
cursor.execute('''
INSERT OR IGNORE INTO users (username, email, password, role)
VALUES (?, ?, ?, ?)
''', ('admin', 'admin@textadventurebuilder.com', admin_password, 'admin'))

# Insert default site settings
cursor.execute('''
INSERT OR IGNORE INTO site_settings (setting_name, setting_value)
VALUES (?, ?)
''', ('theme', 'light'))

# Insert some default tags
default_tags = ['Fantasy', 'Sci-Fi', 'Horror', 'Mystery', 'Comedy', 'Adventure', 'Historical', 'Educational']
for tag in default_tags:
    cursor.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag,))

# Commit changes and close connection
conn.commit()
conn.close()

print("Database initialized successfully with admin account and default settings.")

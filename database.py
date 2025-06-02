import sqlite3
import os
import time
import pandas as pd
from datetime import datetime

# Database setup
DB_PATH = os.environ.get('HM_DB_PATH', 'transactions.db')

def get_db_connection(timeout=30):
    """Get a database connection with retry logic."""
    max_attempts = 5
    attempt = 0
    while attempt < max_attempts:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=timeout)
            return conn
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                attempt += 1
                if attempt == max_attempts:
                    raise e
                time.sleep(0.1)  # Wait before retrying
            else:
                raise e

def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Create tags table if it doesn't exist
        c.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                color TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create uploaded_files table if it doesn't exist
        c.execute('''
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                sha_256 TEXT NOT NULL UNIQUE,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                transaction_count INTEGER NOT NULL
            )
        ''')

        # Create transactions table if it doesn't exist
        c.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                file_sha_256 TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_sha_256) REFERENCES uploaded_files(sha_256)
            )
        ''')

        # Create transaction_tags junction table
        c.execute('''
            CREATE TABLE IF NOT EXISTS transaction_tags (
                transaction_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (transaction_id, tag_id),
                FOREIGN KEY (transaction_id) REFERENCES transactions(id),
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            )
        ''')

        # Insert default tags if they don't exist
        default_tags = [
            ('Groceries', 'Food, household items, and daily essentials', '#FF9999'),
            ('Dining', 'Restaurants, cafes, and takeout food', '#99FF99'),
            ('Transportation', 'Gas, public transit, car maintenance, and rideshares', '#9999FF'),
            ('Shopping', 'Retail purchases, clothing, and personal items', '#FFFF99'),
            ('Entertainment', 'Movies, events, hobbies, and leisure activities', '#FF99FF'),
            ('Utilities', 'Electricity, water, gas, internet, and phone bills', '#99FFFF'),
            ('Housing', 'Rent, mortgage, property taxes, and home maintenance', '#FFB366'),
            ('Healthcare', 'Medical expenses, prescriptions, and insurance', '#FF6666'),
            ('Education', 'Tuition, books, courses, and educational materials', '#66B366'),
            ('Travel', 'Vacations, business trips, and travel expenses', '#B366B3'),
            ('Gifts', 'Gifts, donations, and charitable contributions', '#66B3B3'),
            ('Personal Care', 'Haircuts, beauty products, and wellness services', '#B3B366'),
            ('Investments', 'Savings, investments, and retirement contributions', '#4D4D4D'),
            ('Income', 'Salary, bonuses, and other income sources', '#4CAF50'),
            ('Subscriptions', 'Streaming services, software, and memberships', '#9C27B0'),
            ('Insurance', 'Health, auto, home, and other insurance premiums', '#2196F3')
        ]
        c.executemany('''
            INSERT OR IGNORE INTO tags (name, description, color)
            VALUES (?, ?, ?)
        ''', default_tags)

        conn.commit()
    finally:
        if conn:
            conn.close()

def reset_database():
    """Reset the database by dropping all tables and recreating them.
    WARNING: This will delete all existing data!
    """
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Drop existing tables
        c.execute('DROP TABLE IF EXISTS transaction_tags')
        c.execute('DROP TABLE IF EXISTS transactions')
        c.execute('DROP TABLE IF EXISTS uploaded_files')
        c.execute('DROP TABLE IF EXISTS tags')

        conn.commit()
    finally:
        if conn:
            conn.close()

    # Reinitialize the database
    init_db()

def get_tags():
    """Get all tags from the database."""
    conn = get_db_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM tags ORDER BY name", conn)
        return df
    finally:
        conn.close()

def add_tag(name, description, color):
    """Add a new tag to the database."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO tags (name, description, color)
            VALUES (?, ?, ?)
        ''', (name, description, color))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_tag(tag_id, name, description, color):
    """Update an existing tag."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''
            UPDATE tags
            SET name = ?, description = ?, color = ?
            WHERE id = ?
        ''', (name, description, color, tag_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_tag(tag_id):
    """Delete a tag."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def save_file_info(filename, sha_256, transaction_count):
    """Save file information to the database."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO uploaded_files (filename, sha_256, transaction_count)
            VALUES (?, ?, ?)
        ''', (filename, sha_256, transaction_count))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # File hash already exists
        return False
    finally:
        conn.close()

def get_uploaded_files():
    """Get list of uploaded files from the database."""
    conn = get_db_connection()
    try:
        df = pd.read_sql_query("""
            SELECT filename, upload_date, transaction_count, sha_256
            FROM uploaded_files
            ORDER BY upload_date DESC
        """, conn)
        return df
    finally:
        conn.close()

def save_transactions(df, sha_256):
    """Save transactions to the database."""
    conn = get_db_connection()
    try:
        c = conn.cursor()

        # Get tag IDs
        tags = {row[1]: row[0] for row in c.execute("SELECT id, name FROM tags")}

        # Add file_sha_256 column
        df['file_sha_256'] = sha_256

        # Save transactions
        for _, row in df.iterrows():
            # Insert transaction
            c.execute('''
                INSERT INTO transactions (date, description, amount, file_sha_256)
                VALUES (?, ?, ?, ?)
            ''', (row['Date'], row['Description'], row['Amount'], sha_256))

            transaction_id = c.lastrowid

            # Handle tags
            if 'Tags' in row and pd.notna(row['Tags']):
                # Split tags by comma and strip whitespace
                tag_names = [tag.strip() for tag in str(row['Tags']).split(',')]
                for tag_name in tag_names:
                    if tag_name in tags:
                        # Add tag to transaction
                        c.execute('''
                            INSERT INTO transaction_tags (transaction_id, tag_id)
                            VALUES (?, ?)
                        ''', (transaction_id, tags[tag_name]))

        conn.commit()
    finally:
        conn.close()

def load_transactions():
    """Load all transactions from the database."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()

    conn = get_db_connection()
    try:
        # Get transactions with their tags
        df = pd.read_sql_query("""
            SELECT t.id, t.date, t.description, t.amount,
                   GROUP_CONCAT(tg.name) as tags,
                   t.file_sha_256, f.filename
            FROM transactions t
            LEFT JOIN transaction_tags tt ON t.id = tt.transaction_id
            LEFT JOIN tags tg ON tt.tag_id = tg.id
            JOIN uploaded_files f ON t.file_sha_256 = f.sha_256
            GROUP BY t.id
            ORDER BY t.date DESC
        """, conn)

        if not df.empty:
            df['Date'] = pd.to_datetime(df['date'])
            df = df.rename(columns={
                'date': 'Date',
                'description': 'Description',
                'amount': 'Amount',
                'tags': 'Tags',
                'file_sha_256': 'File SHA-256',
                'filename': 'Source File'
            })
        return df
    finally:
        conn.close()

def update_transaction_tags(transaction_id, tag_ids):
    """Update the tags of a transaction."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        # Remove existing tags
        c.execute('DELETE FROM transaction_tags WHERE transaction_id = ?', (transaction_id,))

        # Add new tags
        for tag_id in tag_ids:
            c.execute('''
                INSERT INTO transaction_tags (transaction_id, tag_id)
                VALUES (?, ?)
            ''', (transaction_id, tag_id))

        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating transaction tags: {e}")
        return False
    finally:
        conn.close()

def get_tag_options():
    """Get tags for dropdown options."""
    conn = get_db_connection()
    try:
        df = pd.read_sql_query("SELECT id, name, color FROM tags ORDER BY name", conn)
        return [{'label': row['name'], 'value': row['id'], 'style': {'color': row['color']}} for _, row in df.iterrows()]
    finally:
        conn.close()
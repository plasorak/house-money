import sqlite3
import os
import time
import json
import polars as pl
from datetime import datetime, timedelta
import threading
from typing import Dict, Any
import logging

# Database setup
DB_PATH = os.environ.get('HM_DB_PATH', 'transactions.db')

# Thread-local storage for database connections
thread_local = threading.local()

# Cache configuration
CACHE_TTL = 300  # 5 minutes in seconds
_cache_lock = threading.Lock()
_cache_timestamps: Dict[str, float] = {}
_cache: Dict[str, Any] = {}

def _invalidate_cache(cache_name: str = None):
    """Invalidate specific cache or all caches if no name provided."""
    with _cache_lock:
        if cache_name:
            _cache_timestamps.pop(cache_name, None)
            _cache.pop(cache_name, None)
            # If invalidating transactions cache, also invalidate all sorted transaction caches
            if cache_name == 'transactions':
                # Remove all cache keys that start with 'transactions_sort_'
                keys_to_remove = [k for k in _cache_timestamps.keys() if k.startswith('transactions_sort_')]
                for k in keys_to_remove:
                    _cache_timestamps.pop(k)
                    _cache.pop(k)
        else:
            _cache_timestamps.clear()
            _cache.clear()

def _is_cache_valid(cache_name: str) -> bool:
    """Check if cache is still valid based on TTL."""
    with _cache_lock:
        timestamp = _cache_timestamps.get(cache_name)
        if timestamp is None:
            return False
        return (time.time() - timestamp) < CACHE_TTL

def _update_cache(cache_name: str, data: Any):
    """Update the cache with new data."""
    with _cache_lock:
        _cache[cache_name] = data
        _cache_timestamps[cache_name] = time.time()

def _get_cache(cache_name: str):
    """Get the cache for a given name."""
    with _cache_lock:
        return _cache.get(cache_name, None)

def get_db_connection(timeout=30):
    """Get a database connection for the current thread."""
    if not hasattr(thread_local, 'connection'):
        thread_local.connection = sqlite3.connect(DB_PATH, timeout=timeout)
        thread_local.connection.row_factory = sqlite3.Row
    return thread_local.connection

def close_thread_connection():
    """Close the database connection for the current thread."""
    if hasattr(thread_local, 'connection'):
        thread_local.connection.close()
        del thread_local.connection

def close_all_connections():
    """Close all thread-local connections."""
    # This is a no-op since connections are managed per-thread
    pass

def init_db(table='all'):
    """Initialize the database and create specified table(s) if they don't exist."""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        tables_to_create = []
        if table == 'all' or table == 'tags':
            tables_to_create.append(('''
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    color TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''', 'tags'))

        if table == 'all' or table == 'uploaded_files':
            tables_to_create.append(('''
                CREATE TABLE IF NOT EXISTS uploaded_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    sha_256 TEXT NOT NULL UNIQUE,
                    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    transaction_count INTEGER NOT NULL
                )
            ''', 'uploaded_files'))

        if table == 'all' or table == 'transactions':
            tables_to_create.append(('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TIMESTAMP NOT NULL,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL,
                    file_sha_256 TEXT NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (file_sha_256) REFERENCES uploaded_files(sha_256)
                )
            ''', 'transactions'))

        if table == 'all' or table == 'transaction_tags':
            tables_to_create.append(('''
                CREATE TABLE IF NOT EXISTS transaction_tags (
                    transaction_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (transaction_id, tag_id),
                    FOREIGN KEY (transaction_id) REFERENCES transactions(id),
                    FOREIGN KEY (tag_id) REFERENCES tags(id)
                )
            ''', 'transaction_tags'))

        for create_sql, table_name in tables_to_create:
            c.execute(create_sql)
            print(f"Created table: {table_name}")

        # Insert default tags if we're creating the tags table
        if table == 'all' or table == 'tags':
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
            print("Inserted default tags")

        conn.commit()
    finally:
        if conn:
            conn.close()

def reset_database(table='all'):
    """Reset specified table(s) by dropping and recreating them.
    WARNING: This will delete all data in the specified table(s)!
    """
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Drop specified tables
        if table == 'all':
            tables = ['transaction_tags', 'transactions', 'uploaded_files', 'tags']
        else:
            tables = [table]

        for t in tables:
            c.execute(f'DROP TABLE IF EXISTS {t}')
            print(f"Dropped table: {t}")

        conn.commit()
    finally:
        if conn:
            conn.close()

    # Reinitialize the specified table(s)
    init_db(table)

def get_tags():
    """Get all tags from the database."""
    if not _is_cache_valid('tags'):
        conn = get_db_connection()
        try:
            df = pl.read_database("SELECT * FROM tags ORDER BY name", conn)
            _update_cache('tags', df)
            return df
        finally:
            close_thread_connection()
    cached_data = _get_cache('tags')
    return cached_data if cached_data is not None else pl.DataFrame()

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
        _invalidate_cache('tags')
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        close_thread_connection()

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
        _invalidate_cache('tags')  # Only need to invalidate tags cache
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        close_thread_connection()

def delete_tag(tag_id):
    """Delete a tag."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        conn.commit()
        _invalidate_cache('tags')  # Only need to invalidate tags cache
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        close_thread_connection()

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
        _invalidate_cache('uploaded_files')
        return True
    except sqlite3.IntegrityError:
        # File hash already exists
        return False
    finally:
        close_thread_connection()

def get_uploaded_files():
    """Get list of uploaded files from the database."""
    if not _is_cache_valid('uploaded_files'):
        print("Getting uploaded files from database...")
        conn = get_db_connection()
        try:
            # First check if the table exists
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='uploaded_files'")
            if not c.fetchone():
                print("uploaded_files table does not exist")
                return pl.DataFrame()

            # Get the files
            df = pl.read_database("""
                SELECT filename, upload_date, transaction_count, sha_256
                FROM uploaded_files
                ORDER BY upload_date DESC
            """, conn)
            print(f"Found {len(df)} files in database")
            _update_cache('uploaded_files', df)
            return df
        finally:
            close_thread_connection()
    cached_data = _get_cache('uploaded_files')
    return cached_data if cached_data is not None else pl.DataFrame()

def save_transactions(df, sha_256):
    """Save transactions to the database."""
    conn = get_db_connection()
    try:
        c = conn.cursor()

        # Get tag IDs
        tags = {row[1]: row[0] for row in c.execute("SELECT id, name FROM tags")}

        # Create a copy of the DataFrame to avoid modifying the original
        df_copy = df.copy()
        df_copy['file_sha_256'] = sha_256

        # Convert date to ISO format timestamp
        df_copy['Date'] = df_copy['Date'].dt.strftime('%Y-%m-%d %H:%M:%S')

        # Save transactions
        for _, row in df_copy.iterrows():
            # Insert transaction
            c.execute('''
                INSERT INTO transactions (date, description, amount, file_sha_256, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (row['Date'], row['Description'], row['Amount'], sha_256, row.get('Notes', '')))

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
        _invalidate_cache('transactions')
    finally:
        close_thread_connection()

def load_transactions():
    """Load all transactions from the database."""
    if not _is_cache_valid('transactions'):
        if not os.path.exists(DB_PATH):
            return pl.DataFrame()

        conn = get_db_connection()
        try:
            # Get transactions with their tags
            df = pl.read_database("""
                SELECT t.id, t.date, t.description, t.amount, t.notes,
                       GROUP_CONCAT(tg.name) as tags,
                       t.file_sha_256, f.filename
                FROM transactions t
                LEFT JOIN transaction_tags tt ON t.id = tt.transaction_id
                LEFT JOIN tags tg ON tt.tag_id = tg.id
                JOIN uploaded_files f ON t.file_sha_256 = f.sha_256
                GROUP BY t.id
                ORDER BY t.date DESC
            """, conn)

            if not df.is_empty():
                df = df.with_columns([
                    pl.col('date').str.to_datetime(format='%Y-%m-%d %H:%M:%S').alias('Date'),
                    pl.col('description').alias('Description'),
                    pl.col('amount').alias('Amount'),
                    pl.col('notes').alias('Notes'),
                    pl.col('tags').alias('Tags'),
                    pl.col('file_sha_256').alias('File SHA-256'),
                    pl.col('filename').alias('Source File')
                ])
            _update_cache('transactions', df)
            return df
        finally:
            close_thread_connection()
    cached_data = _get_cache('transactions')
    return cached_data if cached_data is not None else pl.DataFrame()

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
        _invalidate_cache('transactions')
        return True
    except Exception as e:
        print(f"Error updating transaction tags: {e}")
        return False
    finally:
        close_thread_connection()

def update_transaction_note(transaction_id, note):
    """Update the note of a transaction."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''
            UPDATE transactions
            SET notes = ?
            WHERE id = ?
        ''', (note, transaction_id))
        conn.commit()
        _invalidate_cache('transactions')
        return True
    except Exception as e:
        print(f"Error updating transaction note: {e}")
        return False
    finally:
        close_thread_connection()

def get_tag_name_to_id_mapping():
    """Get a mapping of tag names to their IDs."""
    if not _is_cache_valid('tags'):
        conn = get_db_connection()
        try:
            mapping = {row[1]: row[0] for row in conn.execute("SELECT id, name FROM tags")}
            _update_cache('tag_mapping', mapping)
            return mapping
        finally:
            close_thread_connection()
    cached_data = _get_cache('tag_mapping')
    return cached_data if cached_data is not None else {}

def create_manual_transaction(date, description, amount, notes=None, tags=None):
    """Create a new transaction manually.

    Args:
        date (datetime): Transaction date and time
        description (str): Transaction description
        amount (float): Transaction amount
        notes (str, optional): Transaction notes
        tags (list, optional): List of tag IDs to associate with the transaction

    Returns:
        int: The ID of the newly created transaction, or None if creation failed
    """
    conn = get_db_connection()
    try:
        c = conn.cursor()
        # Insert transaction
        c.execute('''
            INSERT INTO transactions (date, description, amount, notes, file_sha_256)
            VALUES (?, ?, ?, ?, ?)
        ''', (date, description, amount, notes, 'manual_entry'))

        transaction_id = c.lastrowid

        # Add tags if any
        if tags:
            for tag_id in tags:
                c.execute('''
                    INSERT INTO transaction_tags (transaction_id, tag_id)
                    VALUES (?, ?)
                ''', (transaction_id, tag_id))

        conn.commit()
        _invalidate_cache('transactions')
        return transaction_id
    except Exception as e:
        print(f"Error creating manual transaction: {e}")
        return None
    finally:
        close_thread_connection()

def load_transactions_with_sort(sort_column='date', ascending=True, search_text=None, search_text_on=None):
    """Load transactions from the database with sorting and optional search applied."""
    cache_key = f"transactions_sort_{sort_column}_{ascending}_{search_text}_{search_text_on}"
    if not _is_cache_valid(cache_key):
        conn = get_db_connection()
        try:
            # Validate sort column to prevent SQL injection
            valid_columns = ['date', 'description', 'amount']
            sort_column = sort_column.lower()
            if sort_column not in valid_columns:
                sort_column = 'date'

            # Map column names to their table-qualified versions
            column_map = {
                'date': 't.date',
                'description': 't.description',
                'amount': 't.amount'
            }

            # Build the query with sorting and optional search
            query = f"""
            SELECT t.id, t.date, t.description, t.amount, t.notes,
                   GROUP_CONCAT(tg.name) as tags,
                   t.file_sha_256, f.filename as source_file
            FROM transactions t
            LEFT JOIN transaction_tags tt ON t.id = tt.transaction_id
            LEFT JOIN tags tg ON tt.tag_id = tg.id
            LEFT JOIN uploaded_files f ON t.file_sha_256 = f.sha_256
            WHERE 1=1
            """

            # Add search condition if search_text is provided
            if search_text:
                query += f" AND {column_map[search_text_on]} LIKE '%{search_text}%'"

            query += f"""
            GROUP BY t.id
            ORDER BY {column_map[sort_column]} {'ASC' if ascending else 'DESC'}
            """

            df = pl.read_database(query, conn)

            # Convert date strings to datetime and rename columns
            df = df.with_columns([
                pl.col('date').str.to_datetime(format='%Y-%m-%d %H:%M:%S', strict=False)
                .fill_null(pl.col('date').str.to_datetime(format='%Y-%m-%d', strict=False))
                .alias('Date'),
                pl.col('description').alias('Description'),
                pl.col('amount').alias('Amount'),
                pl.col('notes').alias('Notes'),
                pl.col('tags').alias('Tags'),
                pl.col('file_sha_256').alias('File SHA-256'),
                pl.col('source_file').alias('Source File')
            ])
            _update_cache(cache_key, df)
            return df
        finally:
            close_thread_connection()
    cached_data = _get_cache(cache_key)
    return cached_data if cached_data is not None else pl.DataFrame()

def delete_transactions(transaction_ids):
    """Delete multiple transactions by their IDs.

    Args:
        transaction_ids (list): List of transaction IDs to delete

    Returns:
        bool: True if deletion was successful, False otherwise
    """
    conn = get_db_connection()
    try:
        c = conn.cursor()
        # First delete associated tags
        c.executemany('DELETE FROM transaction_tags WHERE transaction_id = ?',
                     [(id,) for id in transaction_ids])
        # Then delete the transactions
        c.executemany('DELETE FROM transactions WHERE id = ?',
                     [(id,) for id in transaction_ids])
        conn.commit()
        _invalidate_cache('transactions')
        return True
    except Exception as e:
        print(f"Error deleting transactions: {e}")
        return False
    finally:
        close_thread_connection()
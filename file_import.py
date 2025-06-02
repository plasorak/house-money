import base64
import hashlib
import io
import pandas as pd
import sqlite3
from database import DB_PATH, save_file_info, save_transactions

def calculate_file_hash(contents):
    """Calculate SHA-256 hash of file contents."""
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    return hashlib.sha256(decoded).hexdigest()

def parse_contents(contents, filename, format_type='standard', custom_columns=None):
    print(f"Parsing contents for {filename} with format {format_type}")
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)

    try:
        df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        print(f"Successfully read CSV with columns: {df.columns.tolist()}")

        # Define column mappings for different formats
        format_mappings = {
            'standard': {
                'date': 'Date',
                'description': 'Description',
                'amount': 'Amount'
            },
            'bank': {
                'date': 'Transaction Date',
                'description': 'Details',
                'amount': 'Transaction Amount'
            },
            'custom': custom_columns or {
                'date': 'Date',
                'description': 'Description',
                'amount': 'Amount'
            }
        }

        # Get the appropriate column mapping
        mapping = format_mappings[format_type]
        print(f"Using column mapping: {mapping}")

        # Check if required columns exist in the CSV
        if not all(col in df.columns for col in mapping.values()):
            missing_cols = [col for col in mapping.values() if col not in df.columns]
            print(f"Missing required columns: {missing_cols}")
            return None, f"CSV is missing required columns: {', '.join(missing_cols)}"

        # Rename columns to standard format
        df = df.rename(columns={
            mapping['date']: 'Date',
            mapping['description']: 'Description',
            mapping['amount']: 'Amount'
        })
        print("Columns renamed successfully")

        # Convert date column to datetime
        df['Date'] = pd.to_datetime(df['Date'])
        print("Date column converted to datetime")

        # Add Tags column if it doesn't exist
        if 'Tags' not in df.columns:
            df['Tags'] = ''
            print("Added empty Tags column")

        # Ensure Amount is numeric
        df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
        print("Amount column converted to numeric")

        # Remove any rows with invalid amounts
        original_len = len(df)
        df = df.dropna(subset=['Amount'])
        if len(df) < original_len:
            print(f"Removed {original_len - len(df)} rows with invalid amounts")

        print(f"Successfully parsed {len(df)} transactions")
        return df, None
    except Exception as e:
        print(f"Error in parse_contents: {str(e)}")
        return None, f"Error processing {filename}: {str(e)}"

def process_uploaded_files(contents_list, filename_list, format_type, custom_date_col=None, custom_desc_col=None, custom_amount_col=None):
    """Process a list of uploaded files and return the combined data."""
    print(f"Processing {len(contents_list) if contents_list else 0} files")
    if not contents_list:
        return None, [], []

    custom_columns = None
    if format_type == 'custom':
        custom_columns = {
            'date': custom_date_col,
            'description': custom_desc_col,
            'amount': custom_amount_col
        }

    dfs = []
    status_messages = []

    for contents, filename in zip(contents_list, filename_list):
        print(f"Processing file: {filename}")
        # Calculate file hash
        sha_256 = calculate_file_hash(contents)
        print(f"File hash: {sha_256}")

        # Check if file was already uploaded
        if not save_file_info(filename, sha_256, 0):  # We'll update the count after processing
            print(f"File {filename} was already uploaded")
            status_messages.append(f"⚠️ {filename} was already uploaded and will be skipped")
            continue

        df, error = parse_contents(contents, filename, format_type, custom_columns)
        if df is not None:
            print(f"Successfully parsed {len(df)} transactions from {filename}")
            dfs.append((df, sha_256))  # Store both df and sha_256
            # Update transaction count
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('''
                UPDATE uploaded_files
                SET transaction_count = ?
                WHERE sha_256 = ?
            ''', (len(df), sha_256))
            conn.commit()
            conn.close()
            status_messages.append(f"✅ {filename} uploaded successfully ({len(df)} transactions)")
        else:
            print(f"Error parsing {filename}: {error}")
            status_messages.append(f"❌ {filename}: {error}")

    if not dfs:
        print("No dataframes were successfully processed")
        return None, [], status_messages

    # Save each dataframe with its corresponding sha_256
    for df, sha_256 in dfs:
        print(f"Saving {len(df)} transactions to database")
        save_transactions(df, sha_256)

    # Combine all dataframes for display
    combined_df = pd.concat([df for df, _ in dfs], ignore_index=True)
    print(f"Combined dataframe has {len(combined_df)} transactions")

    # Sort by date
    combined_df = combined_df.sort_values('Date', ascending=False)

    # Convert date to string format for JSON serialization
    combined_df['Date'] = combined_df['Date'].dt.strftime('%Y-%m-%d')

    # Get unique tags
    tags = [{'label': tag, 'value': tag} for tag in combined_df['Tags'].str.split(',').explode().unique() if tag]
    print(f"Found {len(tags)} unique tags")

    return combined_df.to_dict('records'), tags, status_messages
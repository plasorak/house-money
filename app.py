import dash
from dash import html, dcc, callback, Input, Output, State, PreventUpdate
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import base64
import io
import sqlite3
import os

import hashlib

# Initialize the Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "House Money"

# Database setup
DB_PATH = 'transactions.db'

def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Drop existing tables if they exist to recreate with new schema
    c.execute('DROP TABLE IF EXISTS transactions')
    c.execute('DROP TABLE IF EXISTS uploaded_files')
    c.execute('DROP TABLE IF EXISTS categories')

    # Create categories table first
    c.execute('''
        CREATE TABLE IF NO  T EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            color TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create uploaded_files table
    c.execute('''
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            sha_256 TEXT NOT NULL UNIQUE,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            transaction_count INTEGER NOT NULL
        )
    ''')

    # Create transactions table with foreign keys
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            category_id INTEGER NOT NULL,
            file_sha_256 TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id),
            FOREIGN KEY (file_sha_256) REFERENCES uploaded_files(sha_256)
        )
    ''')

    # Insert default categories
    default_categories = [
        ('Groceries', 'Food and household items', '#FF9999'),
        ('Dining', 'Restaurants and takeout', '#99FF99'),
        ('Transportation', 'Gas, public transit, and car maintenance', '#9999FF'),
        ('Shopping', 'Retail purchases', '#FFFF99'),
        ('Entertainment', 'Movies, events, and hobbies', '#FF99FF'),
        ('Utilities', 'Bills and services', '#99FFFF'),
        ('Housing', 'Rent, mortgage, and home maintenance', '#FFB366'),
        ('Healthcare', 'Medical expenses', '#FF6666')
    ]
    c.executemany('''
        INSERT OR IGNORE INTO categories (name, description, color)
        VALUES (?, ?, ?)
    ''', default_categories)

    conn.commit()
    conn.close()

def calculate_file_hash(contents):
    """Calculate SHA-256 hash of file contents."""
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    return hashlib.sha256(decoded).hexdigest()

def save_file_info(filename, sha_256, transaction_count):
    """Save file information to the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT filename, upload_date, transaction_count, sha_256
        FROM uploaded_files
        ORDER BY upload_date DESC
    """, conn)
    conn.close()
    return df

def get_categories():
    """Get all categories from the database."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM categories ORDER BY name", conn)
    conn.close()
    return df

def add_category(name, description, color):
    """Add a new category to the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO categories (name, description, color)
            VALUES (?, ?, ?)
        ''', (name, description, color))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_category(category_id, name, description, color):
    """Update an existing category."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE categories
            SET name = ?, description = ?, color = ?
            WHERE id = ?
        ''', (name, description, color, category_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_category(category_id):
    """Delete a category."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM categories WHERE id = ?', (category_id,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def save_transactions(df, sha_256):
    """Save transactions to the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get category IDs
    categories = {row[1]: row[0] for row in c.execute("SELECT id, name FROM categories")}

    # Add category_id column
    df['category_id'] = df['Category'].map(categories)
    df['file_sha_256'] = sha_256

    # Drop the Category column as we now use category_id
    df = df.drop('Category', axis=1)

    df.to_sql('transactions', conn, if_exists='append', index=False)
    conn.close()

def load_transactions():
    """Load all transactions from the database."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT t.id, t.date, t.description, t.amount, c.name as category,
               c.id as category_id, t.file_sha_256, f.filename
        FROM transactions t
        JOIN categories c ON t.category_id = c.id
        JOIN uploaded_files f ON t.file_sha_256 = f.sha_256
        ORDER BY t.date DESC
    """, conn)
    conn.close()

    if not df.empty:
        df['Date'] = pd.to_datetime(df['date'])
        df = df.rename(columns={
            'date': 'Date',
            'description': 'Description',
            'amount': 'Amount',
            'category': 'Category',
            'category_id': 'Category ID',
            'file_sha_256': 'File SHA-256',
            'filename': 'Source File'
        })
    return df

# Initialize database on startup
init_db()

# Layout
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H1("Family Finance Dashboard", className="text-center mb-4"),
        ])
    ]),

    # File Upload Section
    dbc.Row([
        dbc.Col([
            html.H4("Select CSV Format", className="mt-4"),
            dcc.Dropdown(
                id='csv-format',
                options=[
                    {'label': 'Standard Format (Date, Description, Amount)', 'value': 'standard'},
                    {'label': 'Bank Format (Transaction Date, Details, Transaction Amount)', 'value': 'bank'},
                    {'label': 'Custom Format', 'value': 'custom'}
                ],
                value='standard',
                clearable=False
            ),
            html.Div(id='custom-format-inputs', style={'display': 'none'}, children=[
                dbc.Row([
                    dbc.Col([
                        html.Label("Date Column"),
                        dcc.Input(id='date-column', type='text', placeholder='Enter column name')
                    ], width=4),
                    dbc.Col([
                        html.Label("Description Column"),
                        dcc.Input(id='description-column', type='text', placeholder='Enter column name')
                    ], width=4),
                    dbc.Col([
                        html.Label("Amount Column"),
                        dcc.Input(id='amount-column', type='text', placeholder='Enter column name')
                    ], width=4),
                ])
            ]),
            dcc.Upload(
                id='upload-data',
                children=html.Div([
                    'Drag and Drop or ',
                    html.A('Select CSV Files')
                ]),
                style={
                    'width': '100%',
                    'height': '60px',
                    'lineHeight': '60px',
                    'borderWidth': '1px',
                    'borderStyle': 'dashed',
                    'borderRadius': '5px',
                    'textAlign': 'center',
                    'margin': '10px'
                },
                multiple=True
            ),
            html.Div(id='upload-status', className="mt-2"),
            html.Div(id='uploaded-files-table', className="mt-4"),
        ])
    ]),

    # Filters Section
    dbc.Row([
        dbc.Col([
            html.H4("Filters", className="mt-4"),
            dbc.Row([
                dbc.Col([
                    html.Label("Date Range"),
                    dcc.DatePickerRange(
                        id='date-range',
                        start_date=datetime.now().replace(day=1),
                        end_date=datetime.now(),
                    ),
                ], width=6),
                dbc.Col([
                    html.Label("Categories to Ignore"),
                    dcc.Dropdown(
                        id='category-filter',
                        multi=True,
                        placeholder="Select categories to ignore"
                    ),
                ], width=6),
            ]),
        ])
    ]),

    # Tabs Section
    dbc.Row([
        dbc.Col([
            dbc.Tabs([
                # Overview Tab
                dbc.Tab([
                    dbc.Row([
                        dbc.Col([
                            html.H4("Monthly Overview", className="mt-4"),
                            html.Div(id='monthly-summary')
                        ])
                    ]),
                    dbc.Row([
                        dbc.Col([
                            dcc.Graph(id='spending-trend'),
                        ], width=6),
                        dbc.Col([
                            dcc.Graph(id='category-breakdown'),
                        ], width=6),
                    ]),
                ], label="Overview", tab_id="overview"),

                # Metrics Tab
                dbc.Tab([
                    dbc.Row([
                        dbc.Col([
                            html.H4("Key Metrics", className="mt-4"),
                            dbc.Card([
                                dbc.CardBody([
                                    html.Div(id='metrics-content')
                                ])
                            ])
                        ])
                    ]),
                ], label="Metrics", tab_id="metrics"),

                # Transactions Tab
                dbc.Tab([
                    dbc.Row([
                        dbc.Col([
                            html.H4("Transactions", className="mt-4"),
                            html.Div(id='transaction-table')
                        ])
                    ]),
                ], label="Transactions", tab_id="transactions"),

                # Categories Tab
                dbc.Tab([
                    dbc.Row([
                        dbc.Col([
                            html.H4("Manage Categories", className="mt-4"),
                            dbc.Button("Add New Category", id="add-category-btn", color="primary", className="mb-3"),
                            html.Div(id="category-form-container"),
                            html.Div(id="categories-table-container")
                        ])
                    ])
                ], label="Categories", tab_id="categories"),
            ], id="tabs", active_tab="overview"),
        ])
    ]),

    # Store component for the data
    dcc.Store(id='stored-data', data=load_transactions().to_dict('records')),

], fluid=True)

@callback(
    Output('custom-format-inputs', 'style'),
    Input('csv-format', 'value')
)
def toggle_custom_format(format_type):
    if format_type == 'custom':
        return {'display': 'block'}
    return {'display': 'none'}

def parse_contents(contents, filename, format_type='standard', custom_columns=None):
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)

    try:
        df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))

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

        # Check if required columns exist in the CSV
        if not all(col in df.columns for col in mapping.values()):
            missing_cols = [col for col in mapping.values() if col not in df.columns]
            return None, f"CSV is missing required columns: {', '.join(missing_cols)}"

        # Rename columns to standard format
        df = df.rename(columns={
            mapping['date']: 'Date',
            mapping['description']: 'Description',
            mapping['amount']: 'Amount'
        })

        # Convert date column to datetime
        df['Date'] = pd.to_datetime(df['Date'])

        # Add Category column if it doesn't exist
        if 'Category' not in df.columns:
            df['Category'] = 'Uncategorized'

        # Ensure Amount is numeric
        df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')

        # Remove any rows with invalid amounts
        df = df.dropna(subset=['Amount'])

        return df, None
    except Exception as e:
        return None, f"Error processing {filename}: {str(e)}"

@callback(
    [Output('stored-data', 'data'),
     Output('category-filter', 'options'),
     Output('upload-status', 'children'),
     Output('uploaded-files-table', 'children')],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename'),
     State('csv-format', 'value'),
     State('date-column', 'value'),
     State('description-column', 'value'),
     State('amount-column', 'value')]
)
def update_data(contents_list, filename_list, format_type, custom_date_col, custom_desc_col, custom_amount_col):
    if not contents_list:
        # If no new data uploaded, load from database
        df = load_transactions()
        if df.empty:
            return None, [], "", create_uploaded_files_table()
        categories = [{'label': cat, 'value': cat} for cat in df['Category'].unique()]
        return df.to_dict('records'), categories, "", create_uploaded_files_table()

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
        # Calculate file hash
        sha_256 = calculate_file_hash(contents)

        # Check if file was already uploaded
        if not save_file_info(filename, sha_256, 0):  # We'll update the count after processing
            status_messages.append(f"⚠️ {filename} was already uploaded and will be skipped")
            continue

        df, error = parse_contents(contents, filename, format_type, custom_columns)
        if df is not None:
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
            status_messages.append(f"❌ {filename}: {error}")

    if not dfs:
        return None, [], html.Div(status_messages), create_uploaded_files_table()

    # Save each dataframe with its corresponding sha_256
    for df, sha_256 in dfs:
        save_transactions(df, sha_256)

    # Combine all dataframes for display
    combined_df = pd.concat([df for df, _ in dfs], ignore_index=True)

    # Sort by date
    combined_df = combined_df.sort_values('Date', ascending=False)

    # Convert date to string format for JSON serialization
    combined_df['Date'] = combined_df['Date'].dt.strftime('%Y-%m-%d')

    # Get unique categories
    categories = [{'label': cat, 'value': cat} for cat in combined_df['Category'].unique()]

    return combined_df.to_dict('records'), categories, html.Div(status_messages), create_uploaded_files_table()

def create_uploaded_files_table():
    """Create a table showing uploaded files."""
    df = get_uploaded_files()
    if df.empty:
        return html.Div("No files uploaded yet")

    df['upload_date'] = pd.to_datetime(df['upload_date'])
    df['upload_date'] = df['upload_date'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # Format the SHA-256 to be more readable (first 8 chars)
    df['sha_256'] = df['sha_256'].apply(lambda x: f"{x[:8]}...")

    return html.Div([
        html.H5("Uploaded Files", className="mt-4"),
        dbc.Table.from_dataframe(
            df,
            striped=True,
            bordered=True,
            hover=True
        )
    ])

@callback(
    [Output('spending-trend', 'figure'),
     Output('category-breakdown', 'figure'),
     Output('monthly-summary', 'children'),
     Output('transaction-table', 'children'),
     Output('metrics-content', 'children')],
    [Input('stored-data', 'data'),
     Input('date-range', 'start_date'),
     Input('date-range', 'end_date'),
     Input('category-filter', 'value')]
)
def update_charts(data, start_date, end_date, ignored_categories):
    print("Debug - Data received:", len(data) if data else 0, "records")

    if not data:
        empty_fig = go.Figure()
        empty_fig.update_layout(title="No data uploaded")
        return empty_fig, empty_fig, "No data uploaded", "No data uploaded", "No data uploaded"

    df = pd.DataFrame(data)
    print("Debug - DataFrame created with columns:", df.columns.tolist())

    # Convert date strings to datetime
    df['Date'] = pd.to_datetime(df['Date'])
    df['Amount'] = pd.to_numeric(df['Amount'])

    print("Debug - Date range:", df['Date'].min(), "to", df['Date'].max())
    print("Debug - Amount range:", df['Amount'].min(), "to", df['Amount'].max())

    # Apply filters
    mask = (df['Date'] >= start_date) & (df['Date'] <= end_date)
    if ignored_categories:
        mask &= ~df['Category'].isin(ignored_categories)
    df = df[mask]

    print("Debug - Filtered data points:", len(df))

    # Monthly spending trend
    monthly_spending = df.groupby(df['Date'].dt.strftime('%Y-%m'))['Amount'].sum().reset_index()
    print("Debug - Monthly spending points:", len(monthly_spending))

    trend_fig = px.line(monthly_spending, x='Date', y='Amount',
                       title='Monthly Spending Trend')
    trend_fig.update_layout(
        xaxis_title="Month",
        yaxis_title="Amount ($)",
        hovermode='x unified'
    )

    # Category breakdown
    category_spending = df.groupby('Category')['Amount'].sum().reset_index()
    print("Debug - Categories:", category_spending['Category'].tolist())

    category_fig = px.pie(category_spending, values='Amount', names='Category',
                         title='Spending by Category')
    category_fig.update_traces(textposition='inside', textinfo='percent+label')

    # Monthly summary
    current_month = datetime.now().strftime('%Y-%m')
    current_month_spending = df[df['Date'].dt.strftime('%Y-%m') == current_month]['Amount'].sum()
    avg_monthly_spending = df.groupby(df['Date'].dt.strftime('%Y-%m'))['Amount'].sum().mean()

    summary = html.Div([
        html.H5(f"Current Month Spending: ${current_month_spending:.2f}"),
        html.H5(f"Average Monthly Spending: ${avg_monthly_spending:.2f}")
    ])

    # Create interactive transaction table
    transaction_table = create_transaction_table(load_transactions())

    # Metrics content
    total_spending = df['Amount'].sum()
    num_transactions = len(df)
    avg_transaction = total_spending / num_transactions if num_transactions > 0 else 0
    top_category = category_spending.loc[category_spending['Amount'].idxmax()]['Category']
    top_category_amount = category_spending.loc[category_spending['Amount'].idxmax()]['Amount']

    metrics = html.Div([
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H4("Total Spending"),
                        html.H3(f"${total_spending:,.2f}")
                    ])
                ], className="mb-4")
            ], width=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H4("Number of Transactions"),
                        html.H3(f"{num_transactions:,}")
                    ])
                ], className="mb-4")
            ], width=6),
        ]),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H4("Average Transaction"),
                        html.H3(f"${avg_transaction:,.2f}")
                    ])
                ], className="mb-4")
            ], width=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H4("Top Spending Category"),
                        html.H3(f"{top_category}"),
                        html.P(f"${top_category_amount:,.2f}")
                    ])
                ], className="mb-4")
            ], width=6),
        ])
    ])

    return trend_fig, category_fig, summary, transaction_table, metrics

def update_transaction_category(transaction_id, new_category_id):
    """Update the category of a transaction."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE transactions
            SET category_id = ?
            WHERE id = ?
        ''', (new_category_id, transaction_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating transaction category: {e}")
        return False
    finally:
        conn.close()

def get_category_options():
    """Get categories for dropdown options."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT id, name, color FROM categories ORDER BY name", conn)
    conn.close()
    return [{'label': row['name'], 'value': row['id'], 'style': {'color': row['color']}} for _, row in df.iterrows()]

def create_transaction_table(df):
    """Create an interactive transaction table with category dropdowns."""
    if df.empty:
        return html.Div("No transactions found")

    # Get category options for dropdowns
    category_options = get_category_options()

    # Create table header
    table_header = [
        html.Thead(html.Tr([
            html.Th("Date"),
            html.Th("Description"),
            html.Th("Amount"),
            html.Th("Category"),
            html.Th("Source File")
        ]))
    ]

    # Create table rows with category dropdowns
    rows = []
    for _, row in df.iterrows():
        category_dropdown = dcc.Dropdown(
            id={'type': 'category-dropdown', 'index': row['id']},
            options=category_options,
            value=row['Category ID'],
            clearable=False,
            style={'width': '150px'}
        )

        rows.append(html.Tr([
            html.Td(row['Date'].strftime('%Y-%m-%d')),
            html.Td(row['Description']),
            html.Td(f"${row['Amount']:.2f}"),
            html.Td(category_dropdown),
            html.Td(row['Source File'])
        ]))

    table_body = [html.Tbody(rows)]

    return html.Div([
        html.H5("Transactions", className="mt-4"),
        dbc.Table(table_header + table_body, striped=True, bordered=True, hover=True)
    ])

@callback(
    Output("categories-table-container", "children"),
    Input("add-category-btn", "n_clicks"),
    Input("category-form-submit", "n_clicks"),
    Input("category-delete", "n_clicks"),
    prevent_initial_call=True
)
def update_categories_table(n_add, n_submit, n_delete):
    df = get_categories()

    if df.empty:
        return html.Div("No categories found")

    # Format the table with color swatches
    table_header = [
        html.Thead(html.Tr([
            html.Th("Color"),
            html.Th("Name"),
            html.Th("Description"),
            html.Th("Created At")
        ]))
    ]

    rows = []
    for _, row in df.iterrows():
        color_swatch = html.Td(
            html.Div(
                style={
                    'width': '20px',
                    'height': '20px',
                    'backgroundColor': row['color'],
                    'border': '1px solid #ddd',
                    'borderRadius': '3px'
                }
            )
        )
        rows.append(html.Tr([
            color_swatch,
            html.Td(row['name']),
            html.Td(row['description']),
            html.Td(pd.to_datetime(row['created_at']).strftime('%Y-%m-%d %H:%M'))
        ]))

    table_body = [html.Tbody(rows)]

    return html.Div([
        html.H5("Available Categories", className="mt-4"),
        dbc.Table(table_header + table_body, striped=True, bordered=True, hover=True)
    ])

@callback(
    Output("category-form-container", "children"),
    Input("add-category-btn", "n_clicks"),
    prevent_initial_call=True
)
def show_category_form(n_clicks):
    if n_clicks is None:
        return None

    return dbc.Card([
        dbc.CardBody([
            html.H5("Add New Category"),
            dbc.Input(id="category-name", placeholder="Category Name", className="mb-3"),
            dbc.Input(id="category-description", placeholder="Description", className="mb-3"),
            dbc.Input(id="category-color", type="color", className="mb-3"),
            dbc.Button("Submit", id="category-form-submit", color="primary", className="me-2"),
            dbc.Button("Cancel", id="category-form-cancel", color="secondary")
        ])
    ])

@callback(
    Output("category-form-container", "children", allow_duplicate=True),
    Input("category-form-cancel", "n_clicks"),
    prevent_initial_call=True
)
def hide_category_form(n_clicks):
    if n_clicks is None:
        raise PreventUpdate
    return None

@callback(
    Output("category-form-container", "children", allow_duplicate=True),
    Input("category-form-submit", "n_clicks"),
    State("category-name", "value"),
    State("category-description", "value"),
    State("category-color", "value"),
    prevent_initial_call=True
)
def submit_category_form(n_clicks, name, description, color):
    if n_clicks is None:
        raise PreventUpdate

    if not name:
        return html.Div("Category name is required", style={"color": "red"})

    success = add_category(name, description, color)
    if success:
        return None
    else:
        return html.Div("Category name already exists", style={"color": "red"})

@callback(
    Output('transaction-table', 'children', allow_duplicate=True),
    Input('category-dropdown', 'value'),
    State('category-dropdown', 'id'),
    prevent_initial_call=True
)
def update_transaction_category_callback(new_category_id, dropdown_id):
    if not dropdown_id or not new_category_id:
        raise PreventUpdate

    # Extract transaction_id from the dropdown_id (format: "category-dropdown-{transaction_id}")
    transaction_id = int(dropdown_id.split('-')[-1])

    # Update the category in the database
    if update_transaction_category(transaction_id, new_category_id):
        # Reload and display the updated transactions
        df = load_transactions()
        return create_transaction_table(df)

    raise PreventUpdate

if __name__ == '__main__':
    app.run(debug=True)
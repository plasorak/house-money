import dash
from dash import html, dcc, callback, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import base64
import io
import sqlite3
import hashlib
from database import (
    init_db, get_tags, add_tag, update_tag, delete_tag,
    save_file_info, get_uploaded_files, save_transactions, load_transactions,
    update_transaction_tags, get_tag_options, DB_PATH
)

# Initialize the Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)
app.title = "House Money"

def calculate_file_hash(contents):
    """Calculate SHA-256 hash of file contents."""
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    return hashlib.sha256(decoded).hexdigest()

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

        # Add Tags column if it doesn't exist
        if 'Tags' not in df.columns:
            df['Tags'] = ''

        # Ensure Amount is numeric
        df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')

        # Remove any rows with invalid amounts
        df = df.dropna(subset=['Amount'])

        return df, None
    except Exception as e:
        return None, f"Error processing {filename}: {str(e)}"

# Initialize database on startup
init_db()

# Layout
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H1("House Money", className="text-center mb-4"),
        ])
    ]),

    # Tabs Section
    dbc.Row([
        dbc.Col([
            dbc.Tabs([
                # Transactions Tab
                dbc.Tab([
                    dbc.Row([
                        dbc.Col([
                            html.H4("Transactions", className="mt-4"),
                            html.Div(id='transaction-table')
                        ])
                    ]),
                ], label="Transactions", tab_id="transactions"),

                # Tags Tab
                dbc.Tab([
                    dbc.Row([
                        dbc.Col([
                            html.H4("Manage Tags", className="mt-4"),
                            dbc.Button("Add New Tag", id="add-tag-btn", color="primary", className="mb-3"),
                            html.Div(id="tag-form-container"),
                            html.Div(id="tags-table-container")
                        ])
                    ])
                ], label="Tags", tab_id="tags"),

                # Import Tab
                dbc.Tab([
                    dbc.Row([
                        dbc.Col([
                            html.H4("Import Transactions", className="mt-4"),
                            html.Div([
                                html.H5("Select CSV Format", className="mt-4"),
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
                            ]),
                            html.Div(id='uploaded-files-table', className="mt-4"),
                        ])
                    ])
                ], label="Import", tab_id="import"),
            ], id="tabs", active_tab="transactions"),
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
                    html.Label("Tags to Ignore"),
                    dcc.Dropdown(
                        id='tag-filter',
                        multi=True,
                        placeholder="Select tags to ignore"
                    ),
                ], width=6),
            ]),
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

@callback(
    [Output('stored-data', 'data'),
     Output('tag-filter', 'options'),
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
        tags = [{'label': tag, 'value': tag} for tag in df['Tags'].str.split(',').explode().unique() if tag]
        return df.to_dict('records'), tags, "", create_uploaded_files_table()

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

    # Get unique tags
    tags = [{'label': tag, 'value': tag} for tag in combined_df['Tags'].str.split(',').explode().unique() if tag]

    return combined_df.to_dict('records'), tags, html.Div(status_messages), create_uploaded_files_table()

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
    Output('transaction-table', 'children'),
    [Input('stored-data', 'data'),
     Input('date-range', 'start_date'),
     Input('date-range', 'end_date'),
     Input('tag-filter', 'value')]
)
def update_transaction_table(data, start_date, end_date, ignored_tags):
    if not data:
        return html.Div("No transactions found")

    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    df['Amount'] = pd.to_numeric(df['Amount'])

    # Apply filters
    mask = (df['Date'] >= start_date) & (df['Date'] <= end_date)
    if ignored_tags:
        # Filter out transactions that have any of the ignored tags
        mask &= ~df['Tags'].str.contains('|'.join(ignored_tags), na=False)
    df = df[mask]

    return create_transaction_table(df)

@callback(
    Output("tags-table-container", "children"),
    Input("add-tag-btn", "n_clicks"),
    Input("tag-form-submit", "n_clicks"),
    Input("tag-delete", "n_clicks"),
    prevent_initial_call=True,
    suppress_callback_exceptions=True,
)
def update_tags_table(n_add, n_submit, n_delete):
    df = get_tags()

    if df.empty:
        return html.Div("No tags found")

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
        html.H5("Available Tags", className="mt-4"),
        dbc.Table(table_header + table_body, striped=True, bordered=True, hover=True)
    ])

@callback(
    Output("tag-form-container", "children"),
    Input("add-tag-btn", "n_clicks"),
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def show_tag_form(n_clicks):
    if n_clicks is None:
        return None

    return dbc.Card([
        dbc.CardBody([
            html.H5("Add New Tag"),
            dbc.Input(id="tag-name", placeholder="Tag Name", className="mb-3"),
            dbc.Input(id="tag-description", placeholder="Description", className="mb-3"),
            dbc.Input(id="tag-color", type="color", className="mb-3"),
            dbc.Button("Submit", id="tag-form-submit", color="primary", className="me-2"),
            dbc.Button("Cancel", id="tag-form-cancel", color="secondary")
        ])
    ])

@callback(
    Output("tag-form-container", "children", allow_duplicate=True),
    Input("tag-form-cancel", "n_clicks"),
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def hide_tag_form(n_clicks):
    if n_clicks is None:
        raise PreventUpdate
    return None

@callback(
    Output("tag-form-container", "children", allow_duplicate=True),
    Input("tag-form-submit", "n_clicks"),
    State("tag-name", "value"),
    State("tag-description", "value"),
    State("tag-color", "value"),
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def submit_tag_form(n_clicks, name, description, color):
    if n_clicks is None:
        raise PreventUpdate

    if not name:
        return html.Div("Tag name is required", style={"color": "red"})

    success = add_tag(name, description, color)
    if success:
        return None
    else:
        return html.Div("Tag name already exists", style={"color": "red"})

@callback(
    Output('transaction-table', 'children', allow_duplicate=True),
    Input('tag-filter', 'value'),
    State('tag-filter', 'id'),
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def update_transaction_tags_callback(new_tag_ids, dropdown_id):
    if not dropdown_id or not new_tag_ids:
        raise PreventUpdate

    # Extract transaction_id from the dropdown_id
    transaction_id = int(dropdown_id['index'])

    # Update the tags in the database
    if update_transaction_tags(transaction_id, new_tag_ids):
        # Reload and display the updated transactions
        df = load_transactions()
        return create_transaction_table(df)

    raise PreventUpdate

def create_transaction_table(df):
    """Create an interactive transaction table with tag dropdowns."""
    if df.empty:
        return html.Div("No transactions found")

    # Get tag options for dropdowns
    tag_options = get_tag_options()

    # Create table header
    table_header = [
        html.Thead(html.Tr([
            html.Th("Date"),
            html.Th("Description"),
            html.Th("Amount"),
            html.Th("Tags"),
            html.Th("Source File")
        ]))
    ]

    # Create table rows with tag dropdowns
    rows = []
    for _, row in df.iterrows():
        # Get current tags for this transaction
        current_tags = [tag.strip() for tag in str(row['Tags']).split(',') if tag.strip()]

        tag_dropdown = dcc.Dropdown(
            id={'type': 'tag-filter', 'index': row['id']},
            options=tag_options,
            value=current_tags,
            multi=True,
            clearable=True,
            style={'width': '200px'}
        )

        rows.append(html.Tr([
            html.Td(row['Date'].strftime('%Y-%m-%d')),
            html.Td(row['Description']),
            html.Td(f"${row['Amount']:.2f}"),
            html.Td(tag_dropdown),
            html.Td(row['Source File'])
        ]))

    table_body = [html.Tbody(rows)]

    return html.Div([
        html.H5("Transactions", className="mt-4"),
        dbc.Table(table_header + table_body, striped=True, bordered=True, hover=True)
    ])

if __name__ == '__main__':
    app.run(debug=True)
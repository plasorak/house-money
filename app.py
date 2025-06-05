import dash
from dash import html, dcc, callback, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from dateutil.relativedelta import relativedelta
import base64
import io
import sqlite3
import hashlib
import atexit
from database import (
    init_db, get_tags, add_tag, update_tag, delete_tag,
    save_file_info, get_uploaded_files, save_transactions, load_transactions,
    update_transaction_note, update_transaction_tags, get_tag_name_to_id_mapping,
    create_manual_transaction, load_transactions_with_sort, DB_PATH,
    close_thread_connection, delete_transactions
)
from file_import import process_uploaded_files

# Register cleanup function for the main thread
atexit.register(close_thread_connection)

# Add cleanup for each callback
def cleanup_after_callback(func):
    """Decorator to clean up database connections after callbacks."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            close_thread_connection()
    return wrapper

# Initialize the Dash app
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        'https://fonts.googleapis.com/css2?family=Financier+Display&display=swap',
        '/assets/custom.css'
    ],
    suppress_callback_exceptions=True
)
app.title = "House Money"

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
                            dbc.Button("Add Transaction", id="add-transaction-btn", color="primary", className="mb-3"),
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

    # Store components for the data
    dcc.Store(id='stored-data', data=load_transactions().to_dict('records')),
    dcc.Store(id='sort-state', data={'column': 'date', 'ascending': True}),
    dcc.Store(id='filter-state', data={'text': '', 'column': 'description'}),
    dcc.Store(id='selected-transactions', data=[]),  # Store selected transaction IDs

    # Add Transaction Modal
    dbc.Modal([
        dbc.ModalHeader("Add New Transaction"),
        dbc.ModalBody([
            dbc.Form([
                dbc.Row([
                    dbc.Col([
                        html.Label("Date & Time"),
                        dcc.DatePickerSingle(
                            id='new-transaction-date',
                            date=datetime.now().date(),
                            display_format='YYYY-MM-DD'
                        ),
                        dbc.Input(
                            id='new-transaction-time',
                            type='text',
                            value=datetime.now().strftime('%H:%M'),
                            placeholder='HH:MM',
                            pattern='^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$',
                            style={'marginTop': '10px'}
                        ),
                        html.Small("Format: HH:MM (24-hour)", className="text-muted")
                    ], width=6),
                    dbc.Col([
                        html.Label("Amount"),
                        dbc.Input(
                            id='new-transaction-amount',
                            type='number',
                            step='0.01',
                            placeholder='Enter amount'
                        )
                    ], width=6)
                ], className="mb-3"),
                dbc.Row([
                    dbc.Col([
                        html.Label("Description"),
                        dbc.Input(
                            id='new-transaction-description',
                            type='text',
                            placeholder='Enter description'
                        )
                    ])
                ], className="mb-3"),
                dbc.Row([
                    dbc.Col([
                        html.Label("Tags"),
                        dcc.Dropdown(
                            id='new-transaction-tags',
                            options=[{'label': name, 'value': id} for name, id in get_tag_name_to_id_mapping().items()],
                            multi=True,
                            clearable=True
                        )
                    ])
                ], className="mb-3"),
                dbc.Row([
                    dbc.Col([
                        html.Label("Notes"),
                        dbc.Textarea(
                            id='new-transaction-notes',
                            placeholder='Enter notes (optional)'
                        )
                    ])
                ])
            ])
        ]),
        dbc.ModalFooter([
            dbc.Button("Cancel", id="cancel-transaction", className="ms-auto", n_clicks=0),
            dbc.Button("Add Transaction", id="submit-transaction", className="ms-2", n_clicks=0)
        ])
    ], id="add-transaction-modal", is_open=False)

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
    [Output('stored-data', 'data', allow_duplicate=True),
     Output('upload-status', 'children'),
     Output('uploaded-files-table', 'children'),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename'),
     State('csv-format', 'value'),
     State('date-column', 'value'),
     State('description-column', 'value'),
     State('amount-column', 'value'),
     State('sort-state', 'data')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
@cleanup_after_callback
def update_data(contents_list, filename_list, format_type, custom_date_col, custom_desc_col, custom_amount_col, sort_state):
    print(f"update_data called with {len(contents_list) if contents_list else 0} files")
    if not contents_list:
        # If no new data uploaded, load from database
        print("No new data uploaded, loading from database")
        df = load_transactions_with_sort(sort_state['column'], sort_state['ascending'])
        print(f"Loaded {len(df)} transactions from database")

        # Always refresh the uploaded files table
        uploaded_files_table = create_uploaded_files_table()

        if df.empty:
            return None, "", uploaded_files_table, html.Div("No transaction found")

        return df.to_dict('records'), "", uploaded_files_table, create_transaction_table(df)

    # Process uploaded files using the new module
    data, tags, status_messages = process_uploaded_files(
        contents_list,
        filename_list,
        format_type,
        custom_date_col,
        custom_desc_col,
        custom_amount_col
    )

    # Create the uploaded files table
    uploaded_files_table = create_uploaded_files_table()

    # Load transactions for the table with current sort
    df = load_transactions_with_sort(sort_state['column'], sort_state['ascending'])

    return df.to_dict('records'), html.Div(status_messages), uploaded_files_table, create_transaction_table(df)

# Add a separate callback for initial data loading
@callback(
    [Output('stored-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True)],
    Input('tabs', 'active_tab'),
    State('sort-state', 'data'),
    prevent_initial_call='initial_duplicate',
    suppress_callback_exceptions=True
)
def load_initial_data(active_tab, sort_state):
    if active_tab != 'transactions':
        raise PreventUpdate

    df = load_transactions_with_sort(sort_state['column'], sort_state['ascending'])
    if df.empty:
        return None, html.Div("No transaction found")

    return df.to_dict('records'), create_transaction_table(df)

def create_uploaded_files_table():
    """Create a table showing uploaded files."""
    print("Creating uploaded files table...")
    df = get_uploaded_files()
    print(f"Got uploaded files from database: {len(df)} files")
    print(f"Files: {df.to_dict('records') if not df.empty else 'No files'}")

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
    Output('transaction-table', 'children', allow_duplicate=True),
    [Input('date-range', 'start_date'),
     Input('date-range', 'end_date')],
    prevent_initial_call=True
)
def update_transaction_table(start_date, end_date):
    # Load transactions directly from database
    df = load_transactions()
    print(f"Loaded {len(df)} transactions from database")
    if df.empty:
        return html.Div("No transaction found")

    # Apply filters
    mask = (df['Date'] >= start_date) & (df['Date'] <= end_date)
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
    [Output('stored-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input('tag-filter', 'value')],
    [State('tag-filter', 'id'),
     State('sort-state', 'data')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def update_transaction_tags_callback(new_tag_ids, dropdown_id, sort_state):
    print("update_transaction_tags_callback")
    if not dropdown_id or not new_tag_ids:
        raise PreventUpdate

    # Extract transaction_id from the dropdown_id
    transaction_id = int(dropdown_id['index'])

    # Update the tags in the database
    if update_transaction_tags(transaction_id, new_tag_ids):
        # Reload and display the updated transactions with current sort
        df = load_transactions_with_sort(sort_state['column'], sort_state['ascending'])
        return df.to_dict('records'), create_transaction_table(df)

    raise PreventUpdate

@callback(
    [Output('stored-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input({'type': 'note-input', 'index': dash.ALL}, 'value')],
    [State({'type': 'note-input', 'index': dash.ALL}, 'id'),
     State('sort-state', 'data')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def update_transaction_note_callback(note_values, note_ids, sort_state):
    if not note_ids:
        raise PreventUpdate

    # Find which input triggered the callback
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if not triggered_id:
        raise PreventUpdate

    # Parse the triggered ID to get the transaction ID
    import json
    triggered_id = json.loads(triggered_id)
    transaction_id = triggered_id['index']

    # Get the new note value
    note_index = next(i for i, id_dict in enumerate(note_ids) if id_dict['index'] == transaction_id)
    new_note = note_values[note_index]

    # Update the note in the database
    if update_transaction_note(transaction_id, new_note):
        # Reload and display the updated transactions with current sort
        df = load_transactions_with_sort(sort_state['column'], sort_state['ascending'])
        return df.to_dict('records'), create_transaction_table(df)

    raise PreventUpdate

def create_transaction_table(df):
    """Create an interactive transaction table with tag dropdowns."""
    if df.empty:
        return html.Div("No transaction found")

    # Get tag name to ID mapping
    tag_name_to_id = get_tag_name_to_id_mapping()

    # Get current sort state from the stored data
    sort_state = {'column': 'date', 'ascending': True}  # Default sort state
    if hasattr(df, 'attrs') and 'sort_state' in df.attrs:
        sort_state = df.attrs['sort_state']

    # Helper function to create sort indicator
    def get_sort_indicator(column):
        if sort_state['column'] != column:
            return "↕"  # Default indicator
        return "↑" if sort_state['ascending'] else "↓"

    # Create table header with sortable columns
    table_header = [
        html.Thead(html.Tr([
            html.Th("Select"),  # New column for checkboxes
            html.Th([
                "Date & Time ",
                html.Span(get_sort_indicator('date'), style={"marginLeft": "5px"})
            ], id="sort-date", style={"cursor": "pointer"}),
            html.Th([
                html.Div([
                    html.Div([
                        "Description ",
                        html.Span(get_sort_indicator('description'), style={"marginLeft": "5px"})
                    ], style={"cursor": "pointer"}, id="sort-description"),
                    dbc.Input(
                        id="description-filter",
                        type="text",
                        placeholder="Filter...",
                        size="sm",
                        style={"width": "100%", "marginTop": "5px"}
                    )
                ])
            ]),
            html.Th([
                "Amount ",
                html.Span(get_sort_indicator('amount'), style={"marginLeft": "5px"})
            ], id="sort-amount", style={"cursor": "pointer"}),
            html.Th("Tags"),
            html.Th("Notes"),
            html.Th("Source File")
        ]))
    ]

    # Create table rows with tag dropdowns
    rows = []
    for _, row in df.iterrows():
        # Get current tags for this transaction
        current_tags = [tag.strip() for tag in str(row['Tags']).split(',') if tag.strip()]
        # Convert tag names to IDs
        current_tag_ids = [tag_name_to_id.get(tag) for tag in current_tags if tag in tag_name_to_id]

        tag_dropdown = dcc.Dropdown(
            id={'type': 'tag-filter', 'index': row['id']},
            options=[{'label': name, 'value': id} for name, id in tag_name_to_id.items()],
            value=current_tag_ids,
            multi=True,
            clearable=True,
            style={'width': '200px'}
        )

        # Create notes input
        notes_input = dcc.Input(
            id={'type': 'note-input', 'index': row['id']},
            value=row.get('Notes', ''),
            placeholder='Add a note...',
            style={'width': '200px'},
            debounce=True
        )

        # Create checkbox
        checkbox = dcc.Checklist(
            id={'type': 'transaction-checkbox', 'index': row['id']},
            options=[{'label': '', 'value': row['id']}],
            value=[],
            style={'margin': '0'}
        )

        rows.append(html.Tr([
            html.Td(checkbox),
            html.Td(row['Date'].strftime('%Y-%m-%d %H:%M:%S')),
            html.Td(row['Description']),
            html.Td(f"£ {row['Amount']:.2f}"),
            html.Td(tag_dropdown),
            html.Td(notes_input),
            html.Td(row['Source File'])
        ]))

    table_body = [html.Tbody(rows)]

    return html.Div([
        html.H5("Transactions", className="mt-4"),
        dbc.Button("Delete Selected", id="delete-selected-btn", color="danger", className="mb-3", style={'display': 'none'}),
        dbc.Table(table_header + table_body, striped=True, bordered=True, hover=True, id="transaction-table-sortable")
    ])

@callback(
    [Output('stored-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True),
     Output('selected-transactions', 'data', allow_duplicate=True)],
    [Input({'type': 'transaction-checkbox', 'index': dash.ALL}, 'value')],
    [State({'type': 'transaction-checkbox', 'index': dash.ALL}, 'id'),
     State('sort-state', 'data')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def update_selected_transactions(checkbox_values, checkbox_ids, sort_state):
    # Flatten the list of selected transaction IDs
    selected_ids = [id for value_list in checkbox_values for id in value_list]

    # Load and display transactions with current sort
    df = load_transactions_with_sort(sort_state['column'], sort_state['ascending'])

    return df.to_dict('records'), create_transaction_table(df), selected_ids

@callback(
    Output("delete-selected-btn", "style"),
    Input("selected-transactions", "data"),
    prevent_initial_call=True
)
def toggle_delete_button(selected_ids):
    if selected_ids:
        return {'display': 'block'}
    return {'display': 'none'}

@callback(
    [Output('stored-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True),
     Output('filter-state', 'data', allow_duplicate=True)],
    Input('description-filter', 'value'),
    State('sort-state', 'data'),
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def filter_transactions(search_text, sort_state):
    # Update filter state
    filter_state = {'text': search_text or '', 'column': 'description'}

    # Load data with current sort and search
    df = load_transactions_with_sort(
        sort_column=sort_state['column'],
        ascending=sort_state['ascending'],
        search_text=search_text,
        search_text_on='description'
    )

    return df.to_dict('records'), create_transaction_table(df), filter_state

@callback(
    [Output('stored-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input('sort-date', 'n_clicks'),
     Input('sort-description', 'n_clicks'),
     Input('sort-amount', 'n_clicks')],
    [State('sort-state', 'data'),
     State('filter-state', 'data')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
def sort_table(n_date, n_desc, n_amount, current_sort, filter_state):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update

    # Get the triggered input
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Map column names to their database counterparts
    column_map = {
        'sort-date': 'date',
        'sort-description': 'description',
        'sort-amount': 'amount'
    }

    # Get the column to sort by
    sort_column = column_map.get(triggered_id)
    if not sort_column:
        return dash.no_update, dash.no_update

    # If clicking the same column, toggle direction
    # Otherwise, sort ascending by default
    ascending = True
    if current_sort and current_sort['column'] == sort_column:
        ascending = not current_sort['ascending']

    # Update sort state
    sort_state = {'column': sort_column, 'ascending': ascending}

    # Load data with current sort and any active filters
    df = load_transactions_with_sort(
        sort_column=sort_column,
        ascending=ascending,
        search_text=filter_state['text'],
        search_text_on=filter_state['column']
    )

    return df.to_dict('records'), create_transaction_table(df)

@callback(
    Output("add-transaction-modal", "is_open"),
    [Input("add-transaction-btn", "n_clicks"),
     Input("cancel-transaction", "n_clicks"),
     Input("submit-transaction", "n_clicks")],
    [State("add-transaction-modal", "is_open")],
    prevent_initial_call=True
)
def toggle_transaction_modal(n_add, n_cancel, n_submit, is_open):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if button_id in ["add-transaction-btn", "cancel-transaction"]:
        return not is_open
    return is_open

if __name__ == '__main__':
    app.run(debug=True)
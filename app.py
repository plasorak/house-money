import dash
from dash import html, dcc, callback, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import polars as pl
import plotly.graph_objects as go
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json
import atexit
import functools
import logging
from database import (
    get_tags, add_tag, get_uploaded_files, load_transactions,
    update_transaction_note, update_transaction_tags, get_tag_name_to_id_mapping,
    close_thread_connection
)
from file_import import process_uploaded_files

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Register cleanup function for the main thread
atexit.register(close_thread_connection)

def debug_callback(func):
    """Simple decorator to log callback name when executed."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.debug(f"Callback executed: {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

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
                            dcc.Graph(id='transaction-count-plot'),
                            dcc.DatePickerRange(
                                id='date-range',
                                start_date=datetime.now() - relativedelta(months=1),
                                end_date=datetime.now(),
                                display_format='YYYY-MM-DD',
                                className="mb-3"
                            ),
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
    dcc.Store(id='transactions-data', data=load_transactions().to_dicts()),
    dcc.Store(id='sort-state', data={'column': 'Date', 'ascending': True}),
    dcc.Store(id='filter-state', data=[]),
    dcc.Store(id='date-range-state', data={'start_date': None, 'end_date': None}),  # Store date range state

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
@debug_callback
def toggle_custom_format(format_type):
    if format_type == 'custom':
        return {'display': 'block'}
    return {'display': 'none'}

@callback(
    [Output('transactions-data', 'data', allow_duplicate=True),
     Output('upload-status', 'children'),
     Output('uploaded-files-table', 'children'),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename'),
     State('csv-format', 'value'),
     State('date-column', 'value'),
     State('description-column', 'value'),
     State('amount-column', 'value'),
     State('sort-state', 'data'),
     State('filter-state', 'data'),
     State('date-range-state', 'data')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
@debug_callback
@cleanup_after_callback
def update_data(contents_list, filename_list, format_type, custom_date_col, custom_desc_col, custom_amount_col, sort_state, filter_state, date_range_state):
    if not contents_list:
        # If no new data uploaded, load from database
        print("No new data uploaded, loading from database")
        df = load_transactions()
        print(f"Loaded {len(df)} transactions from database")

        # Apply sorting
        df = df.sort(sort_state['column'], descending=not sort_state['ascending'])

        # Always refresh the uploaded files table
        uploaded_files_table = create_uploaded_files_table()

        if df.is_empty():
            return None, "", uploaded_files_table, html.Div("No transaction found")

        return df.to_dicts(), "", uploaded_files_table, create_transaction_table(df, sort_state, filter_state, date_range_state)

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
    df = load_transactions()
    df = df.sort(sort_state['column'], descending=not sort_state['ascending'])

    return df.to_dicts(), html.Div(status_messages), uploaded_files_table, create_transaction_table(df, sort_state, filter_state, date_range_state)

# Add a separate callback for initial data loading
@callback(
    [Output('transactions-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input('tabs', 'active_tab'),
     Input('sort-state', 'data'),
     Input('filter-state', 'data'),
     Input('date-range-state', 'data')],
    prevent_initial_call='initial_duplicate',
    suppress_callback_exceptions=True
)
@debug_callback
def load_initial_data(active_tab, sort_state, filter_state, date_range_state):
    if active_tab != 'transactions':
        raise PreventUpdate

    df = load_transactions()

    # Apply date range filter if it exists
    if date_range_state and (date_range_state['start_date'] or date_range_state['end_date']):
        start_date = pl.datetime(date_range_state['start_date']) if date_range_state['start_date'] else None
        end_date = pl.datetime(date_range_state['end_date']) if date_range_state['end_date'] else None

        if start_date:
            df = df.filter(pl.col('Date') >= start_date)
        if end_date:
            df = df.filter(pl.col('Date') <= end_date)

    df = df.sort(sort_state['column'], descending=not sort_state['ascending'])

    if df.is_empty():
        return None, html.Div("No transaction found")

    return df.to_dicts(), create_transaction_table(df, sort_state, filter_state, date_range_state)

def create_uploaded_files_table():
    """Create a table showing uploaded files."""
    print("Creating uploaded files table...")
    df = get_uploaded_files()
    print(f"Got uploaded files from database: {len(df)} files")
    print(f"Files: {df.to_dicts() if not df.is_empty() else 'No files'}")

    if df.is_empty():
        return html.Div("No files uploaded yet")

    df = df.with_columns([
        pl.col('upload_date').cast(pl.Datetime).dt.strftime('%Y-%m-%d %H:%M:%S').alias('upload_date'),
        pl.col('sha_256').str.slice(0, 8).str.concat('...').alias('sha_256')
    ])

    return html.Div([
        html.H5("Uploaded Files", className="mt-4"),
        dbc.Table.from_dataframe(
            df.to_pandas(),  # Convert to pandas for dbc.Table compatibility
            striped=True,
            bordered=True,
            hover=True
        )
    ])

@callback(
    [Output('transactions-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input('date-range', 'start_date'),
     Input('date-range', 'end_date'),
     Input('sort-state', 'data'),
     Input('filter-state', 'data')],
    [State('date-range-state', 'data')],
    prevent_initial_call=True
)
@debug_callback
def update_transaction_table(start_date, end_date, sort_state, filter_state, date_range_state):
    # Load transactions directly from database
    df = load_transactions()
    print(f"Loaded {len(df)} transactions from database")
    if df.is_empty():
        return None, html.Div("No transaction found")

    # Convert dates to datetime
    start_date = pl.datetime(start_date) if start_date else None
    end_date = pl.datetime(end_date) if end_date else None

    # Apply date filters if dates are provided
    if start_date:
        df = df.filter(pl.col('Date') >= start_date)
    if end_date:
        df = df.filter(pl.col('Date') <= end_date)

    # Apply sorting
    df = df.sort(sort_state['column'], descending=not sort_state['ascending'])

    return df.to_dicts(), create_transaction_table(df, sort_state, filter_state, date_range_state)

@callback(
    Output("tags-table-container", "children"),
    Input("tabs", "active_tab"),
    prevent_initial_call='initial_duplicate',
    suppress_callback_exceptions=True,
)
@debug_callback
def update_tags_table(active_tab):
    if active_tab != "tags":
        raise PreventUpdate

    df = get_tags()

    if df.is_empty():
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
    for _, row in df.iter_rows(named=True):
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
            html.Td(row['created_at'].strftime('%Y-%m-%d %H:%M'))
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
@debug_callback
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
@debug_callback
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
@debug_callback
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
    [Output('transactions-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input({'type': 'tag-filter', 'index': dash.ALL}, 'value'),
     Input('sort-state', 'data'),
     Input('filter-state', 'data'),
     Input('date-range-state', 'data')],
    [State({'type': 'tag-filter', 'index': dash.ALL}, 'id')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
@debug_callback
def update_transaction_tags_callback(new_tag_ids, dropdown_ids, sort_state, filter_state, date_range_state):
    print("update_transaction_tags_callback")
    if not dropdown_ids or not new_tag_ids:
        raise PreventUpdate

    # Find which input triggered the callback
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate

    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if not triggered_id:
        raise PreventUpdate

    # Parse the triggered ID to get the transaction ID
    triggered_id = json.loads(triggered_id)
    transaction_id = triggered_id['index']

    # Get the new tag values
    # Find the index of the dropdown that matches the transaction ID
    for i, id_dict in enumerate(dropdown_ids):
        if isinstance(id_dict, dict) and id_dict.get('index') == transaction_id:
            new_tags = new_tag_ids[i]
            break
    else:
        raise PreventUpdate

    # Update the tags in the database
    if update_transaction_tags(transaction_id, new_tags):
        # Reload and display the updated transactions with current sort
        df = load_transactions()
        df = df.sort(sort_state['column'], descending=not sort_state['ascending'])
        return df.to_dicts(), create_transaction_table(df, sort_state, filter_state, date_range_state)

    raise PreventUpdate

@callback(
    [Output('transactions-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True)],
    [Input({'type': 'note-input', 'index': dash.ALL}, 'value'),
     Input('sort-state', 'data'),
     Input('filter-state', 'data'),
     Input('date-range-state', 'data')],
    [State({'type': 'note-input', 'index': dash.ALL}, 'id')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
@debug_callback
def update_transaction_note_callback(note_values, note_ids, sort_state, filter_state, date_range_state):
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
    triggered_id = json.loads(triggered_id)
    transaction_id = triggered_id['index']

    # Get the new note value
    for i, id_dict in enumerate(note_ids):
        if isinstance(id_dict, dict) and id_dict.get('index') == transaction_id:
            new_note = note_values[i]
            break
    else:
        raise PreventUpdate

    # Update the note in the database
    if update_transaction_note(transaction_id, new_note):
        # Reload and display the updated transactions with current sort
        df = load_transactions()
        df = df.sort(sort_state['column'], descending=not sort_state['ascending'])
        return df.to_dicts(), create_transaction_table(df, sort_state, filter_state, date_range_state)

    raise PreventUpdate

def create_transaction_table(df, sort_state, filter_state, date_range_state):
    """Create an interactive transaction table with tag dropdowns."""
    if df.is_empty():
        return html.Div("No transaction found")

    # Get tag name to ID mapping
    tag_name_to_id = get_tag_name_to_id_mapping()

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
            html.Th("Data Source")
        ]))
    ]

    # Create table rows with tag dropdowns
    rows = []
    for row in df.iter_rows(named=True):
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
    [Output('transactions-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True),
     Output('filter-state', 'data', allow_duplicate=True)],
    [Input('description-filter', 'value'),
     Input('sort-state', 'data'),
     Input('date-range-state', 'data')],
    [State('filter-state', 'data')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
@debug_callback
def filter_transactions(search_text, sort_state, date_range_state, filter_state):
    # Update filter state
    filter_state = {'text': search_text or '', 'column': 'description'}

    # Load data with current sort and search
    df = load_transactions()

    # Apply search filter if text is provided
    if search_text:
        df = df.filter(pl.col('Description').str.contains(search_text, literal=True))

    # Apply sorting
    df = df.sort(sort_state['column'], descending=not sort_state['ascending'])

    return df.to_dicts(), create_transaction_table(df, sort_state, filter_state, date_range_state), filter_state

@callback(
    [Output('transactions-data', 'data', allow_duplicate=True),
     Output('transaction-table', 'children', allow_duplicate=True),
     Output('sort-state', 'data', allow_duplicate=True)],
    [Input('sort-date', 'n_clicks'),
     Input('sort-description', 'n_clicks'),
     Input('sort-amount', 'n_clicks'),
     Input('filter-state', 'data'),
     Input('date-range-state', 'data')],
    [State('sort-state', 'data')],
    prevent_initial_call=True,
    suppress_callback_exceptions=True
)
@debug_callback
def sort_table(n_date, n_desc, n_amount, current_sort, filter_state, date_range_state):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update, dash.no_update

    # Get the triggered input
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Map column names to their database counterparts
    column_map = {
        'sort-date': 'Date',
        'sort-description': 'Description',
        'sort-amount': 'Amount'
    }

    # Get the column to sort by
    sort_column = column_map.get(triggered_id)
    if not sort_column:
        return dash.no_update, dash.no_update, dash.no_update

    # If clicking the same column, toggle direction
    # Otherwise, sort ascending by default
    ascending = True
    if current_sort and current_sort['column'] == sort_column:
        ascending = not current_sort['ascending']

    # Update sort state
    sort_state = {'column': sort_column, 'ascending': ascending}

    # Load data and apply filters and sorting
    df = load_transactions()

    # Apply search filter if text is provided and filter_state exists
    if filter_state and isinstance(filter_state, dict) and filter_state.get('text'):
        df = df.filter(pl.col(filter_state['column']).str.contains(filter_state['text'], literal=True))

    # Apply sorting
    df = df.sort(sort_column, descending=not ascending)

    return df.to_dicts(), create_transaction_table(df, sort_state, filter_state, date_range_state), sort_state

@callback(
    Output("add-transaction-modal", "is_open"),
    [Input("add-transaction-btn", "n_clicks"),
     Input("cancel-transaction", "n_clicks"),
     Input("submit-transaction", "n_clicks")],
    [State("add-transaction-modal", "is_open")],
    prevent_initial_call=True
)
@debug_callback
def toggle_transaction_modal(n_add, n_cancel, n_submit, is_open):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if button_id in ["add-transaction-btn", "cancel-transaction"]:
        return not is_open
    return is_open

@callback(
    Output('transaction-count-plot', 'figure'),
    Input('transactions-data', 'data'),
    prevent_initial_call=True
)
@debug_callback
def update_transaction_count_plot(data):
    if not data:
        return go.Figure()

    # Convert data to DataFrame
    df = pl.DataFrame(data)
    df = df.with_columns(pl.col('Date').cast(pl.Datetime))

    # Group by date and count transactions
    daily_counts = df.group_by(pl.col('Date').dt.date()).agg(pl.count().alias('count'))
    daily_counts = daily_counts.with_columns(pl.col('Date').cast(pl.Datetime))

    # Create the figure
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=daily_counts['Date'].to_list(),
        y=daily_counts['count'].to_list(),
        name='Transactions per Day'
    ))

    # Update layout
    fig.update_layout(
        title='Transactions / Day',
        xaxis_title='Date',
        yaxis_title='Transactions',
        showlegend=False,
        height=300,
        margin=dict(l=20, r=20, t=40, b=20)
    )

    return fig

if __name__ == '__main__':
    app.run(debug=True)
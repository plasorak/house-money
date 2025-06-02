# Family Finance Dashboard

A Python Dash application for managing and visualizing family finances. This application allows you to:

- Import bank statements in CSV format
- Filter and ignore specific transactions
- View aggregated spending metrics
- Analyze spending patterns over time
- Categorize transactions

## Setup

1. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python app.py
```

4. Open your browser and navigate to `http://localhost:8050`

## CSV Format Requirements

The application expects CSV files with the following columns:
- Date
- Description
- Amount
- Category (optional)

## Features

- Monthly spending overview
- Category-wise expense breakdown
- Transaction filtering
- Interactive charts and graphs
- Data export capabilities
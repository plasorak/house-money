import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

def generate_sample_transactions(num_transactions=100, start_date=None, end_date=None):
    if start_date is None:
        start_date = datetime.now() - timedelta(days=365)
    if end_date is None:
        end_date = datetime.now()

    # Define categories and their typical transaction descriptions
    categories = {
        'Groceries': [
            'Walmart', 'Target', 'Whole Foods', 'Trader Joes', 'Kroger',
            'Costco', 'Safeway', 'Grocery Store', 'Supermarket'
        ],
        'Dining': [
            'Restaurant', 'Cafe', 'Coffee Shop', 'Fast Food', 'Pizza Place',
            'Food Delivery', 'Takeout', 'Dinner', 'Lunch', 'Breakfast'
        ],
        'Transportation': [
            'Gas Station', 'Uber', 'Lyft', 'Taxi', 'Public Transit',
            'Parking', 'Car Maintenance', 'Auto Parts', 'Oil Change'
        ],
        'Shopping': [
            'Amazon', 'Online Store', 'Department Store', 'Clothing Store',
            'Electronics Store', 'Home Goods', 'Furniture Store'
        ],
        'Entertainment': [
            'Movie Theater', 'Streaming Service', 'Concert', 'Theater',
            'Sports Event', 'Gym', 'Fitness Center', 'Hobby Store'
        ],
        'Utilities': [
            'Electric Bill', 'Water Bill', 'Internet', 'Phone Bill',
            'Cable TV', 'Gas Bill', 'Utility Payment'
        ],
        'Housing': [
            'Rent', 'Mortgage', 'Home Repair', 'Home Improvement',
            'Property Tax', 'Home Insurance'
        ],
        'Healthcare': [
            'Doctor Visit', 'Pharmacy', 'Medical Supplies', 'Health Insurance',
            'Dental', 'Vision', 'Medical Bill'
        ]
    }

    # Generate random dates
    date_range = (end_date - start_date).days
    dates = [start_date + timedelta(days=random.randint(0, date_range)) for _ in range(num_transactions)]
    dates.sort()

    # Generate transactions
    transactions = []
    for date in dates:
        # Select a random category
        category = random.choice(list(categories.keys()))
        # Select a random description from the category
        description = random.choice(categories[category])

        # Generate amount based on category
        if category == 'Groceries':
            amount = round(random.uniform(20, 200), 2)
        elif category == 'Dining':
            amount = round(random.uniform(10, 100), 2)
        elif category == 'Transportation':
            amount = round(random.uniform(15, 150), 2)
        elif category == 'Shopping':
            amount = round(random.uniform(25, 300), 2)
        elif category == 'Entertainment':
            amount = round(random.uniform(10, 200), 2)
        elif category == 'Utilities':
            amount = round(random.uniform(50, 300), 2)
        elif category == 'Housing':
            amount = round(random.uniform(500, 3000), 2)
        elif category == 'Healthcare':
            amount = round(random.uniform(20, 500), 2)

        transactions.append({
            'Date': date.strftime('%Y-%m-%d'),
            'Description': description,
            'Amount': amount,
            'Category': category
        })

    # Create DataFrame
    df = pd.DataFrame(transactions)

    # Save to CSV
    df.to_csv('sample_transactions.csv', index=False)
    print(f"Generated {num_transactions} sample transactions in sample_transactions.csv")
    return df

if __name__ == "__main__":
    # Generate transactions for the last year
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    df = generate_sample_transactions(num_transactions=200, start_date=start_date, end_date=end_date)

    # Print some statistics
    print("\nSample Statistics:")
    print(f"Date Range: {df['Date'].min()} to {df['Date'].max()}")
    print("\nTotal Spending by Category:")
    print(df.groupby('Category')['Amount'].sum().sort_values(ascending=False))
    print(f"\nTotal Transactions: ${df['Amount'].sum():,.2f}")
import os
from database import DB_PATH, reset_database, init_db
import click
import sqlite3
from rich.console import Console
from rich.prompt import Confirm

console = Console()

@click.group()
def cli():
    """Database management utility for House Money"""
    pass

@cli.command()
@click.argument('table', type=click.Choice(['all', 'transactions', 'tags', 'uploaded_files', 'transaction_tags']))
def init(table):
    """Initialize a new database or specific table"""
    if os.path.exists(DB_PATH):
        if not Confirm.ask(f"Database already exists at {DB_PATH}. Do you want to reinitialize the {table} table(s)?"):
            return
    init_db(table)
    console.print(f"[green]Table(s) initialized at {DB_PATH}[/green]")

@cli.command()
@click.argument('table', type=click.Choice(['all', 'transactions', 'tags', 'uploaded_files', 'transaction_tags']))
def reset(table):
    """Reset specific table(s) by dropping and recreating them"""
    if not os.path.exists(DB_PATH):
        console.print(f"[yellow]Database does not exist at {DB_PATH}[/yellow]")
        return

    if not Confirm.ask(f"Are you sure you want to reset the {table} table(s) at {DB_PATH}? This will delete all data in those tables!"):
        return

    reset_database(table)
    console.print(f"[green]Table(s) reset at {DB_PATH}[/green]")

@cli.command()
@click.argument('table', type=click.Choice(['all', 'transactions', 'tags', 'uploaded_files', 'transaction_tags']))
def delete(table):
    """Delete specific table(s) from the database"""
    if not os.path.exists(DB_PATH):
        console.print(f"[yellow]Database does not exist at {DB_PATH}[/yellow]")
        return

    if not Confirm.ask(f"Are you sure you want to delete the {table} table(s) from {DB_PATH}?"):
        return

    # Connect to database and drop the specified table(s)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if table == 'all':
        tables = ['transactions', 'tags', 'uploaded_files', 'transaction_tags']
    else:
        tables = [table]

    for t in tables:
        c.execute(f'DROP TABLE IF EXISTS {t}')

    conn.commit()
    conn.close()
    console.print(f"[green]Table(s) deleted from {DB_PATH}[/green]")

if __name__ == '__main__':
    cli()
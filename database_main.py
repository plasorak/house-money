import os
from database import DB_PATH, reset_database, init_db
import click
import rich
from rich.console import Console
from rich.prompt import Confirm

console = Console()

@click.group()
def cli():
    """Database management utility for House Money"""
    pass

@cli.command('delete')
def delete_db():
    """Delete the database file"""
    if not os.path.exists(DB_PATH):
        console.print(f"Database file ({DB_PATH}) does not exist. No need to do anything...")
        return

    # Ask for confirmation
    if not Confirm.ask(f"WARNING: This will delete ALL data in {DB_PATH}!\nAre you sure you want to continue?"):
        console.print("Operation cancelled.")
        return

    try:
        os.remove(DB_PATH)
        console.print("[green]Database file has been deleted successfully![/green]")
    except Exception as e:
        console.print(f"[red]Error deleting database: {e}[/red]")

@cli.command('reset')
def reset_db():
    """Reset the database (drop all tables and recreate)"""
    if not os.path.exists(DB_PATH):
        console.print("Database file does not exist. Creating new database...")
        init_db()
        console.print("[green]Database has been created successfully![/green]")
        return

    # Ask for confirmation
    if not Confirm.ask(f"WARNING: This will delete ALL data in {DB_PATH}!\nAre you sure you want to continue?"):
        console.print("Operation cancelled.")
        return

    try:
        reset_database()
        console.print("[green]Database has been reset successfully![/green]")
    except Exception as e:
        console.print(f"[red]Error resetting database: {e}[/red]")

@cli.command('create')
def create_db():
    """Create a new database"""
    if os.path.exists(DB_PATH):
        if not Confirm.ask(f"Database file already exists at {DB_PATH}.\nDo you want to overwrite it?"):
            console.print("Operation cancelled.")
            return

    try:
        init_db()
        console.print("[green]Database has been created successfully![/green]")
    except Exception as e:
        console.print(f"[red]Error creating database: {e}[/red]")

if __name__ == '__main__':
    cli()
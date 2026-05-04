"""
Database schema validation utilities

Provides functions to validate database schema compatibility
and display results with rich formatting.
"""

import click
import sys
from typing import Optional, Tuple
from utils.database.schema_checker import analyze_database_schema


def display_schema_validation_result(
    is_in_sync: bool,
    error_message: str,
    differences_count: int,
    is_connection_error: bool,
    context: str = "COMMAND",  # "COMMAND" or "API"
    database_url: Optional[str] = None,
    verbose: bool = False
) -> None:
    """
    Display schema validation results with rich formatting.
    
    Args:
        is_in_sync: Whether schema is in sync
        error_message: Error message if not in sync
        differences_count: Number of differences found
        is_connection_error: Whether this is a connection error
        context: Context for the validation ("COMMAND" or "API")
        database_url: Optional database URL override
        verbose: Whether to show success message
    """
    if is_connection_error:
        click.echo("")
        click.echo("=" * 60)
        click.echo(click.style(f"🚫 {context} FAILED - DATABASE CONNECTION ERROR", fg='red', bold=True))
        click.echo("=" * 60)
        click.echo("")
        click.echo("Unable to connect to the database.")
        click.echo("")
        click.echo(error_message)
        click.echo("")
        click.echo("🔧 To fix this issue:")
        click.echo("   1. Check your DATABASE_URL environment variable")
        click.echo("   2. Ensure the database server is running")
        click.echo("   3. Verify network connectivity")
        click.echo("   4. Check authentication credentials")
        click.echo("")
        click.echo("=" * 60)
        click.echo("")
        if context == "API":
            click.echo(click.style("   Action: Fix connection issues above and restart API", fg='red'))
        else:
            click.echo(click.style("   Action: Fix connection issues above and retry", fg='red'))
        click.echo("")
        sys.exit(1)
    
    elif not is_in_sync:
        click.echo("")
        click.echo("=" * 60)
        click.echo(click.style(f"🚫 {context} FAILED - DATABASE SCHEMA MISMATCH", fg='red', bold=True))
        click.echo("=" * 60)
        click.echo("")
        if context == "API":
            click.echo("The database schema is not compatible with the current API version.")
        else:
            click.echo("The database schema is not compatible with the current CLI version.")
        click.echo("")
        click.echo(error_message)
        click.echo("")
        
        # Build remediation commands with same args as current command
        if database_url:
            base_sync_cmd = f"python cli.py --database-url '{database_url}' system db sync --apply"
            interactive_sync_cmd = f"python cli.py --database-url '{database_url}' system db sync --apply --interactive"
        else:
            base_sync_cmd = "python cli.py system db sync --apply"
            interactive_sync_cmd = "python cli.py system db sync --apply --interactive"
        
        click.echo("🔧 To fix this issue:")
        click.echo(f"   1. Run: {base_sync_cmd}")
        if context == "API":
            if database_url:
                restart_cmd = f"python api_main.py --database-url '{database_url}'"
            else:
                restart_cmd = "python api_main.py"
            click.echo(f"   2. Then restart: {restart_cmd}")
        else:
            click.echo("   2. Then retry your original command")
        click.echo("")
        click.echo("💡 For step-by-step control:")
        click.echo(f"   {interactive_sync_cmd}")
        click.echo("")
        click.echo("=" * 60)
        click.echo("")
        click.echo(click.style(f"❌ {context} ABORTED", fg='red', bold=True))
        click.echo(click.style(f"   Reason: Database schema has {differences_count} incompatible differences", fg='red'))
        if context == "API":
            click.echo(click.style("   Action: Fix schema issues above and restart API", fg='red'))
        else:
            click.echo(click.style("   Action: Fix schema issues above and retry", fg='red'))
        click.echo("")
        sys.exit(1)
    
    elif verbose:
        # Show success message only if verbose is enabled
        click.echo("")
        click.echo("=" * 60)
        click.echo(click.style("✅ DATABASE SCHEMA VALIDATED", fg='green', bold=True))
        click.echo(click.style("   Status: All database tables and columns are properly synchronized", fg='green'))
        if context == "API":
            click.echo(click.style("   Action: Continuing with API server bootstrap...", fg='green'))
        else:
            click.echo(click.style("   Action: Continuing with command execution...", fg='green'))
        click.echo("=" * 60)
        click.echo("")


def validate_database_schema(
    context: str = "COMMAND",
    database_url: Optional[str] = None,
    verbose: bool = False
) -> Tuple[bool, str, int, bool]:
    """
    Validate database schema and display results with rich formatting.
    
    Centralized validation function used by both API and CLI components.
    Provides consistent validation logic with context-appropriate error messages.
    
    Args:
        context: Context for the validation ("COMMAND" or "API")
        database_url: Optional database URL override
        verbose: Whether to show success message
    
    Returns:
        Tuple of (is_in_sync, error_message, differences_count, is_connection_error)
    """
    from utils.database.schema_checker import validate_schema_centralized
    
    # Use centralized schema validation logic
    is_in_sync, error_message, differences_count, is_connection_error = validate_schema_centralized()
    
    # Display results with rich formatting
    display_schema_validation_result(
        is_in_sync=is_in_sync,
        error_message=error_message,
        differences_count=differences_count,
        is_connection_error=is_connection_error,
        context=context,
        database_url=database_url,
        verbose=verbose
    )
    
    return is_in_sync, error_message, differences_count, is_connection_error


 
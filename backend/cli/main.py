#!/usr/bin/env python3
"""
Phoveus - CLI Interface

Command-line interface for internal administrative tasks.
Uses the same hexagonal architecture as the API for consistency.
"""

import click
import sys
import logging
from pathlib import Path
from typing import Optional

# Add project root to path for imports early
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import config functions early
from config import settings, set_database_url, clear_database_url_override
from utils.debug import colorize
from cli.logging_config import configure_logging
from cli.services import get_services

# Configure logging immediately
configure_logging()

logger = logging.getLogger(__name__)


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--database-url', help='Override PHOVEU_BACKEND_DATABASE_URL for this command')
@click.pass_context
def cli(ctx, verbose, database_url):
    """
    Phoveus CLI
    
    Internal command-line tools for administrative tasks.
    Uses hexagonal architecture for clean separation of concerns.
    """
    # Ensure context exists
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['auth_context'] = None  # Will be set during authentication
    
    # Set database URL override if provided (do this early)
    if database_url:
        set_database_url(database_url)
        if verbose:
            click.echo(f"🔧 Using database URL: {database_url}")
    
    if verbose:
        click.echo("🔧 Initializing services...")
    
    # Initialize services with database URL override
    try:
        ctx.obj['services'] = get_services(database_url, initialize_db=False)  # Default to no initialization
        if verbose:
            click.echo("✅ Services initialized successfully")
    except Exception as e:
        click.echo(f"❌ Failed to initialize services: {e}", err=True)
        sys.exit(1)
    
    # Database schema pre-flight check (skip for system commands)
    if not ctx.invoked_subcommand or ctx.invoked_subcommand != 'system':
        try:
            from utils.database.schema_validation import validate_database_schema
            
            if verbose:
                click.echo("🔍 Checking database schema...")
            
            # Use shared validation utility with rich formatting
            validate_database_schema(
                context="COMMAND",
                database_url=database_url,
                verbose=verbose
            )
                
        except Exception as e:
            click.echo(f"❌ Error checking database schema: {e}")
            sys.exit(1)


# Import command groups
# NOTE: Imported here to avoid circular imports if commands import cli.main
try:
    from cli.commands import auth, rate_limit, system, support
    from cli.commands.crud import crud
    from cli.commands.notifications import notifications

    # Register command groups
    cli.add_command(auth.auth)
    cli.add_command(crud)
    cli.add_command(rate_limit.rate_limit)
    cli.add_command(system.system)
    cli.add_command(support.support)
    cli.add_command(notifications)
except ImportError as e:
    pass


if __name__ == '__main__':
    cli()
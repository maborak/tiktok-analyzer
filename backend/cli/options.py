import click
import functools
from cli.services import get_services

def common_options(f):
    """Decorator to add common global options to subcommands"""
    
    @click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
    @click.option('--database-url', help='Override PHOVEU_BACKEND_DATABASE_URL for this command')
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        verbose = kwargs.get('verbose')
        database_url = kwargs.get('database_url')
        
        # Update context if these were provided at subcommand level
        if verbose:
            ctx.obj['verbose'] = verbose
        
        # If database-url provided at subcommand level, re-initialize services
        if database_url:
            from config import set_database_url
            set_database_url(database_url)
            if ctx.obj.get('verbose'):
                click.echo(f"🔧 Overriding database URL from subcommand: {database_url}")
            
            # Re-initialize services with the new URL
            ctx.obj['services'] = get_services(database_url, force_refresh=True)
            
        return f(ctx, *args, **kwargs)
    
    return wrapper

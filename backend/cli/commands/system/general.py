#!/usr/bin/env python3
"""
General System Commands

Environment configuration and system status commands.
"""

import click
import os
from cli.session import session_manager


def require_admin_auth(ctx):
    """Check if user has admin authentication"""
    if not session_manager.is_authenticated():
        click.echo("❌ Authentication required. Use 'auth login' first.", err=True)
        return False
    
    if not session_manager.is_admin():
        click.echo("❌ Admin privileges required.", err=True)
        return False
    
    return True


@click.group()
def system():
    """System management and configuration commands"""
    pass


# Import and add db commands to system group
from .db import db
system.add_command(db)

# Import and add network commands to system group
from .network import network
system.add_command(network)

# Import and add http-engine commands to system group
from .http_engine import http_engine
system.add_command(http_engine)


@system.command()
@click.pass_context
def env(ctx):
    """
    Show environment configuration
    
    Display all environment variables and configuration settings
    used by the application.
    """
    if not require_admin_auth(ctx):
        return 1
    
    click.echo("🔧 Environment Configuration")
    click.echo("=" * 50)
    
    # Get all environment variables
    env_vars = dict(os.environ)
    
    # Sort by key for better readability
    sorted_vars = sorted(env_vars.items())
    
    # Group by category
    database_vars = []
    server_vars = []
    auth_vars = []
    monitoring_vars = []
    other_vars = []
    
    for key, value in sorted_vars:
        if key.startswith(('PHOVEU_BACKEND_DATABASE_', 'PHOVEU_BACKEND_DB_')):
            database_vars.append((key, value))
        elif key.startswith(('PHOVEU_BACKEND_UVI_', 'PHOVEU_BACKEND_HOST', 'PHOVEU_BACKEND_PORT', 'PHOVEU_BACKEND_WORKERS')):
            server_vars.append((key, value))
        elif key.startswith(('PHOVEU_BACKEND_JWT_', 'PHOVEU_BACKEND_AUTH_', 'PHOVEU_BACKEND_PASSWORD_')):
            auth_vars.append((key, value))
        elif key.startswith(('PHOVEU_BACKEND_MONITOR_', 'PHOVEU_BACKEND_RATE_LIMIT_')):
            monitoring_vars.append((key, value))
        else:
            other_vars.append((key, value))
    
    # Print database variables
    if database_vars:
        click.echo("🗃️  Database Configuration:")
        for key, value in database_vars:
            # Mask passwords in connection strings
            if 'password' in key.lower() or 'pass' in key.lower():
                if '://' in value:
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(value)
                        if parsed.password:
                            masked_value = value.replace(parsed.password, "***")
                        else:
                            masked_value = value
                    except:
                        masked_value = "***"
                else:
                    masked_value = "***"
            else:
                masked_value = value
            click.echo(f"  {key:<25} = {masked_value}")
        click.echo()
    
    # Print server variables
    if server_vars:
        click.echo("🌐 Server Configuration:")
        for key, value in server_vars:
            click.echo(f"  {key:<25} = {value}")
        click.echo()
    
    # Print auth variables
    if auth_vars:
        click.echo("🔐 Authentication Configuration:")
        for key, value in auth_vars:
            if 'password' in key.lower() or 'pass' in key.lower() or 'secret' in key.lower():
                click.echo(f"  {key:<25} = ***")
            else:
                click.echo(f"  {key:<25} = {value}")
        click.echo()
    
    # Print monitoring variables
    if monitoring_vars:
        click.echo("📊 Monitoring Configuration:")
        for key, value in monitoring_vars:
            click.echo(f"  {key:<25} = {value}")
        click.echo()
    
    # Print other variables
    if other_vars:
        click.echo("🔧 Other Configuration:")
        for key, value in other_vars:
            click.echo(f"  {key:<25} = {value}")
        click.echo()
    
    # Summary
    total_vars = len(env_vars)
    click.echo(f"📊 Summary: {total_vars} environment variables found")
    
    return 0


@system.command()
@click.pass_context
def system_status(ctx):
    """
    Show system status
    
    Display comprehensive system status including database health,
    service status, and performance metrics.
    """
    if not require_admin_auth(ctx):
        return 1
    
    click.echo("📊 System Status")
    click.echo("=" * 50)
    
    try:
        services = ctx.obj['services']
        
        # Database status
        try:
            cache_stats = services.data_persistence_adapter.get_cache_stats()
            click.echo("🗃️  Database Status:")
            click.echo(f"  • Total Products: {cache_stats['total_products']}")
            click.echo(f"  • Available Products: {cache_stats['available_products']}")
            click.echo(f"  • Recent Checks (24h): {cache_stats['recent_checks_24h']}")
            click.echo(f"  • Total Checks: {cache_stats['total_checks']}")
        except Exception as e:
            click.echo(f"  ❌ Database Error: {e}")
        
        # User status
        try:
            users = services.auth_adapter.get_all_users()
            if users:
                admin_count = len([u for u in users if u.role.value == 'admin'])
                user_count = len([u for u in users if u.role.value == 'user'])
                active_count = len([u for u in users if u.is_active])
                
                click.echo(f"\n👥 User Status:")
                click.echo(f"  • Total Users: {len(users)}")
                click.echo(f"  • Admin Users: {admin_count}")
                click.echo(f"  • Regular Users: {user_count}")
                click.echo(f"  • Active Users: {active_count}")
        except Exception as e:
            click.echo(f"  ❌ User Status Error: {e}")
        
        # System info
        try:
            import psutil
            click.echo(f"\n💻 System Information:")
            click.echo(f"  • CPU Usage: {psutil.cpu_percent()}%")
            click.echo(f"  • Memory Usage: {psutil.virtual_memory().percent}%")
            click.echo(f"  • Disk Usage: {psutil.disk_usage('/').percent}%")
        except ImportError:
            click.echo("  ⚠️  psutil not available for system metrics")
        except Exception as e:
            click.echo(f"  ❌ System Metrics Error: {e}")
        
        return 0
        
    except Exception as e:
        click.echo(f"❌ Error getting system status: {e}", err=True)
        return 1


 
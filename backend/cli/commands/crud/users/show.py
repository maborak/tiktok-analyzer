"""
User show command

Shows detailed information about a specific user including account details and settings.
"""

import click
from cli.auth_decorators import require_admin_auth


@click.command()
@click.argument('user_id', type=int)
@click.pass_context
def show(ctx, user_id):
    """
    Show detailed information about a specific user
    
    Display comprehensive user information including
    sessions, API keys, and account details.
    """
    
    services = ctx.obj['services']
    
    click.echo(f"👤 User Details: {user_id}")
    click.echo("=" * 50)
    
    try:
        # Get user
        user = services.auth_adapter.get_user_by_id(user_id)
        
        if not user:
            click.echo(f"❌ User {user_id} not found")
            return 1
        
        # Display user information
        click.echo(f"🆔 User ID: {user.id}")
        click.echo(f"👤 Username: {user.username}")
        click.echo(f"📧 Email: {user.email}")
        click.echo(f"📝 Full Name: {user.full_name}")
        click.echo(f"🔑 Role: {user.role.value}")
        click.echo(f"🔒 Active: {user.is_active}")
        click.echo(f"✅ Verified: {user.is_verified}")
        click.echo(f"📅 Created: {user.created_at}")
        click.echo(f"📅 Last Login: {user.last_login}")
        click.echo(f"📊 Max Products: {user.max_products}")
        click.echo(f"⚡ API Rate Limit: {user.api_rate_limit}")
        
        if user.failed_login_attempts > 0:
            click.echo(f"⚠️  Failed Login Attempts: {user.failed_login_attempts}")
        
        if user.locked_until:
            click.echo(f"🔒 Locked Until: {user.locked_until}")
        
        return 0
        
    except Exception as e:
        click.echo(f"❌ Error showing user: {e}", err=True)
        return 1 
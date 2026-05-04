"""
User list command

Lists all users in the database with filtering and formatting options.
"""

import click
from cli.auth_decorators import require_admin_auth


@click.command()
@require_admin_auth()
@click.option('--limit', '-l', type=int, default=50, help='Number of users to show')
@click.option('--role', '-r', type=click.Choice(['user', 'admin', 'moderator']), help='Filter by user role')
@click.option('--active', '-a', is_flag=True, help='Show only active users')
@click.pass_context
def list(ctx, limit, role, active):
    """
    List all users in the database
    
    Display user accounts with their roles, status, and basic information.
    """
    
    services = ctx.obj['services']
    
    click.echo("👥 User List")
    click.echo("=" * 40)
    
    try:
        # Get all users
        users = services.auth_adapter.get_all_users()
        
        if not users:
            click.echo("❌ No users found")
            return 0
        
        # Apply filters
        if role:
            users = [u for u in users if u.role.value == role]
        
        if active:
            users = [u for u in users if u.is_active]
        
        # Apply limit
        if limit and limit < len(users):
            users = users[:limit]
        
        click.echo(f"📊 Found {len(users)} users")
        click.echo("\nID\tUsername\t\tEmail\t\t\tRole\t\tActive")
        click.echo("-" * 100)
        
        for user in users:
            status = "✅" if user.is_active else "❌"
            click.echo(f"{user.id}\t{user.username:<15}\t{user.email:<20}\t{user.role.value:<10}\t{status}")
        
        return 0
        
    except Exception as e:
        click.echo(f"❌ Error listing users: {e}", err=True)
        return 1 
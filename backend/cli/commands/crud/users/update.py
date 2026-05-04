"""
User update command

Updates user account settings including role, status, and limits.
"""

import click
from cli.auth_decorators import require_admin_auth
from domain.entities.auth_models import UserRole


@click.command()
@click.argument('user_id', type=int)
@click.option('--role', '-r', type=click.Choice(['user', 'admin', 'moderator']), help='New user role')
@click.option('--active', '-a', type=bool, help='Set user active status')
@click.option('--max-products', '-m', type=int, help='Set max products limit')
@click.option('--rate-limit', '-l', type=int, help='Set API rate limit')
@click.pass_context
def update(ctx, user_id, role, active, max_products, rate_limit):
    """
    Update user account settings
    
    Modify user role, status, limits, and other account settings.
    """
    
    services = ctx.obj['services']
    
    click.echo(f"✏️  Updating User: {user_id}")
    click.echo("=" * 40)
    
    try:
        # Get current user
        user = services.auth_adapter.get_user_by_id(user_id)
        
        if not user:
            click.echo(f"❌ User {user_id} not found")
            return 1
        
        # Show current values
        click.echo(f"Current values:")
        click.echo(f"  Role: {user.role.value}")
        click.echo(f"  Active: {user.is_active}")
        click.echo(f"  Max Products: {user.max_products}")
        click.echo(f"  Rate Limit: {user.api_rate_limit}")
        
        # Build updates dictionary
        updates = {}
        if role:
            updates["role"] = UserRole(role)
            click.echo(f"  → Role: {role}")
        
        if active is not None:
            updates["is_active"] = active
            click.echo(f"  → Active: {active}")
        
        if max_products is not None:
            updates["max_products"] = max_products
            click.echo(f"  → Max Products: {max_products}")
        
        if rate_limit is not None:
            updates["api_rate_limit"] = rate_limit
            click.echo(f"  → Rate Limit: {rate_limit}")
        
        # Save changes
        if not updates:
            click.echo("⚠️  No changes specified")
            return 0
        
        success = services.auth_adapter.update_user(user_id, updates)
        
        if success:
            click.echo(f"✅ User {user_id} updated successfully")
            return 0
        else:
            click.echo(f"❌ Failed to update user {user_id}")
            return 1
            
    except Exception as e:
        click.echo(f"❌ Error updating user: {e}", err=True)
        return 1 
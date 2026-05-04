"""
User delete command

Deletes user accounts and removes all associated data.
"""

import click
from cli.auth_decorators import require_admin_auth


@click.command()
@click.argument('user_id', type=int)
@click.pass_context
def delete(ctx, user_id):
    """
    Delete a user account
    
    Remove a user account and all associated data including
    sessions, API keys, and product associations.
    """
    if not require_admin_auth(ctx):
        return 1
    
    services = ctx.obj['services']
    
    # Confirm deletion
    if not click.confirm(f"Are you sure you want to delete user {user_id}?"):
        click.echo("❌ Deletion cancelled")
        return 0
    
    click.echo(f"🗑️  Deleting User: {user_id}")
    click.echo("=" * 40)
    
    try:
        # Get user first to show what we're deleting
        user = services.auth_adapter.get_user_by_id(user_id)
        if user:
            click.echo(f"👤 Username: {user.username}")
            click.echo(f"📧 Email: {user.email}")
            click.echo(f"🔑 Role: {user.role.value}")
        
        # Delete user
        success = services.auth_adapter.delete_user(user_id)
        
        if success:
            click.echo(f"✅ User {user_id} deleted successfully")
            return 0
        else:
            click.echo(f"❌ Failed to delete user {user_id}")
            return 1
            
    except Exception as e:
        click.echo(f"❌ Error deleting user: {e}", err=True)
        return 1 
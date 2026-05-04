"""
User management operations

This module provides commands for managing users including listing, showing, updating, and deleting users.
"""

import click
from cli.auth_decorators import require_admin_auth


@click.group()
def users():
    """User management operations"""
    pass


# Import and register user commands
from .list import list
from .show import show
from .update import update
from .delete import delete

users.add_command(list)
users.add_command(show)
users.add_command(update)
users.add_command(delete) 
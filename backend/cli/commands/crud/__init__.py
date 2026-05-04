"""
CRUD operations for admin data management

This module provides command-line tools for managing products, users, and system data.
Uses hexagonal architecture for clean separation of concerns.
"""

import click
from cli.auth_decorators import require_admin_auth


@click.group()
def crud():
    """CRUD operations for admin data management"""
    pass


# Import and register command groups
from .users import users

crud.add_command(users)
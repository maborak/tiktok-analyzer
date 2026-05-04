#!/usr/bin/env python3
"""
CLI Authentication Decorators

Centralized authentication system for CLI commands.
Provides decorators to control access levels for different commands.
"""

import click
from functools import wraps
from cli.session import session_manager


def require_auth(admin_only: bool = False):
    """
    Decorator to require authentication for CLI commands
    
    Args:
        admin_only: If True, requires admin privileges. If False, any authenticated user is allowed.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(ctx, *args, **kwargs):
            # Check if user is authenticated
            if not session_manager.is_authenticated():
                click.echo("❌ Authentication required", err=True)
                click.echo("💡 Use 'auth login' to authenticate", err=True)
                return 1
            
            # If admin_only is True, check for admin privileges
            if admin_only and not session_manager.is_admin():
                click.echo("❌ Admin privileges required", err=True)
                click.echo("💡 Use 'auth login' to authenticate as admin", err=True)
                return 1
            
            # Authentication passed, proceed with command
            return func(ctx, *args, **kwargs)
        
        return wrapper
    return decorator


def require_admin_auth():
    """Decorator to require admin authentication"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if user is authenticated
            if not session_manager.is_authenticated():
                click.echo("❌ Authentication required", err=True)
                click.echo("💡 Use 'auth login' to authenticate", err=True)
                return 1
            
            # Check for admin privileges
            if not session_manager.is_admin():
                click.echo("❌ Admin privileges required", err=True)
                click.echo("💡 Use 'auth login' to authenticate as admin", err=True)
                return 1
            
            # Authentication passed, proceed with command
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_user_auth():
    """Decorator to require user authentication (any authenticated user)"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if user is authenticated
            if not session_manager.is_authenticated():
                click.echo("❌ Authentication required", err=True)
                click.echo("💡 Use 'auth login' to authenticate", err=True)
                return 1
            
            # Authentication passed, proceed with command
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def optional_auth():
    """
    Decorator for commands that work with or without authentication
    Provides user context if available, but doesn't require it.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Add auth context to ctx.obj if available
            if session_manager.is_authenticated():
                auth_context = session_manager.get_auth_context()
                # Get ctx from args
                ctx = args[0] if args else None
                if ctx and hasattr(ctx, 'obj'):
                    if not hasattr(ctx.obj, 'auth_context'):
                        ctx.obj['auth_context'] = auth_context
                    if not hasattr(ctx.obj, 'user_id'):
                        ctx.obj['user_id'] = auth_context.get('user_id')
                    if not hasattr(ctx.obj, 'username'):
                        ctx.obj['username'] = auth_context.get('username')
                    if not hasattr(ctx.obj, 'role'):
                        ctx.obj['role'] = auth_context.get('role')
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def no_auth():
    """
    Decorator for commands that explicitly don't require authentication
    Useful for system/bootstrap commands that need to work before auth is set up.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # No authentication check, proceed directly
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


 
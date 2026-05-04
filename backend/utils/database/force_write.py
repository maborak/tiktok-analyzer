"""
Database Consistency Decorators

Decorators to explicitly control database connection routing for specific routes.
These decorators override the default routing behavior based on DB_USE_REPLICA_ENGINE setting.

- @require_write_db: Forces write connection (overrides default routing)
- @require_read_db: Forces read connection (overrides default routing)
- with consistency_context("read"): Forces read connection in a block

Note: By default, ALL operations route to write. Only decorators or context managers can override this.
"""

from functools import wraps
from contextvars import ContextVar
from typing import Callable, Optional
from contextlib import contextmanager
import inspect

# Context variables to track connection preference for current request
_force_write_context: ContextVar[bool] = ContextVar('force_write', default=False)
_force_read_context: ContextVar[bool] = ContextVar('force_read', default=False)


def get_db_consistency_mode() -> Optional[str]:
    """
    Get the database consistency mode for the current request context.
    
    Returns:
        "write" if write mode is forced
        "read" if read mode is forced
        None if no preference (use default routing)
    """
    if _force_write_context.get():
        return "write"
    elif _force_read_context.get():
        return "read"
    return None


@contextmanager
def consistency_context(mode: str = "read"):
    """
    Context manager to force database consistency mode for a block of code.
    
    Args:
        mode: "read" or "write"
        
    Usage:
        with consistency_context("read"):
            # All DB operations here will use read replica
            user = session.query(User).first()
    """
    token = None
    if mode == "write":
        token = _force_write_context.set(True)
    elif mode == "read":
        token = _force_read_context.set(True)
        
    try:
        yield
    finally:
        if token:
            if mode == "write":
                _force_write_context.reset(token)
            elif mode == "read":
                _force_read_context.reset(token)


def require_write_db(func: Callable) -> Callable:
    """
    Decorator to force all database operations in a route to use write connection.
    
    This decorator overrides the default routing behavior:
    - If DB_USE_REPLICA_ENGINE=true: Forces write connection (avoids replication lag)
    - If DB_USE_REPLICA_ENGINE=false: Still uses write connection (default behavior)
    
    Use this decorator for routes that:
    - Create or modify authentication data (register, login, password change)
    - Need to read immediately after writing
    - Require strong consistency
    
    Example:
        @router.post("/register")
        @require_write_db
        async def register(...):
            # All database operations here will use write connection
            ...
    
    Args:
        func: The route function to decorate
    
    Returns:
        Decorated function that forces write mode
    """
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Set context variable to force write mode
            token = _force_write_context.set(True)
            try:
                # Execute the route function
                result = await func(*args, **kwargs)
                return result
            finally:
                # Reset context variable
                _force_write_context.reset(token)
        return async_wrapper
    else:
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Set context variable to force write mode
            token = _force_write_context.set(True)
            try:
                # Execute the route function
                result = func(*args, **kwargs)
                return result
            finally:
                # Reset context variable
                _force_write_context.reset(token)
        return sync_wrapper


def require_read_db(func: Callable) -> Callable:
    """
    Decorator to force all database operations in a route to use read connection.
    
    This decorator overrides the default routing behavior:
    - If DB_USE_REPLICA_ENGINE=true: Forces read connection (uses replica)
    - If DB_USE_REPLICA_ENGINE=false: Uses write engine (same connection, but respects decorator intent)
    
    Use this decorator for routes that:
    - Only read data (no writes)
    - Can tolerate eventual consistency
    - Want to offload read traffic to replicas
    
    Example:
        @router.get("/products")
        @require_read_db
        async def list_products(...):
            # All database operations here will use read connection
            ...
    
    Args:
        func: The route function to decorate
    
    Returns:
        Decorated function that forces read mode
    """
    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Set context variable to force read mode
            token = _force_read_context.set(True)
            try:
                # Execute the route function
                result = await func(*args, **kwargs)
                return result
            finally:
                # Reset context variable
                _force_read_context.reset(token)
        return async_wrapper
    else:
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Set context variable to force read mode
            token = _force_read_context.set(True)
            try:
                # Execute the route function
                result = func(*args, **kwargs)
                return result
            finally:
                # Reset context variable
                _force_read_context.reset(token)
        return sync_wrapper

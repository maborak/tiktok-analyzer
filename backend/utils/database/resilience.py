"""
Database resilience utilities.

Provides decorators and helpers for handling database connection errors
and implementing retry logic for robust persistence operations.
"""

import time
import logging
from functools import wraps
from typing import Callable, TypeVar, Any
from sqlalchemy.exc import OperationalError, DisconnectionError

logger = logging.getLogger(__name__)

T = TypeVar('T')

def is_connection_error(e: Exception) -> bool:
    """
    Check if the exception is a database connection error.
    
    Args:
        e: The exception to check
        
    Returns:
        True if it's a connection error, False otherwise
    """
    msg = str(e).lower()
    return (
        isinstance(e, (OperationalError, DisconnectionError)) or
        "connection closed" in msg or
        "cursor already closed" in msg or
        "packet sequence number wrong" in msg or
        "connection unexpectedly" in msg or
        "connection refused" in msg or
        "server closed the connection" in msg
    )

def retry_db_operation(max_retries: int = 3, initial_delay: float = 0.1):
    """
    Decorator to retry database operations on connection errors.
    
    Automatically resets the database connection pool on failure before retrying.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds (exponential backoff)
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # Only retry on connection errors
                    if not is_connection_error(e):
                        raise
                    
                    # If this is the last attempt, don't retry
                    if attempt == max_retries - 1:
                        logger.error(f"DB operation failed after {max_retries} attempts: {e}")
                        raise

                    logger.warning(
                        f"DB connection error (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Resetting connection and retrying..."
                    )
                    
                    # Reset global connection pool/engines
                    # This ensures the next get_db_session() call creates fresh engines
                    try:
                        from utils.database.database_session import reset_database_connection
                        reset_database_connection()
                    except Exception as reset_err:
                        logger.error(f"Failed to reset database connection: {reset_err}")
                    
                    # Exponential backoff
                    delay = initial_delay * (2 ** attempt)
                    time.sleep(delay)
            
            # Should not accept here, but just in case
            if last_exception:
                raise last_exception
                
        return wrapper
    return decorator

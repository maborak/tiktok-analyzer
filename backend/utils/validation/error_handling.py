"""
Error handling utilities

Centralized error handling to standardize HTTPException patterns
and provide consistent error responses across the application.
"""

from fastapi import HTTPException, status
from typing import Optional, Any, Dict
import logging
from sqlalchemy.exc import OperationalError, DisconnectionError

logger = logging.getLogger(__name__)

def raise_not_found_error(detail: str, resource_type: str = "Resource") -> None:
    """
    Raise a standardized 404 Not Found error.
    
    Args:
        detail: Error detail message
        resource_type: Type of resource that was not found
    """
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource_type} not found: {detail}"
    )

def raise_internal_server_error(detail: str, operation: str = "Operation") -> None:
    """
    Raise a standardized 500 Internal Server Error.
    
    Args:
        detail: Error detail message
        operation: Description of the operation that failed
    """
    logger.error(f"{operation} failed: {detail}")
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"{operation} failed: {detail}"
    )

def raise_bad_request_error(detail: str, field: Optional[str] = None) -> None:
    """
    Raise a standardized 400 Bad Request error.
    
    Args:
        detail: Error detail message
        field: Optional field name that caused the error
    """
    message = f"Invalid {field}: {detail}" if field else detail
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message
    )

def raise_conflict_error(detail: str, resource: str = "Resource") -> None:
    """
    Raise a standardized 409 Conflict error.
    
    Args:
        detail: Error detail message
        resource: Type of resource that conflicts
    """
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"{resource} conflict: {detail}"
    )

def raise_locked_error(detail: str, resource: str = "Resource") -> None:
    """
    Raise a standardized 423 Locked error.
    
    Args:
        detail: Error detail message
        resource: Type of resource that is locked
    """
    raise HTTPException(
        status_code=status.HTTP_423_LOCKED,
        detail=f"{resource} is locked: {detail}"
    )

def safe_api_operation(operation: callable, 
                      error_message: str = "Operation failed",
                      not_found_message: Optional[str] = None) -> Any:
    """
    Safely execute an API operation with standardized error handling.
    
    Args:
        operation: Function to execute
        error_message: Message for internal server errors
        not_found_message: Optional message for not found errors
        
    Returns:
        Operation result
        
    Raises:
        HTTPException: Standardized HTTP errors
    """
    try:
        return operation()
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"{error_message}: {e}")
        raise_internal_server_error(str(e), error_message)

def create_error_response(message: str, 
                         status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
                         details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a standardized error response.
    
    Args:
        message: Error message
        status_code: HTTP status code
        details: Optional additional error details
        
    Returns:
        Standardized error response dictionary
    """
    response = {
        "error": True,
        "message": message,
        "status_code": status_code
    }
    
    if details:
        response["details"] = details
        
    return response

def is_database_error(error: Exception) -> bool:
    """
    Check if an error is a database-related error.
    
    Args:
        error: Exception to check
        
    Returns:
        True if error is database-related, False otherwise
    """
    # Check for SQLAlchemy database errors
    if isinstance(error, (OperationalError, DisconnectionError)):
        return True
    
    # Check error message for database-related keywords
    error_str = str(error).lower()
    database_keywords = [
        'database',
        'db error',
        'connection',
        'operationalerror',
        'disconnectionerror',
        'sqlalchemy',
        'psycopg2',
        'pymysql',
        'sqlite',
        'postgresql',
        'mysql',
        'server closed the connection',
        'connection unexpectedly',
        'connection lost',
        'connection reset',
        'connection timed out',
        'connection refused',
        'broken pipe',
        'connection pool',
        'connection is closed',
        'connection was closed',
        'lost connection',
        'connection error'
    ]
    return any(keyword in error_str for keyword in database_keywords)

def sanitize_error_message(error: Exception, operation: str = "Operation") -> str:
    """
    Sanitize error message for client responses.
    Database errors are replaced with generic messages unless DEBUG_MODE is enabled.
    
    Args:
        error: Exception that occurred
        operation: Description of the operation that failed
        
    Returns:
        Sanitized error message safe to return to clients (or full error if DEBUG_MODE)
    """
    from config import CONFIG
    
    # Log the full error server-side
    logger.error("%s failed: %s", operation, error, exc_info=True)
    
    # If DEBUG_MODE is enabled, return the full error message
    if CONFIG.get("DEBUG_MODE", False):
        error_str = str(error)
        # Include error type for better debugging
        error_type = type(error).__name__
        return f"{operation} failed: [{error_type}] {error_str}"
    
    # If it's a database error, return generic message
    if is_database_error(error):
        return f"{operation} failed. Please try again later."
    
    # For non-database errors, return generic message to avoid exposing internals
    return f"{operation} failed. Please try again later." 
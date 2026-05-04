"""
Utilities Package

Contains utility functions organized by responsibility.
"""

# Import from organized subpackages
from .security import *
from .database import *
from .validation import *

# Import database functions that are not in the database subpackage
from database import create_database_engine, get_session_maker, create_tables
from config import get_database_url

from .debug import (
    debug_return
)

from .display import (
    jq,
    json_print,
    table_print,
    BeautifulPrinter,
    convert_to_serializable
)

__all__ = [
    # Security utilities
    'get_current_user', 'require_admin', 'require_moderator',
    'require_permission', 'require_product_access',
    'get_auth_middleware', 'get_rate_limit_middleware',

    # Database utilities
    'get_db_session',
    'clear_database', 'init_database', 'seed_database', 'reset_database',
    'DatabaseConnectionParser', 'get_database_driver_requirements',
    'create_database_engine', 'get_session_maker', 'create_tables',
    'get_database_url',

    # Validation utilities
    'safe_api_operation', 'raise_not_found_error',
    'raise_internal_server_error', 'raise_bad_request_error',
    'raise_conflict_error', 'raise_locked_error', 'create_error_response',

    # Debug utilities
    'debug_return',

    # Display utilities
    'jq', 'json_print', 'table_print', 'BeautifulPrinter', 'convert_to_serializable'
]

"""
Domain Package

Contains all domain logic organized by responsibility.
"""

# Import from organized subpackages
from .entities import *
# from .services import *  # Removed to avoid circular import
from .api_models import *

__all__ = [
    # Entities
    'User', 'UserSession', 'ApiKey', 'AuthContext',
    'AuthStatus', 'UserRole', 'LoginRequest', 'RegisterRequest',
    'PasswordResetRequest', 'PasswordResetResponse',
    'ChangePasswordRequest', 'ChangePasswordResponse',
    'CreateApiKeyRequest', 'CreateApiKeyResponse',

    # API Models
    'ApiResponse', 'ErrorResponse'
]

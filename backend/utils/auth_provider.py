"""
Auth Service Provider

Provides access to the AuthService singleton without circular import issues.
This module should only depend on domain models, not on route modules.
"""

from typing import Optional
from fastapi import HTTPException, status

from domain.services.auth_service import AuthService

# Global auth service instance - set by routes/auth.py during initialization
_auth_service: Optional[AuthService] = None


def set_auth_service(service: AuthService) -> None:
    """Set the global auth service instance (called during app initialization)"""
    global _auth_service
    _auth_service = service


def get_auth_service() -> AuthService:
    """Get the authentication service instance (FastAPI dependency)"""
    if _auth_service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service not initialized"
        )
    return _auth_service

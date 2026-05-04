"""
OAuth Service Provider

Provides access to the OAuthService singleton without circular import issues.
"""

from typing import Optional
from fastapi import HTTPException, status

from domain.services.oauth_service import OAuthService

_oauth_service: Optional[OAuthService] = None


def set_oauth_service(service: OAuthService) -> None:
    """Set the global OAuth service instance (called during app initialization)."""
    global _oauth_service
    _oauth_service = service


def get_oauth_service() -> OAuthService:
    """Get the OAuth service instance (FastAPI dependency)."""
    if _oauth_service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth service not initialized"
        )
    return _oauth_service

"""
OAuth Domain Models

Domain models for OAuth provider account linking.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class OAuthAccount:
    """Domain model for an OAuth provider account linked to a user."""
    id: int
    user_id: int
    provider: str  # 'google', 'apple', 'github'
    provider_user_id: str  # Provider's unique user ID
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class GoogleOAuthRequest:
    """Request model for Google OAuth login."""
    id_token: str

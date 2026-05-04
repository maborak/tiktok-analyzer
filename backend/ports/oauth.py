"""
OAuth Port — Abstract interface for OAuth account persistence.
"""

from abc import ABC, abstractmethod
from typing import Optional, List

from domain.entities.oauth_models import OAuthAccount


class OAuthPort(ABC):
    """Port for OAuth account persistence operations."""

    @abstractmethod
    def get_oauth_account(self, provider: str, provider_user_id: str) -> Optional[OAuthAccount]:
        """Find an existing OAuth account link by provider and provider user ID."""
        pass

    @abstractmethod
    def get_oauth_accounts_by_user(self, user_id: int) -> List[OAuthAccount]:
        """Get all OAuth accounts linked to a user."""
        pass

    @abstractmethod
    def create_oauth_account(self, oauth_account: OAuthAccount) -> Optional[OAuthAccount]:
        """Create a new OAuth account link."""
        pass

    @abstractmethod
    def delete_oauth_account(self, provider: str, provider_user_id: str) -> bool:
        """Unlink an OAuth account."""
        pass

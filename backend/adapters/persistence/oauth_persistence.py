"""
OAuth Persistence Adapter

Implements OAuthPort for SQLAlchemy-based persistence of OAuth account links.
"""

import logging
from typing import Optional, List

from ports.oauth import OAuthPort
from domain.entities.oauth_models import OAuthAccount
from database.auth.oauth_models import OAuthAccount as OAuthAccountModel
from utils.database.database_session import get_db_session

logger = logging.getLogger(__name__)


class OAuthPersistenceAdapter(OAuthPort):
    """SQLAlchemy adapter for OAuth account persistence."""

    def get_oauth_account(self, provider: str, provider_user_id: str) -> Optional[OAuthAccount]:
        with get_db_session() as session:
            model = (
                session.query(OAuthAccountModel)
                .filter_by(provider=provider, provider_user_id=provider_user_id)
                .first()
            )
            return self._to_domain(model) if model else None

    def get_oauth_accounts_by_user(self, user_id: int) -> List[OAuthAccount]:
        with get_db_session() as session:
            models = (
                session.query(OAuthAccountModel)
                .filter_by(user_id=user_id)
                .all()
            )
            return [self._to_domain(m) for m in models]

    def create_oauth_account(self, oauth_account: OAuthAccount) -> Optional[OAuthAccount]:
        try:
            with get_db_session() as session:
                model = OAuthAccountModel(
                    user_id=oauth_account.user_id,
                    provider=oauth_account.provider,
                    provider_user_id=oauth_account.provider_user_id,
                    email=oauth_account.email,
                    name=oauth_account.name,
                    avatar_url=oauth_account.avatar_url,
                )
                session.add(model)
                session.flush()
                result = self._to_domain(model)
                session.commit()
                return result
        except Exception as e:
            logger.error("Failed to create OAuth account: %s", e)
            return None

    def delete_oauth_account(self, provider: str, provider_user_id: str) -> bool:
        try:
            with get_db_session() as session:
                rows = (
                    session.query(OAuthAccountModel)
                    .filter_by(provider=provider, provider_user_id=provider_user_id)
                    .delete()
                )
                session.commit()
                return rows > 0
        except Exception as e:
            logger.error("Failed to delete OAuth account: %s", e)
            return False

    @staticmethod
    def _to_domain(model: OAuthAccountModel) -> OAuthAccount:
        return OAuthAccount(
            id=model.id,
            user_id=model.user_id,
            provider=model.provider,
            provider_user_id=model.provider_user_id,
            email=model.email,
            name=model.name,
            avatar_url=model.avatar_url,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

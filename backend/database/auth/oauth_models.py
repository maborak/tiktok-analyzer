from ..core.base import Base
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.orm import relationship


class OAuthAccount(Base):
    """
    SQLAlchemy model for OAuth account links.

    Maps external OAuth provider identities (Google, Apple, GitHub, etc.)
    to internal user accounts. One user can have multiple OAuth accounts
    from different providers.
    """
    __tablename__ = "oauth_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    provider = Column(String(50), nullable=False)  # 'google', 'apple', 'github'
    provider_user_id = Column(String(255), nullable=False)  # Provider's unique user ID (e.g. Google 'sub')
    email = Column(String(255), nullable=True)  # Email from provider
    name = Column(String(255), nullable=True)  # Display name from provider
    avatar_url = Column(String(500), nullable=True)  # Profile picture URL
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="oauth_accounts")

    __table_args__ = (
        UniqueConstraint('provider', 'provider_user_id', name='uq_oauth_provider_user'),
        Index('ix_oauth_provider_email', 'provider', 'email'),
    )

    def __repr__(self):
        return f"<OAuthAccount(id={self.id}, provider='{self.provider}', user_id={self.user_id})>"

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func
import enum

from database.core.base import Base


class RecipientType(str, enum.Enum):
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"


class Recipient(Base):
    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(SQLEnum(RecipientType), nullable=False)
    value = Column(String, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    subject_tag = Column(String, nullable=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)

    # Relationships
    user = relationship("User", backref=backref("recipients", passive_deletes=True))


class RecipientVerification(Base):
    __tablename__ = "recipient_verifications"

    id = Column(Integer, primary_key=True, index=True)
    recipient_id = Column(Integer, ForeignKey("recipients.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    token_salt = Column(String(255), nullable=False)
    token_prefix = Column(String(16), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)

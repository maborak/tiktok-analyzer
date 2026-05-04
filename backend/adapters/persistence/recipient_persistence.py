"""
Recipient persistence adapter.

Handles CRUD for recipients and recipient verification tokens.
Extracted from the former price_alert_persistence module.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import hashlib
import hmac
import logging

from adapters.persistence._base import BasePersistenceAdapter

from domain.entities.recipient_models import (
    Recipient as DistRecipient,
    RecipientType as DistRecipientType,
)
from database.recipients.models import (
    Recipient,
    RecipientVerification,
    RecipientType,
)
from database.auth.utils import generate_salt, hash_password

logger = logging.getLogger(__name__)


class DatabaseRecipientPersistenceAdapter(BasePersistenceAdapter):
    """Recipient and recipient-verification persistence."""

    def _recipient_model_to_domain(self, r, alert_count: int = 0) -> DistRecipient:
        """Convert a database recipient model to a domain entity."""
        return DistRecipient(
            id=r.id,
            user_id=r.user_id,
            type=DistRecipientType(r.type.value),
            value=r.value,
            is_verified=r.is_verified,
            is_enabled=r.is_enabled,
            subject_tag=r.subject_tag,
            name=r.name,
            alert_count=alert_count,
        )

    # ------------------------------------------------------------------ #
    #  Recipients                                                          #
    # ------------------------------------------------------------------ #

    def create_recipient(self, recipient: DistRecipient) -> int:
        """Create a new recipient."""
        def _create(session: Session):
            db_recipient = Recipient(
                user_id=recipient.user_id,
                type=RecipientType(recipient.type.value),
                value=recipient.value,
                is_verified=recipient.is_verified,
                is_enabled=recipient.is_enabled,
                subject_tag=recipient.subject_tag,
                name=recipient.name,
            )
            session.add(db_recipient)
            session.flush()
            return db_recipient.id
        return self._execute_with_retry(_create)

    def get_recipient(self, recipient_id: int) -> Optional[DistRecipient]:
        """Get a recipient by ID."""
        def _get(session: Session):
            r = session.query(Recipient).filter(Recipient.id == recipient_id).first()
            if not r:
                return None
            return self._recipient_model_to_domain(r)
        return self._execute_with_retry(_get)

    def get_user_recipients(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "asc",
        recipient_type: Optional[str] = None,
        is_verified: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Get paginated and filtered recipients for a user."""
        def _get_paginated(session: Session):
            query = session.query(Recipient).filter(Recipient.user_id == user_id)

            # Filtering
            if recipient_type:
                query = query.filter(Recipient.type == RecipientType(recipient_type).value)
            if is_verified is not None:
                query = query.filter(Recipient.is_verified == is_verified)

            # Search
            if search:
                query = query.filter(
                    (Recipient.name.ilike(f"%{search}%"))
                    | (Recipient.value.ilike(f"%{search}%"))
                )

            # Sorting
            if sort_by:
                col = getattr(Recipient, sort_by, None)
                if col:
                    if sort_order.lower() == "desc":
                        query = query.order_by(desc(col))
                    else:
                        query = query.order_by(col)
            else:
                query = query.order_by(desc(Recipient.id))

            # Total count before pagination
            total = query.count()

            # Pagination
            offset = (page - 1) * page_size
            recs = query.offset(offset).limit(page_size).all()

            items = [self._recipient_model_to_domain(r, alert_count=0) for r in recs]

            return {
                "items": items,
                "pagination": {
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": (total + page_size - 1) // page_size,
                },
            }
        return self._execute_with_retry(_get_paginated)

    def update_recipient_verified(self, recipient_id: int, is_verified: bool) -> bool:
        """Update recipient verification status."""
        def _update(session: Session):
            r = session.query(Recipient).filter(Recipient.id == recipient_id).first()
            if not r:
                return False
            r.is_verified = is_verified
            return True
        return self._execute_with_retry(_update)

    def update_recipient(self, recipient: DistRecipient) -> bool:
        """Update an existing recipient."""
        def _update(session: Session):
            r = session.query(Recipient).filter(Recipient.id == recipient.id).first()
            if not r:
                return False
            r.type = RecipientType(recipient.type.value)
            r.value = recipient.value
            r.is_verified = recipient.is_verified
            r.is_enabled = recipient.is_enabled
            r.subject_tag = recipient.subject_tag
            r.name = recipient.name
            return True
        return self._execute_with_retry(_update)

    def delete_recipient(self, recipient_id: int) -> bool:
        """Delete a recipient and its verification tokens."""
        def _delete(session: Session):
            # Delete verification tokens
            session.query(RecipientVerification).filter(
                RecipientVerification.recipient_id == recipient_id
            ).delete()

            # Delete the recipient itself
            r = session.query(Recipient).filter(Recipient.id == recipient_id).first()
            if r:
                session.delete(r)
                return True
            return False
        return self._execute_with_retry(_delete)

    # ------------------------------------------------------------------ #
    #  Recipient Verification                                              #
    # ------------------------------------------------------------------ #

    def create_recipient_verification(self, recipient_id: int, token: str, expires_at: datetime) -> bool:
        """Create a secure verification token for a recipient (with salted hashing)."""
        def _create(session: Session):
            salt = generate_salt()
            token_hash = hash_password(token, salt)
            token_prefix = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]

            # Invalidate any existing unused tokens for this recipient
            session.query(RecipientVerification).filter(
                RecipientVerification.recipient_id == recipient_id
            ).delete()

            v = RecipientVerification(
                recipient_id=recipient_id,
                token_hash=token_hash,
                token_salt=salt,
                token_prefix=token_prefix,
                expires_at=expires_at,
            )
            session.add(v)
            return True
        return self._execute_with_retry(_create)

    def get_recipient_id_by_token(self, token: str) -> Optional[int]:
        """Get recipient ID from verification token using secure hashed lookup."""
        def _get(session: Session):
            token_prefix = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            candidates = session.query(RecipientVerification).filter(
                RecipientVerification.token_prefix == token_prefix,
                RecipientVerification.expires_at > now_utc,
            ).all()

            for v in candidates:
                test_hash = hash_password(token, v.token_salt)
                if hmac.compare_digest(test_hash, v.token_hash):
                    return v.recipient_id
            return None
        return self._execute_with_retry(_get)

    def get_latest_recipient_verification(self, recipient_id: int) -> Optional[Dict[str, Any]]:
        """Get the most recent verification record for a recipient."""
        def _get(session: Session):
            v = (
                session.query(RecipientVerification)
                .filter(RecipientVerification.recipient_id == recipient_id)
                .order_by(RecipientVerification.created_at.desc())
                .first()
            )
            if not v:
                return None
            return {
                "id": v.id,
                "recipient_id": v.recipient_id,
                "created_at": v.created_at,
                "expires_at": v.expires_at,
            }
        return self._execute_with_retry(_get)

    def get_user_verified_recipient_by_email(self, user_id: int, email: str) -> Optional[DistRecipient]:
        """Get a specific verified recipient by email for a user."""
        def _get(session: Session):
            r = session.query(Recipient).filter(
                Recipient.user_id == user_id,
                Recipient.type == RecipientType.EMAIL,
                Recipient.value == email,
                Recipient.is_verified == True,
            ).first()
            if not r:
                return None
            return self._recipient_model_to_domain(r)
        return self._execute_with_retry(_get)

    def get_user_recipients_count(self, user_id: int) -> int:
        """Get number of recipients configured by a user."""
        def _get_count(session: Session):
            return session.query(Recipient).filter(
                Recipient.user_id == user_id
            ).count()
        return self._execute_with_retry(_get_count)

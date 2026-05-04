"""
Service for managing user credits and tracking limits.
One track = One credit.
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta

from ports.data_persistence import DataPersistencePort
from domain.entities.auth_models import User
from domain.entities.billing_models import CreditLedgerEntry, LedgerSource

logger = logging.getLogger(__name__)

class CreditService:
    def __init__(self, data_persistence_adapter: DataPersistencePort, hook_manager=None):
        self.data_persistence_adapter = data_persistence_adapter
        self.hook_manager = hook_manager

    def get_credit_balance(self, user_id: int) -> int:
        """
        Calculate the total available consumable credits for a user.
        Balance = Sum of `amount` from all CreditLedger entries where expires_at > now.
        Includes positive amounts (purchases/grants) and negative amounts (consumption).
        """
        valid_ledgers = self.data_persistence_adapter.get_valid_ledgers_for_user(user_id)
        balance = sum(entry.amount for entry in valid_ledgers)
        return balance

    def can_user_track(self, user_id: int) -> bool:
        """
        Check if user has > 0 credits to track a new product.
        """
        balance = self.get_credit_balance(user_id)
        allowed = balance > 0
        logger.info(f"Credit Check: user={user_id}, balance={balance}, allowed={allowed}")
        return allowed

    def consume_credit(self, user_id: int, description: str = "Product tracking", note: str = None) -> bool:
        """Deduct one credit from user balance"""
        if not self.can_user_track(user_id):
            raise ValueError("Insufficient credits to track product.")

        entry = CreditLedgerEntry(
            id="",
            user_id=user_id,
            amount=-1,
            source=LedgerSource.TRACK_PRODUCT,
            transaction_id=None,
            expires_at=datetime.now(timezone.utc) + timedelta(days=365 * 10), # 10 years expiration for deduction
            note=note
        )
        entry_id = self.data_persistence_adapter.add_credit_ledger_entry(entry)
        logger.info(f"Consumed 1 credit for user={user_id}. entry_id={entry_id}")

        # Fire CREDIT_EXHAUSTED if balance is now zero
        if self.hook_manager:
            new_balance = self.get_credit_balance(user_id)
            if new_balance <= 0:
                from ports.hooks.base_handler import HookEvent, HookEventType
                self.hook_manager.fire(HookEvent(
                    event_type=HookEventType.CREDIT_EXHAUSTED,
                    data={"user_id": user_id, "balance": new_balance},
                    source="credit_service"
                ))

        return True

    def renew_track(self, user_id: int, track_id: int) -> bool:
        """Attempt to renew a product track for 30 days"""
        if not self.can_user_track(user_id):
            return False

        # 1. Look up track for note
        track = self.data_persistence_adapter.get_product_track(track_id)
        if not track:
            return False
        note = f"{track.product_id}/{track.country_code}" if track.product_id else None

        # 2. Consume 1 credit
        self.consume_credit(user_id, f"Auto-renewal for track {track_id}", note=note)

        # 3. Update expiry
        now = datetime.now(timezone.utc)
        # If already expired, start from now. If not, extend from current expiry.
        start_date = track.expires_at if track.expires_at and track.expires_at > now else now
        new_expiry = start_date + timedelta(days=30)
        
        self.data_persistence_adapter.update_track_status(track_id, status="active", expires_at=new_expiry, is_enabled=True)
        return True

    def grant_registration_credits(self, user_id: int, amount: int | None = None) -> bool:
        """Grant initial credits to a newly registered user"""
        if amount is None:
            from config import CONFIG
            amount = CONFIG.get("REGISTRATION_CREDITS", 5)
        entry = CreditLedgerEntry(
            id="",
            user_id=user_id,
            amount=amount,
            source=LedgerSource.REGISTRATION,
            transaction_id=None,
            expires_at=datetime.now(timezone.utc) + timedelta(days=365)
        )
        self.data_persistence_adapter.add_credit_ledger_entry(entry)
        logger.info(f"Granted {amount} registration credits to user={user_id}")
        return True


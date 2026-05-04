"""
Event Persistence Handler

Subscribes to ALL hook events ('*') and persists sanitized payloads
to the hook_events table for audit trail and monitoring dashboards.

Thread-safe: creates its own engine + session factory, isolated from
the main request lifecycle. Runs inside HookManager's ThreadPoolExecutor.
"""

import json
import logging
from typing import Dict, List, Optional

from ports.hooks.base_handler import HookHandler, HookEvent

logger = logging.getLogger(__name__)

# Per-event-type whitelist of fields allowed in data_json.
# Any field not listed is stripped before persistence.
# Unknown event types get an empty dict (safe default).
PAYLOAD_WHITELIST: Dict[str, List[str]] = {
    # Price events
    "price_saved": ["asin", "country_code", "process_type"],
    "price_checked": ["asin", "country_code", "process_type"],
    "price_new": ["asin", "country_code", "process_type"],
    "price_updated": ["asin", "country_code", "process_type"],
    "price_changed": ["asin", "country_code", "process_type"],
    "price_not_changed": ["asin", "country_code", "process_type"],
    # Product events
    "product_added": ["asin", "country_code"],
    "product_updated": ["asin", "country_code"],
    "product_available": ["asin", "country_code"],
    "product_unavailable": ["asin", "country_code"],
    "product_out_of_stock": ["asin", "country_code"],
    # User events (strip tokens and passwords)
    "user_registered": ["user_id", "email", "username"],
    "user_login": ["user_id", "email"],
    "user_verification_requested": ["user_id", "email"],
    "user_password_reset_requested": ["user_id", "email"],
    "user_price_alert": ["user_id", "alert_id", "asin", "country_code", "alert_name", "track_id"],
    # System events
    "admin_notification": ["subject", "message"],
    "monitoring_started": ["worker_id"],
    "monitoring_completed": ["worker_id"],
    # Ticket events (strip guest_access_token)
    "ticket_created": ["ticket_id", "status", "subject", "action"],
    "ticket_updated": ["ticket_id", "status", "action"],
    # Billing events
    "credit_purchased": ["user_id", "credits", "amount", "currency", "provider", "package_id"],
    "credit_exhausted": ["user_id", "balance"],
    # Tracking events
    "product_track_added": ["user_id", "asin", "country_code", "track_id", "price_alert_id", "is_enabled"],
    "product_track_removed": ["user_id", "asin", "country_code"],
    "product_track_resumed": ["user_id", "asin", "country_code", "track_id"],
    # Handler outcome events
    "email_sent": ["recipient", "subject", "template", "event_type"],
    "email_failed": ["recipient", "subject", "error", "event_type"],
    "alert_evaluated": [
        "asin", "country_code", "event_type", "alerts_triggered",
        "tracks_total", "tracks_no_alert", "tracks_skipped_cooldown", "tracks_no_triggers",
        "cooldown_status", "old_price", "new_price",
    ],
    # Wizard events (consolidated from tracking_events)
    "wizard_opened": ["user_id", "asin", "country_code"],
    "wizard_step_entered": ["user_id", "asin", "step_name"],
    "wizard_completed": ["user_id", "asin", "preset_id", "trigger_count"],
    "wizard_abandoned": ["user_id", "asin", "step_name"],
}


class EventPersistenceHandler(HookHandler):
    """
    Persists all hook events to the hook_events database table.

    Uses its own database session factory to avoid coupling with
    the main request-scoped sessions. This is safe because the handler
    runs on HookManager's ThreadPoolExecutor background threads.
    """

    def __init__(self):
        super().__init__(name="EventPersistenceHandler")
        self._session_factory = None

    def _get_session_factory(self):
        """Lazy-initialize session factory on first use."""
        if self._session_factory is None:
            from database.core.connection import create_database_engine, get_session_maker
            engine = create_database_engine()
            self._session_factory = get_session_maker(engine)
        return self._session_factory

    @property
    def enabled(self) -> bool:
        """Always enabled — event persistence is infrastructure, not user-configurable."""
        return True

    @property
    def subscribed_events(self) -> list[str]:
        return ["*"]

    @staticmethod
    def _resolve_event_type(event_type) -> str:
        """Extract the plain string value from an event type (enum or str)."""
        return getattr(event_type, 'value', event_type)

    def handle(self, event: HookEvent) -> None:
        from database.hooks.hook_event_models import HookEventModel

        event_type_str = self._resolve_event_type(event.event_type)
        sanitized = self._sanitize(event, event_type_str)
        session_factory = self._get_session_factory()
        session = session_factory()
        try:
            record = HookEventModel(
                event_type=event_type_str,
                source=event.source,
                trace_id=event.trace_id,
                data_json=json.dumps(sanitized, default=str),
                metadata_json=json.dumps(event.metadata, default=str) if event.metadata else None,
                created_at=event.timestamp,
            )
            session.add(record)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _sanitize(self, event: HookEvent, event_type_str: str = None) -> dict:
        """Filter event data to only whitelisted fields for the event type."""
        event_type = event_type_str or self._resolve_event_type(event.event_type)
        whitelist = PAYLOAD_WHITELIST.get(event_type)
        if whitelist is None:
            return {}
        return {k: v for k, v in event.data.items() if k in whitelist}

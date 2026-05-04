"""
Notification Queue Domain Models

Channel-agnostic notification message for async delivery via Redis queue.
Subject + body are pre-rendered before enqueueing — the consumer is a pure delivery agent.
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class NotificationMessage:
    """A single notification ready for delivery via the async queue."""

    # Identity & routing
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    channel: str = "email"  # "email" | "telegram" | "slack" | "webhook"

    # Delivery payload (pre-rendered by the producer)
    recipient_email: str = ""
    recipient_name: Optional[str] = None
    subject: str = ""
    body: str = ""

    # Retry state
    attempt: int = 1
    max_attempts: int = 5
    created_at: float = field(default_factory=time.time)

    # Traceability context (carried from the originating hook event)
    trace_id: Optional[str] = None
    event_type: str = ""
    user_id: int = 0
    alert_id: Optional[int] = None
    track_id: Optional[int] = None
    asin: str = ""
    country_code: str = ""
    recipient_id: Optional[int] = None

    # --- Serialization for Redis ---

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "NotificationMessage":
        return cls(**json.loads(data))

from dataclasses import dataclass
from enum import Enum
from typing import Optional

class RecipientType(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"

@dataclass
class Recipient:
    id: int
    user_id: int
    type: RecipientType
    value: str
    is_verified: bool = False
    is_enabled: bool = True
    subject_tag: Optional[str] = None
    name: Optional[str] = None
    alert_count: int = 0

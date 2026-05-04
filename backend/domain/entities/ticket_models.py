from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from enum import Enum


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_CUSTOMER = "PENDING_CUSTOMER"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class TicketOrigin(str, Enum):
    WEB = "WEB"
    EMAIL = "EMAIL"
    API = "API"
    LIVECHAT = "LIVECHAT"
    CONTACT_FORM = "CONTACT_FORM"


@dataclass
class TicketCategoryDef:
    id: str
    name: str
    description: str
    is_active: bool = True


@dataclass
class TicketTag:
    id: str
    name: str
    color: str


@dataclass
class Ticket:
    id: str
    subject: str
    status: TicketStatus
    priority: TicketPriority
    category_id: str
    origin: TicketOrigin
    created_at: datetime
    updated_at: datetime
    user_id: Optional[int] = None
    sender_email: Optional[str] = None
    assigned_agent_id: Optional[int] = None
    sla_due_date: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    guest_access_token: Optional[str] = None
    reopen_count: int = 0
    tags: list[TicketTag] = field(default_factory=list)


@dataclass
class TicketAttachment:
    id: str
    ticket_id: str
    message_id: str
    file_name: str
    file_url: str
    content_type: str
    file_size: int
    created_at: datetime


@dataclass
class TicketMessage:
    id: str
    ticket_id: str
    message: str
    created_at: datetime
    sender_id: Optional[int] = None
    sender_email: Optional[str] = None
    is_internal_note: bool = False
    attachments: list[TicketAttachment] = field(default_factory=list)


@dataclass
class TicketInboundConfig:
    id: str
    email_address: str
    default_category_id: str


class LiveChatStatus(str, Enum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class LiveChatSenderType(str, Enum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


@dataclass
class LiveChatAttachment:
    id: str
    session_id: str
    message_id: str
    file_name: str
    file_url: str
    content_type: str
    file_size: int
    created_at: datetime



@dataclass
class LiveChatSession:
    id: str
    user_id: Optional[int]
    session_token: Optional[str]
    status: LiveChatStatus
    created_at: datetime
    ended_at: Optional[datetime] = None
    agent_id: Optional[int] = None
    ticket_id: Optional[str] = None
    is_authenticated_user: bool = False
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    current_url: Optional[str] = None
    initial_context: Optional[dict] = None
    initial_message: Optional[str] = None
    typing_status: Optional[dict] = None
    first_response_at: Optional[datetime] = None
    resolution_time_seconds: Optional[int] = None
    csat_score: Optional[int] = None
    csat_comment: Optional[str] = None
    is_proactive: bool = False


@dataclass
class LiveChatMessage:
    id: str
    session_id: str
    sender_type: LiveChatSenderType
    message: str
    created_at: datetime
    sender_id: Optional[int] = None
    attachments: list[LiveChatAttachment] = field(default_factory=list)
    context: Optional[dict] = None
    read_at: Optional[datetime] = None

@dataclass
class LiveChatMacro:
    id: str
    shortcut: str
    content: str
    category: Optional[str] = None
    created_at: Optional[datetime] = None

"""
Hook Handlers (Adapters)

Handlers that adapt hook events to external systems (email, push, webhook, etc.)
"""

from .email_handler import EmailHandler
from .log_handler import LogHandler
from .event_persistence_handler import EventPersistenceHandler

__all__ = [
    "EmailHandler",
    "LogHandler",
    "EventPersistenceHandler",
]

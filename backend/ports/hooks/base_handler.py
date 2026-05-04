"""
Base Handler and Event definitions for the Hook system
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from enum import Enum


class HookEventType(str, Enum):
    """Predefined hook event types"""

    # User events
    USER_REGISTERED = "user_registered"
    USER_LOGIN = "user_login"
    USER_VERIFICATION_REQUESTED = "user_verification_requested"
    USER_PASSWORD_RESET_REQUESTED = "user_password_reset_requested"

    # System events
    ADMIN_NOTIFICATION = "admin_notification"

    # Ticket events
    TICKET_CREATED = "ticket_created"
    TICKET_UPDATED = "ticket_updated"

    # Billing events
    CREDIT_PURCHASED = "credit_purchased"
    CREDIT_EXHAUSTED = "credit_exhausted"

    # Handler outcome events
    EMAIL_SENT = "email_sent"
    EMAIL_FAILED = "email_failed"

    # Config events
    CONFIG_CHANGED = "config_changed"

    # OAuth account events
    OAUTH_ACCOUNT_LINKED = "oauth_account_linked"
    OAUTH_ACCOUNT_UNLINKED = "oauth_account_unlinked"

    # Custom events (use string directly)
    CUSTOM = "custom"


@dataclass
class HookEvent:
    """
    Event data passed to hook handlers.
    
    Attributes:
        event_type: Type of event (from HookEventType or custom string)
        data: Event-specific data dictionary
        timestamp: When the event occurred
        source: Where the event originated (e.g., 'product_service', 'monitor')
        metadata: Additional metadata (optional)
    """
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get value from data dict"""
        return self.data.get(key, default)
    
    def __repr__(self) -> str:
        return f"HookEvent(type={self.event_type}, source={self.source}, keys={list(self.data.keys())})"


class HookHandler(ABC):
    """
    Base class for hook handlers.
    
    Implement this class to create custom handlers for hook events.
    Each handler can subscribe to specific event types.
    
    Enabled status is determined by HOOKS_USE_DB_CONFIG in config.py:
    - If true: check database (disabled if not in DB)
    - If false: check HOOKS_HANDLERS config (disabled if not in config)
    """
    
    def __init__(self, name: Optional[str] = None):
        """
        Initialize handler.
        
        Args:
            name: Handler name (defaults to class name)
        """
        self.name = name or self.__class__.__name__
    
    @property
    def enabled(self) -> bool:
        """
        Check if handler is enabled.
        Uses HookConfigService which respects HOOKS_USE_DB_CONFIG.
        """
        try:
            from database.hooks.services import hook_config_service
            return hook_config_service.is_handler_enabled(self.name)
        except Exception as e:
            # Service not available, default to disabled for safety
            import logging
            logging.getLogger(__name__).warning(f"Could not check handler {self.name} enabled status: {e}")
            return False
    
    @property
    @abstractmethod
    def subscribed_events(self) -> list[str]:
        """
        List of event types this handler subscribes to.
        Return ['*'] to subscribe to all events.
        
        Example:
            return [HookEventType.USER_REGISTERED, HookEventType.TICKET_CREATED]
        """
        pass
    
    @abstractmethod
    def handle(self, event: HookEvent) -> None:
        """
        Handle the event.
        
        Args:
            event: The hook event to process
        """
        pass
    
    def should_handle(self, event: HookEvent) -> bool:
        """
        Check if this handler should process the event.
        Override for custom filtering logic.
        
        Args:
            event: The hook event
            
        Returns:
            True if handler should process this event
        """
        if not self.enabled:
            return False
        
        subscribed = self.subscribed_events
        if '*' in subscribed:
            return True
        
        return event.event_type in subscribed
    
    def on_error(self, event: HookEvent, error: Exception) -> None:
        """
        Called when handle() raises an exception.
        Override for custom error handling.
        
        Args:
            event: The event that caused the error
            error: The exception that was raised
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Handler {self.name} failed for event {event.event_type}: {error}")

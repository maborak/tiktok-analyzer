"""
Log Handler - Logs all hook events (useful for debugging/auditing)
"""

import logging
import json
from typing import List

from ports.hooks.base_handler import HookHandler, HookEvent, HookEventType
logger = logging.getLogger(__name__)


class LogHandler(HookHandler):
    """
    Handler that logs all events.
    
    Useful for debugging and auditing hook events.
    
    Usage:
        from ports.hooks import hook_manager
        from adapters.hooks import LogHandler
        
        hook_manager.register(LogHandler())
    """
    
    def __init__(self, log_level: int = logging.INFO):
        """
        Initialize log handler.
        
        Args:
            log_level: Logging level (default INFO)
        
        Note: enabled status is controlled by HOOKS_USE_DB_CONFIG and
        either database or HOOKS_HANDLERS config.
        """
        super().__init__(name="LogHandler")
        self.log_level = log_level
    
    @property
    def subscribed_events(self) -> List[str]:
        return [
            #'price_saved',
            #'price_new',
            #'price_updated',
            #'price_changed',
            #'price_not_changed',
            'price_changed'
        ]  # Subscribe to all events
    
    def handle(self, event: HookEvent) -> None:
        """Log the event"""
        # Serialize data for logging (handle non-serializable objects)
        try:
            data_str = json.dumps(event.data, default=str, indent=2)
        except Exception:
            data_str = str(event.data)
        
        logger.info(
            f"Hook Event: {event.event_type} | Source: {event.source} | "
            f"Timestamp: {event.timestamp.isoformat()}"
        )

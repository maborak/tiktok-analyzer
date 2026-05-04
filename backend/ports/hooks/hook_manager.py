"""
Hook Manager - Central hub for event-driven hooks

Usage:
    from ports.hooks import hook_manager, HookEvent, HookEventType
    
    # Fire an event
    hook_manager.fire(HookEvent(
        event_type=HookEventType.PRICE_SAVED,
        data={"asin": "B001234", "price": 99.99},
        source="product_service"
    ))
    
    # Register a handler
    hook_manager.register(MyEmailHandler())
"""

import logging
from typing import List, Dict, Optional, Type
from concurrent.futures import ThreadPoolExecutor
import threading

from .base_handler import HookHandler, HookEvent

logger = logging.getLogger(__name__)


class HookManager:
    """
    Central manager for hook events and handlers.
    
    Features:
    - Register multiple handlers
    - Fire events to all subscribed handlers
    - Async execution option (non-blocking)
    - Error isolation (one handler failure doesn't affect others)
    """
    
    _instance: Optional["HookManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "HookManager":
        """Singleton pattern - ensure only one HookManager exists"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the hook manager"""
        if self._initialized:
            return
        
        self._handlers: List[HookHandler] = []
        self._event_handlers: Dict[str, List[HookHandler]] = {}  # Cache for faster lookup
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hook_")
        self._auto_registered = False
        self._dependencies: dict = {}
        self._event_config_service = None
        self._initialized = True
        logger.info("HookManager initialized")

    def configure(self, **dependencies) -> None:
        """
        Provide dependencies for handlers before auto-registration.

        Call from the composition root (api_main.py) to inject adapters
        into handlers that need them.

        Args:
            **dependencies: Named dependencies (e.g. data_persistence=adapter)
        """
        self._dependencies.update(dependencies)
        if "event_config_service" in dependencies:
            self._event_config_service = dependencies["event_config_service"]
        logger.info(f"HookManager configured with dependencies: {list(dependencies.keys())}")

    def auto_register_handlers(self) -> None:
        """
        Auto-register all available handlers.
        Handlers check their own enabled status from config/database.
        """
        if self._auto_registered:
            logger.debug("Handlers already auto-registered, skipping")
            return

        try:
            from adapters.hooks import EmailHandler, LogHandler, EventPersistenceHandler

            notification_queue = self._dependencies.get("notification_queue")

            handlers = [
                LogHandler(),
                EmailHandler(notification_queue=notification_queue),
                EventPersistenceHandler(),
            ]

            for handler in handlers:
                self.register(handler)
                logger.info(f"Auto-registered handler: {handler.name} (enabled={handler.enabled})")

            self._auto_registered = True
            logger.info(f"Auto-registration complete: {len(handlers)} handlers registered")

        except Exception as e:
            logger.error(f"Failed to auto-register handlers: {e}")
    
    def register(self, handler: HookHandler) -> None:
        """
        Register a handler for events.
        
        Args:
            handler: HookHandler instance to register
        """
        if handler in self._handlers:
            logger.warning(f"Handler {handler.name} already registered, skipping")
            return
        
        self._handlers.append(handler)
        
        # Update event-handler cache
        for event_type in handler.subscribed_events:
            if event_type not in self._event_handlers:
                self._event_handlers[event_type] = []
            self._event_handlers[event_type].append(handler)
        
        logger.info(f"Registered handler: {handler.name} for events: {handler.subscribed_events}")
    
    def unregister(self, handler: HookHandler) -> bool:
        """
        Unregister a handler.
        
        Args:
            handler: Handler to remove
            
        Returns:
            True if handler was found and removed
        """
        if handler not in self._handlers:
            return False
        
        self._handlers.remove(handler)
        
        # Update cache
        for event_type in handler.subscribed_events:
            if event_type in self._event_handlers:
                self._event_handlers[event_type] = [
                    h for h in self._event_handlers[event_type] if h != handler
                ]
        
        logger.info(f"Unregistered handler: {handler.name}")
        return True
    
    def get_handlers(self) -> List[HookHandler]:
        """
        Get all registered handlers.
        Triggers auto-registration if not yet done.

        Returns:
            List of all registered HookHandler instances
        """
        if not self._auto_registered:
            self.auto_register_handlers()
        return list(self._handlers)
    
    def fire(self, event: HookEvent, async_mode: bool = True) -> None:
        """
        Fire an event to all subscribed handlers.
        
        Args:
            event: The event to fire
            async_mode: If True, handlers run in background threads (non-blocking)
        """
        # Auto-register handlers on first fire (lazy initialization)
        if not self._auto_registered:
            self.auto_register_handlers()
        
        handlers = self._get_handlers_for_event(event)
        
        if not handlers:
            logger.info(f"No handlers for event: {event.event_type}")
            return
        
        logger.info(f"Firing event {event.event_type} to {len(handlers)} handlers")
        
        for handler in handlers:
            if async_mode:
                self._executor.submit(self._execute_handler, handler, event)
            else:
                self._execute_handler(handler, event)
    
    def fire_sync(self, event: HookEvent) -> None:
        """
        Fire an event synchronously (blocking).
        
        Args:
            event: The event to fire
        """
        self.fire(event, async_mode=False)
    
    def _get_handlers_for_event(self, event: HookEvent) -> List[HookHandler]:
        """Get all handlers that should process this event"""
        handlers = []

        # Get handlers subscribed to this specific event
        if event.event_type in self._event_handlers:
            handlers.extend(self._event_handlers[event.event_type])

        # Get handlers subscribed to all events ('*')
        if '*' in self._event_handlers:
            handlers.extend(self._event_handlers['*'])

        event_type_str = getattr(event.event_type, 'value', event.event_type)

        def _is_allowed(h: HookHandler) -> bool:
            if not h.should_handle(event):
                return False
            # Check event config matrix (admin override)
            if self._event_config_service:
                return self._event_config_service.is_allowed(event_type_str, h.name)
            return True

        return [h for h in handlers if _is_allowed(h)]
    
    def _execute_handler(self, handler: HookHandler, event: HookEvent) -> None:
        """Execute a single handler safely with structured outcome logging."""
        import time as _time
        # Propagate event.trace_id into the logging context so all handler
        # logs (including those in background threads) carry the trace_id.
        from utils.logging_context import set_trace_id, get_trace_id
        if event.trace_id:
            set_trace_id(event.trace_id)
        t0 = _time.monotonic()
        try:
            handler.handle(event)
            duration_ms = round((_time.monotonic() - t0) * 1000)
            logger.info(
                "hook.handled",
                extra={
                    "hook.handler": handler.name,
                    "hook.event_type": event.event_type,
                    "hook.source": event.source,
                    "hook.status": "success",
                    "hook.duration_ms": duration_ms,
                },
            )
        except Exception as e:
            duration_ms = round((_time.monotonic() - t0) * 1000)
            logger.error(
                "hook.failed",
                extra={
                    "hook.handler": handler.name,
                    "hook.event_type": event.event_type,
                    "hook.source": event.source,
                    "hook.status": "failed",
                    "hook.error": str(e),
                    "hook.duration_ms": duration_ms,
                },
                exc_info=True,
            )
            try:
                handler.on_error(event, e)
            except Exception as err_e:
                logger.error(f"Handler {handler.name} error handler also failed: {err_e}")
    
    def get_handler_by_name(self, name: str) -> Optional[HookHandler]:
        """Get a handler by name"""
        for handler in self._handlers:
            if handler.name == name:
                return handler
        return None
    
    def clear(self) -> None:
        """Remove all handlers"""
        self._handlers.clear()
        self._event_handlers.clear()
        logger.info("All handlers cleared")
    
    def shutdown(self) -> None:
        """Shutdown the executor (call on app shutdown)"""
        self._executor.shutdown(wait=True)
        logger.info("HookManager shutdown complete")


# Global singleton instance
hook_manager = HookManager()

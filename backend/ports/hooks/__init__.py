"""
Hooks System

A generic event-driven hook system for executing actions on specific events.
Supports multiple handlers per event (email, push, webhook, etc.)

Core components (ports/hooks/):
- HookManager: Central event dispatcher
- HookHandler: Base class for handlers
- HookEvent: Event data container

Handler implementations (adapters/hooks/):
- EmailHandler: Email notifications
- LogHandler: Event logging
- (Add more handlers in adapters/hooks/)
"""

from .hook_manager import HookManager, hook_manager
from .base_handler import HookHandler, HookEvent, HookEventType

__all__ = [
    "HookManager",
    "hook_manager",
    "HookHandler", 
    "HookEvent",
    "HookEventType"
]

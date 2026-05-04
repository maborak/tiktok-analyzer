"""Port for event configuration persistence."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class EventConfigPort(ABC):
    """Abstract interface for event config storage."""

    @abstractmethod
    def get_all_event_configs(self) -> List[Dict[str, Any]]:
        """Return all event config rows as dicts with keys: event_type, handler_name, enabled."""
        ...

    @abstractmethod
    def upsert_event_config(self, event_type: str, handler_name: str, enabled: bool) -> Dict[str, Any]:
        """Insert or update a single config row. Returns the saved row as dict."""
        ...

    @abstractmethod
    def bulk_upsert_event_configs(self, updates: List[Dict[str, Any]]) -> int:
        """Bulk insert/update config rows. Each dict has event_type, handler_name, enabled. Returns count."""
        ...

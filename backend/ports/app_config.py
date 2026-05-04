"""Port for generic app configuration persistence."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class AppConfigPort(ABC):
    """Abstract interface for generic namespace/key/value config storage."""

    @abstractmethod
    def get_by_namespace(self, namespace: str, scope: str = "global",
                         scope_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all config entries for a namespace, optionally filtered by scope."""
        ...

    @abstractmethod
    def get_merged_config(self, namespace: str,
                          worker_id: Optional[int] = None) -> Dict[str, str]:
        """
        Return merged config for a namespace as {KEY: value_string}.
        If worker_id is provided, worker-specific overrides take precedence over global.
        """
        ...

    @abstractmethod
    def set_value(self, namespace: str, key: str, value: str, value_type: str,
                  scope: str, scope_id: Optional[str],
                  updated_by: Optional[str]) -> Dict[str, Any]:
        """Upsert a single config entry. Returns the saved row as dict."""
        ...

    @abstractmethod
    def delete_value(self, namespace: str, key: str,
                     scope: str, scope_id: Optional[str]) -> bool:
        """Delete a config entry. Returns True if deleted."""
        ...

    @abstractmethod
    def get_all_namespaces(self) -> List[str]:
        """Return distinct namespace values."""
        ...

    @abstractmethod
    def get_all_configs(self) -> List[Dict[str, Any]]:
        """Return every config row as list of dicts."""
        ...

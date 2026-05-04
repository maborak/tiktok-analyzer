"""Port for centralized configuration persistence.

Sits above :class:`AppConfigPort` and is scoped to the global (scope='global',
scope_id='') rows. :class:`ConfigService` uses this port for bulk cache
refresh, import/export, and snapshot replay; the existing AppConfigPort
remains for raw-CRUD and per-worker overrides.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class ConfigPort(ABC):
    @abstractmethod
    def get_all_values(self) -> Dict[str, str]:
        """Every global-scope row as {KEY: raw_value}. Feeds the cache."""
        ...

    @abstractmethod
    def get_namespace_values(self, namespace: str) -> Dict[str, str]:
        """DB values for a namespace as {KEY: raw_value}."""
        ...

    @abstractmethod
    def set_value(self, namespace: str, key: str, value: str,
                  value_type: str, updated_by: Optional[str] = None) -> None:
        """Upsert a single global-scope entry."""
        ...

    @abstractmethod
    def bulk_set(self, entries: List[Dict]) -> int:
        """Bulk upsert global-scope entries.

        Each entry: ``{"namespace", "key", "value", "value_type", "updated_by"?}``.
        Returns the number of rows written (inserts + updates).
        """
        ...

    @abstractmethod
    def export_all(self) -> List[Dict]:
        """Every global-scope row as a list of dicts with metadata.

        Each row: ``{"namespace", "key", "value", "value_type",
        "updated_by", "updated_at"}``.
        """
        ...

    @abstractmethod
    def get_db_metadata(self) -> Dict[str, Dict]:
        """``{KEY: {"updated_at", "updated_by"}}`` for every DB row.

        Used by the admin UI to show "last edited by" per field.
        """
        ...

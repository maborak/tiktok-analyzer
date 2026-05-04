"""Port for config snapshot persistence — versioning and rollback."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class ConfigSnapshotPort(ABC):
    @abstractmethod
    def create(
        self,
        name: str,
        description: Optional[str],
        trigger: str,
        payload: str,
        key_count: int,
        created_by: Optional[str],
        parent_snapshot_id: Optional[int] = None,
    ) -> int:
        """Insert a snapshot row; return its id."""
        ...

    @abstractmethod
    def list(self, limit: int = 50, offset: int = 0,
             trigger: Optional[str] = None) -> List[Dict]:
        """Snapshot metadata (no payload) ordered newest-first."""
        ...

    @abstractmethod
    def count(self, trigger: Optional[str] = None) -> int:
        """Total matching snapshots."""
        ...

    @abstractmethod
    def get(self, snapshot_id: int, include_payload: bool = False) -> Optional[Dict]:
        """Single snapshot by id, with or without its payload. None if missing."""
        ...

    @abstractmethod
    def delete(self, snapshot_id: int) -> bool:
        """Delete one snapshot. True on success, False if id not found."""
        ...

    @abstractmethod
    def prune_oldest_non_manual(self, keep: int) -> int:
        """Retention policy: keep the newest ``keep`` auto-snapshots, drop the rest.

        Manual snapshots are never pruned — the user named them on purpose.
        Returns the count of deleted rows.
        """
        ...

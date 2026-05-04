"""
Event Config Service — in-memory cache with periodic DB refresh.

Controls which (event_type, handler) combinations are enabled.
Missing entries default to enabled (fail-open).
"""

import logging
import threading
import time
from typing import Dict, List, Any, Optional, Tuple

from ports.event_config import EventConfigPort

logger = logging.getLogger(__name__)


class EventConfigService:
    REFRESH_INTERVAL = 30  # seconds

    def __init__(self, config_port: EventConfigPort):
        self._port = config_port
        self._cache: Dict[Tuple[str, str], bool] = {}
        self._lock = threading.Lock()
        self._loaded = False
        self._last_refresh: float = 0.0

    def load(self) -> None:
        """Load all config rows into cache. Called at startup and by refresh()."""
        try:
            rows = self._port.get_all_event_configs()
            new_cache = {(r["event_type"], r["handler_name"]): r["enabled"] for r in rows}
            with self._lock:
                self._cache = new_cache
                self._loaded = True
                self._last_refresh = time.monotonic()
            logger.info(f"EventConfigService: Loaded {len(new_cache)} config entries")
        except Exception as e:
            logger.error(f"EventConfigService: Failed to load config: {e}")

    def is_allowed(self, event_type: str, handler_name: str) -> bool:
        """Check if (event_type, handler) combo is enabled. Missing = True (default enabled)."""
        with self._lock:
            if not self._loaded:
                return True  # Fail open before first load
            return self._cache.get((event_type, handler_name), True)

    def refresh(self) -> None:
        """Reload from DB if stale (older than REFRESH_INTERVAL seconds)."""
        with self._lock:
            if time.monotonic() - self._last_refresh < self.REFRESH_INTERVAL:
                return
        self.load()

    def set_config(self, event_type: str, handler_name: str, enabled: bool) -> Dict[str, Any]:
        """Write-through: update DB + cache immediately."""
        result = self._port.upsert_event_config(event_type, handler_name, enabled)
        with self._lock:
            self._cache[(event_type, handler_name)] = enabled
        return result

    def bulk_set_configs(self, updates: List[Dict[str, Any]]) -> int:
        """Write-through bulk update."""
        count = self._port.bulk_upsert_event_configs(updates)
        with self._lock:
            for u in updates:
                self._cache[(u["event_type"], u["handler_name"])] = u["enabled"]
        return count

    def get_all_configs(self) -> Dict[Tuple[str, str], bool]:
        """Return full config matrix for admin UI."""
        with self._lock:
            return dict(self._cache)

    def get_configs_list(self) -> List[Dict[str, Any]]:
        """Return config as list of dicts for API serialization."""
        with self._lock:
            return [
                {"event_type": et, "handler_name": hn, "enabled": en}
                for (et, hn), en in self._cache.items()
            ]

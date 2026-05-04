"""Config Service — typed config resolution with cache, snapshots, and import/export.

Resolution chain (non-bootstrap keys):
    DB (global scope) → env var (per ENV_MAP) → registry default

Bootstrap keys (DATABASE_URL, REDIS_URL, DB_*_POOL_*) short-circuit to the
env layer because the config service can't reach the DB before they're
resolved. They're env-only and surface ``source='bootstrap'``.

Cache holds raw string values from the DB layer; env + default fall through
on each ``get()``. Cache invalidates on every write — every set / bulk_set
/ import / restore writes the DB then refreshes the cache so workers stay
consistent.
"""

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from domain.entities.config_registry import (
    CONFIG_REGISTRY,
    ENV_MAP,
    ConfigKeyDef,
    get_keys_for_namespace,
    get_namespaces,
)
from ports.config_port import ConfigPort
from ports.config_snapshot_port import ConfigSnapshotPort

logger = logging.getLogger(__name__)

_BOOLEAN_TRUE = {"true", "1", "yes", "on"}
_BOOLEAN_FALSE = {"false", "0", "no", "off", ""}
_SENSITIVE_MASK = "***"


def _coerce(raw: Optional[str], value_type: str, key: str) -> Any:
    """Convert a stored string to its typed value. Raises on bad input."""
    if raw is None:
        raw = ""
    if value_type == "string":
        return raw
    if value_type == "int":
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{key}: cannot parse {raw!r} as int")
    if value_type == "float":
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{key}: cannot parse {raw!r} as float")
    if value_type == "boolean":
        v = raw.strip().lower()
        if v in _BOOLEAN_TRUE:
            return True
        if v in _BOOLEAN_FALSE:
            return False
        raise ValueError(f"{key}: cannot parse {raw!r} as boolean")
    if value_type == "json":
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"{key}: cannot parse JSON: {e}")
    raise ValueError(f"{key}: unknown value_type {value_type!r}")


def _stringify(value: Any, value_type: str, key: str) -> str:
    """Coerce a Python value back to the canonical string form for storage."""
    if value is None:
        return ""
    if value_type == "boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
        v = str(value).strip().lower()
        if v in _BOOLEAN_TRUE:
            return "true"
        if v in _BOOLEAN_FALSE:
            return "false"
        raise ValueError(f"{key}: cannot interpret {value!r} as boolean")
    if value_type == "int":
        try:
            return str(int(value))
        except (TypeError, ValueError):
            raise ValueError(f"{key}: cannot interpret {value!r} as int")
    if value_type == "float":
        try:
            return str(float(value))
        except (TypeError, ValueError):
            raise ValueError(f"{key}: cannot interpret {value!r} as float")
    if value_type == "json":
        if isinstance(value, str):
            return value
        return json.dumps(value)
    return str(value)


class ConfigService:
    """Typed registry-backed config resolution + cache + snapshots."""

    def __init__(
        self,
        config_port: ConfigPort,
        snapshot_port: ConfigSnapshotPort,
    ):
        self._port = config_port
        self._snapshot_port = snapshot_port
        self._cache: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._loaded = False

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def load(self) -> None:
        """Populate cache from DB. Call at startup and after a restore."""
        try:
            values = self._port.get_all_values()
        except Exception as e:
            logger.error(f"ConfigService: failed to load config from DB: {e}")
            raise
        with self._lock:
            self._cache = dict(values)
            self._loaded = True
        logger.info(f"ConfigService: loaded {len(values)} DB-stored config keys")

    def invalidate(self) -> None:
        """Force a cache refresh from DB. Use after out-of-band writes."""
        self.load()

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._loaded

    # ── Resolution ────────────────────────────────────────────────────────

    def _resolve_raw(self, key: str) -> Tuple[str, str]:
        """Return ``(raw_value, source)`` where source is db | env | default | bootstrap."""
        defn = CONFIG_REGISTRY.get(key)
        if defn is None:
            raise KeyError(f"Unknown config key: {key}")

        env_var = ENV_MAP.get(key)

        if defn.bootstrap:
            if env_var:
                env_val = os.environ.get(env_var)
                if env_val is not None:
                    return env_val, "bootstrap"
            return defn.default, "bootstrap"

        with self._lock:
            db_val = self._cache.get(key)
        if db_val is not None:
            return db_val, "db"

        if env_var:
            env_val = os.environ.get(env_var)
            if env_val is not None and env_val != "":
                return env_val, "env"

        return defn.default, "default"

    def get(self, key: str) -> Any:
        """Resolve and coerce a single key to its typed value."""
        raw, _source = self._resolve_raw(key)
        return _coerce(raw, CONFIG_REGISTRY[key].value_type, key)

    def get_metadata(self, key: str) -> Dict[str, Any]:
        """Full descriptor: typed value + flags + provenance + db audit."""
        defn = CONFIG_REGISTRY.get(key)
        if defn is None:
            raise KeyError(f"Unknown config key: {key}")
        raw, source = self._resolve_raw(key)
        value = _coerce(raw, defn.value_type, key)
        db_meta = self._port.get_db_metadata().get(key, {})
        return {
            "key": key,
            "namespace": defn.namespace,
            "value_type": defn.value_type,
            "value": value,
            "raw_value": raw,
            "default": defn.default,
            "source": source,
            "sensitive": defn.sensitive,
            "readonly": defn.readonly,
            "bootstrap": defn.bootstrap,
            "description": defn.description,
            "examples": defn.examples,
            "env_var": ENV_MAP.get(key),
            "updated_at": db_meta.get("updated_at"),
            "updated_by": db_meta.get("updated_by"),
        }

    def get_namespace(self, namespace: str) -> Dict[str, Any]:
        """All resolved typed values in a namespace."""
        defns = get_keys_for_namespace(namespace)
        return {d.key: self.get(d.key) for d in defns}

    def list_namespaces(self) -> List[str]:
        return get_namespaces()

    # ── Writes ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_writable(defn: ConfigKeyDef) -> None:
        if defn.bootstrap:
            raise ValueError(
                f"{defn.key} is a bootstrap key — must be set via env var "
                f"({ENV_MAP.get(defn.key)})"
            )
        if defn.readonly:
            raise ValueError(
                f"{defn.key} is readonly — startup-only, can't be written at runtime"
            )

    def set_value(self, key: str, value: Any, updated_by: Optional[str] = None) -> None:
        """Validate, stringify, write DB, refresh cache for a single key."""
        defn = CONFIG_REGISTRY.get(key)
        if defn is None:
            raise KeyError(f"Unknown config key: {key}")
        self._validate_writable(defn)

        raw = _stringify(value, defn.value_type, key)
        # Roundtrip-validate so we never persist a value that won't parse on read.
        _coerce(raw, defn.value_type, key)

        self._port.set_value(defn.namespace, key, raw, defn.value_type, updated_by)
        with self._lock:
            self._cache[key] = raw

    def bulk_set(
        self,
        entries: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> int:
        """Validate + write a batch of ``{key: value}``. Returns rows written."""
        prepared: List[Dict[str, Any]] = []
        for key, value in entries.items():
            defn = CONFIG_REGISTRY.get(key)
            if defn is None:
                raise KeyError(f"Unknown config key: {key}")
            self._validate_writable(defn)
            raw = _stringify(value, defn.value_type, key)
            _coerce(raw, defn.value_type, key)
            prepared.append({
                "namespace": defn.namespace,
                "key": key,
                "value": raw,
                "value_type": defn.value_type,
                "updated_by": updated_by,
            })

        if not prepared:
            return 0

        count = self._port.bulk_set(prepared)
        with self._lock:
            for p in prepared:
                self._cache[p["key"]] = p["value"]
        return count

    # ── Export / Import ───────────────────────────────────────────────────

    def export_all(self, include_sensitive: bool = False) -> List[Dict[str, Any]]:
        """Every registry key with its resolved value + metadata.

        Sensitive values are masked unless ``include_sensitive=True``.
        """
        rows: List[Dict[str, Any]] = []
        db_meta = self._port.get_db_metadata()
        for key, defn in sorted(CONFIG_REGISTRY.items()):
            raw, source = self._resolve_raw(key)
            value = _coerce(raw, defn.value_type, key)
            display_value = (
                _SENSITIVE_MASK
                if (defn.sensitive and not include_sensitive and raw)
                else value
            )
            meta = db_meta.get(key, {})
            rows.append({
                "key": key,
                "namespace": defn.namespace,
                "value_type": defn.value_type,
                "value": display_value,
                "default": defn.default,
                "source": source,
                "sensitive": defn.sensitive,
                "readonly": defn.readonly,
                "bootstrap": defn.bootstrap,
                "updated_at": meta.get("updated_at"),
                "updated_by": meta.get("updated_by"),
            })
        return rows

    def compute_preview(self, entries: Dict[str, Any]) -> List[Dict[str, Any]]:
        """For each ``{key: value}`` proposed, return a row describing what
        the change would do.

        Rows surface ``current``, ``proposed``, and a ``will_change`` flag,
        plus the readonly / bootstrap / sensitive flags so the UI can mark
        rejected rows. Per-key validation errors are returned in ``error``
        rather than raised — the preview never half-fails.
        """
        rows: List[Dict[str, Any]] = []
        for key, value in entries.items():
            defn = CONFIG_REGISTRY.get(key)
            if defn is None:
                rows.append({
                    "key": key,
                    "error": "unknown key",
                    "will_change": False,
                })
                continue

            row: Dict[str, Any] = {
                "key": key,
                "namespace": defn.namespace,
                "value_type": defn.value_type,
                "sensitive": defn.sensitive,
                "readonly": defn.readonly,
                "bootstrap": defn.bootstrap,
            }

            try:
                self._validate_writable(defn)
            except ValueError as e:
                row["error"] = str(e)
                row["will_change"] = False
                rows.append(row)
                continue

            try:
                raw_proposed = _stringify(value, defn.value_type, key)
                proposed = _coerce(raw_proposed, defn.value_type, key)
            except ValueError as e:
                row["error"] = str(e)
                row["will_change"] = False
                rows.append(row)
                continue

            current_raw, current_source = self._resolve_raw(key)
            current = _coerce(current_raw, defn.value_type, key)
            row["current"] = current
            row["current_source"] = current_source
            row["proposed"] = proposed
            row["will_change"] = current_raw != raw_proposed
            rows.append(row)
        return rows

    def import_entries(
        self,
        entries: Dict[str, Any],
        imported_by: Optional[str] = None,
        snapshot_first: bool = True,
    ) -> Dict[str, Any]:
        """Bulk apply ``{key: value}``. Optionally snapshot first.

        Returns ``{"written": n, "snapshot_id": id|None}``. The snapshot is
        taken before the write so a failed import is recoverable.
        """
        snapshot_id: Optional[int] = None
        if snapshot_first:
            snapshot_id = self.create_snapshot(
                name="pre-import",
                description="Auto-captured before config import",
                trigger="pre_import",
                created_by=imported_by,
            )
        written = self.bulk_set(entries, updated_by=imported_by)
        return {"written": written, "snapshot_id": snapshot_id}

    # ── Snapshots ─────────────────────────────────────────────────────────

    def create_snapshot(
        self,
        name: str,
        description: Optional[str] = None,
        trigger: str = "manual",
        created_by: Optional[str] = None,
        parent_snapshot_id: Optional[int] = None,
    ) -> int:
        """Capture every DB-stored row into a new snapshot. Returns the id."""
        rows = self._port.export_all()
        payload_rows = [
            {
                "namespace": r["namespace"],
                "key": r["key"],
                "value": r["value"],
                "value_type": r["value_type"],
            }
            for r in rows
        ]
        return self._snapshot_port.create(
            name=name,
            description=description,
            trigger=trigger,
            payload=json.dumps(payload_rows),
            key_count=len(payload_rows),
            created_by=created_by,
            parent_snapshot_id=parent_snapshot_id,
        )

    def list_snapshots(
        self,
        limit: int = 50,
        offset: int = 0,
        trigger: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "items": self._snapshot_port.list(limit, offset, trigger),
            "total": self._snapshot_port.count(trigger),
        }

    def get_snapshot(
        self,
        snapshot_id: int,
        include_payload: bool = False,
    ) -> Optional[Dict[str, Any]]:
        return self._snapshot_port.get(snapshot_id, include_payload=include_payload)

    def delete_snapshot(self, snapshot_id: int) -> bool:
        return self._snapshot_port.delete(snapshot_id)

    def restore_snapshot(
        self,
        snapshot_id: int,
        restored_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Take a pre_rollback snapshot, then replay the target snapshot.

        The pre_rollback snapshot links to ``snapshot_id`` via
        ``parent_snapshot_id`` so the chain is reversible.
        """
        target = self._snapshot_port.get(snapshot_id, include_payload=True)
        if target is None:
            raise KeyError(f"Snapshot {snapshot_id} not found")

        try:
            payload_rows = json.loads(target["payload"])
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"Snapshot {snapshot_id} has malformed payload: {e}")

        pre_id = self.create_snapshot(
            name=f"pre-rollback-of-{snapshot_id}",
            description=f"Auto-captured before restoring snapshot {snapshot_id}",
            trigger="pre_rollback",
            created_by=restored_by,
            parent_snapshot_id=snapshot_id,
        )

        prepared = [
            {
                "namespace": r["namespace"],
                "key": r["key"],
                "value": r["value"],
                "value_type": r["value_type"],
                "updated_by": restored_by,
            }
            for r in payload_rows
        ]
        written = self._port.bulk_set(prepared) if prepared else 0
        self.load()
        return {
            "restored": written,
            "pre_rollback_snapshot_id": pre_id,
            "from_snapshot_id": snapshot_id,
        }

    def prune_snapshots(self, keep: int) -> int:
        """Drop oldest non-manual snapshots, keeping the newest ``keep``."""
        return self._snapshot_port.prune_oldest_non_manual(keep)

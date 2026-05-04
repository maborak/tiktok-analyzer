"""Admin Configuration Routes — typed registry-backed config + snapshots.

Sits on top of :class:`ConfigService`. Mounted under ``/admin/configuration``
to avoid colliding with ``/admin/config`` (raw app_config CRUD). Handles
sections / keys / preview / import / export and the snapshot history that
backs the rollback flow.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from domain.entities.config_registry import CONFIG_REGISTRY
from routes.admin.general import get_admin_user_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/configuration", tags=["Admin Configuration"])

# Injected via admin/__init__.py set_dependencies()
config_service = None  # ConfigService instance


class KeyValueRequest(BaseModel):
    value: Any


class BulkRequest(BaseModel):
    entries: Dict[str, Any] = Field(default_factory=dict)


class ImportRequest(BaseModel):
    entries: Dict[str, Any] = Field(default_factory=dict)
    snapshot_first: bool = True


class PreviewRequest(BaseModel):
    entries: Dict[str, Any] = Field(default_factory=dict)


class SnapshotCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None


def _require_service():
    if config_service is None:
        raise HTTPException(503, "Config service not available")
    return config_service


def _admin_email(admin) -> str:
    return getattr(admin, "email", None) or "admin"


# ── Sections / keys ────────────────────────────────────────────────────────

@router.get("/sections")
async def list_sections(_admin=Depends(get_admin_user_dependency)):
    """List namespaces with the number of keys in each."""
    svc = _require_service()
    counts: Dict[str, int] = {}
    for defn in CONFIG_REGISTRY.values():
        counts[defn.namespace] = counts.get(defn.namespace, 0) + 1
    return {
        "sections": [
            {"namespace": ns, "key_count": counts[ns]}
            for ns in svc.list_namespaces()
        ]
    }


@router.get("/sections/{namespace}")
async def get_section(namespace: str, _admin=Depends(get_admin_user_dependency)):
    """All keys in a namespace, fully resolved with metadata."""
    svc = _require_service()
    defns = [d for d in CONFIG_REGISTRY.values() if d.namespace == namespace]
    if not defns:
        raise HTTPException(404, f"Unknown namespace: {namespace}")
    keys = sorted(d.key for d in defns)
    return {
        "namespace": namespace,
        "keys": [svc.get_metadata(k) for k in keys],
    }


@router.get("/keys/{key}")
async def get_key(key: str, _admin=Depends(get_admin_user_dependency)):
    """Single key — resolved value + flags + audit."""
    svc = _require_service()
    try:
        return svc.get_metadata(key)
    except KeyError:
        raise HTTPException(404, f"Unknown config key: {key}")


@router.put("/keys/{key}")
async def set_key(
    key: str,
    body: KeyValueRequest,
    admin=Depends(get_admin_user_dependency),
):
    """Set a single key. Refuses bootstrap + readonly keys."""
    svc = _require_service()
    try:
        svc.set_value(key, body.value, updated_by=_admin_email(admin))
    except KeyError:
        raise HTTPException(404, f"Unknown config key: {key}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    logger.info(f"Config set: {key} by {_admin_email(admin)}")
    return svc.get_metadata(key)


@router.post("/bulk")
async def bulk_set(
    body: BulkRequest,
    admin=Depends(get_admin_user_dependency),
):
    """Bulk set — single transaction at the adapter layer."""
    svc = _require_service()
    try:
        written = svc.bulk_set(body.entries, updated_by=_admin_email(admin))
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    logger.info(f"Config bulk-set: {written} keys by {_admin_email(admin)}")
    return {"written": written}


# ── Export / Import / Preview ─────────────────────────────────────────────

@router.get("/export")
async def export_config(
    include_sensitive: bool = Query(False, description="Include sensitive values "
                                                       "instead of masking them"),
    _admin=Depends(get_admin_user_dependency),
):
    """Every registry key with its resolved value. Sensitive values mask
    to '***' unless ``include_sensitive=true``."""
    svc = _require_service()
    return {"entries": svc.export_all(include_sensitive=include_sensitive)}


@router.post("/import")
async def import_config(
    body: ImportRequest,
    admin=Depends(get_admin_user_dependency),
):
    """Bulk import. Auto-snapshots before writing unless ``snapshot_first=false``."""
    svc = _require_service()
    try:
        result = svc.import_entries(
            body.entries,
            imported_by=_admin_email(admin),
            snapshot_first=body.snapshot_first,
        )
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    logger.info(f"Config import: {result['written']} keys, "
                f"snapshot={result['snapshot_id']} by {_admin_email(admin)}")
    return result


@router.post("/preview")
async def preview_changes(
    body: PreviewRequest,
    _admin=Depends(get_admin_user_dependency),
):
    """Diff proposed entries against current values — no writes.

    Per-key validation errors land in ``rows[i].error`` rather than failing
    the whole preview.
    """
    svc = _require_service()
    return {"rows": svc.compute_preview(body.entries)}


# ── Snapshots ──────────────────────────────────────────────────────────────

@router.post("/snapshots")
async def create_snapshot(
    body: SnapshotCreateRequest,
    admin=Depends(get_admin_user_dependency),
):
    """Manual snapshot of the current DB-stored config."""
    svc = _require_service()
    snap_id = svc.create_snapshot(
        name=body.name,
        description=body.description,
        trigger="manual",
        created_by=_admin_email(admin),
    )
    logger.info(f"Config snapshot created: id={snap_id} name={body.name!r} "
                f"by {_admin_email(admin)}")
    return svc.get_snapshot(snap_id)


@router.get("/snapshots")
async def list_snapshots(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    trigger: Optional[str] = Query(None, description="manual | pre_import | "
                                                     "pre_seed | pre_rollback"),
    _admin=Depends(get_admin_user_dependency),
):
    svc = _require_service()
    return svc.list_snapshots(limit=limit, offset=offset, trigger=trigger)


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(
    snapshot_id: int,
    include_payload: bool = Query(False, description="Include the JSON payload "
                                                     "(usually omitted for the list view)"),
    _admin=Depends(get_admin_user_dependency),
):
    svc = _require_service()
    snap = svc.get_snapshot(snapshot_id, include_payload=include_payload)
    if snap is None:
        raise HTTPException(404, f"Snapshot {snapshot_id} not found")
    return snap


@router.delete("/snapshots/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: int,
    admin=Depends(get_admin_user_dependency),
):
    svc = _require_service()
    if not svc.delete_snapshot(snapshot_id):
        raise HTTPException(404, f"Snapshot {snapshot_id} not found")
    logger.info(f"Config snapshot deleted: id={snapshot_id} by {_admin_email(admin)}")
    return {"deleted": True}


@router.post("/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    snapshot_id: int,
    admin=Depends(get_admin_user_dependency),
):
    """Replay a snapshot. Creates a pre_rollback snapshot first so the
    rollback is itself reversible."""
    svc = _require_service()
    try:
        result = svc.restore_snapshot(snapshot_id, restored_by=_admin_email(admin))
    except KeyError:
        raise HTTPException(404, f"Snapshot {snapshot_id} not found")
    except ValueError as e:
        raise HTTPException(500, f"Snapshot restore failed: {e}")
    logger.info(f"Config snapshot restored: id={snapshot_id} -> "
                f"{result['restored']} keys, pre_rollback="
                f"{result['pre_rollback_snapshot_id']} by {_admin_email(admin)}")
    return result


@router.post("/snapshots/prune")
async def prune_snapshots(
    keep: int = Query(20, ge=0, le=1000, description="Newest non-manual "
                                                     "snapshots to keep"),
    admin=Depends(get_admin_user_dependency),
):
    """Drop oldest non-manual snapshots, keeping the newest ``keep``.
    Manual snapshots are exempt — the user named them on purpose."""
    svc = _require_service()
    deleted = svc.prune_snapshots(keep=keep)
    logger.info(f"Config snapshots pruned: deleted={deleted} keep={keep} "
                f"by {_admin_email(admin)}")
    return {"deleted": deleted, "kept_min": keep}

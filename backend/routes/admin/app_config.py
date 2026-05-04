"""
Admin Generic Config CRUD Routes

Provides namespace-scoped key/value configuration management.
Supports global and per-worker config entries.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from routes.admin.general import get_admin_user_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["Admin Config"])

# Injected via admin/__init__.py set_dependencies()
app_config_adapter = None  # AppConfigAdapter instance


class AppConfigUpsertRequest(BaseModel):
    value: str
    value_type: str = "string"  # int, string, boolean
    scope: str = "global"       # global, worker
    scope_id: Optional[str] = None


@router.get("/namespaces")
async def list_namespaces(
    _admin=Depends(get_admin_user_dependency),
):
    """List all distinct config namespaces."""
    if not app_config_adapter:
        raise HTTPException(503, "Config service not available")
    return {"namespaces": app_config_adapter.get_all_namespaces()}


@router.get("/{namespace}")
async def get_namespace_config(
    namespace: str,
    scope: str = Query("all", description="Filter by scope: all, global, worker"),
    scope_id: Optional[str] = Query(None, description="Worker ID when scope=worker"),
    _admin=Depends(get_admin_user_dependency),
):
    """Get all config entries for a namespace, optionally filtered by scope."""
    if not app_config_adapter:
        raise HTTPException(503, "Config service not available")
    entries = app_config_adapter.get_by_namespace(
        namespace=namespace, scope=scope, scope_id=scope_id
    )
    return {"entries": entries, "namespace": namespace}


@router.put("/{namespace}/{key}")
async def upsert_config_value(
    namespace: str,
    key: str,
    body: AppConfigUpsertRequest,
    admin=Depends(get_admin_user_dependency),
):
    """Create or update a config entry. Use /admin/queue/config for queue namespace."""
    if not app_config_adapter:
        raise HTTPException(503, "Config service not available")

    # Block writes to 'queue' namespace — must go through the validated queue config endpoint
    if namespace == "queue":
        raise HTTPException(
            400,
            "Use PUT /admin/queue/config for queue namespace (validates constraints)"
        )

    admin_email = getattr(admin, "email", None) or "admin"
    result = app_config_adapter.set_value(
        namespace=namespace,
        key=key.upper(),
        value=body.value,
        value_type=body.value_type,
        scope=body.scope,
        scope_id=body.scope_id,
        updated_by=admin_email,
    )
    logger.info(f"Config updated: {namespace}.{key.upper()} "
                f"[{body.scope}:{body.scope_id}] by {admin_email}")
    return result


@router.delete("/{namespace}/{key}")
async def delete_config_value(
    namespace: str,
    key: str,
    scope: str = Query("global"),
    scope_id: Optional[str] = Query(None),
    _admin=Depends(get_admin_user_dependency),
):
    """Delete a config entry."""
    if not app_config_adapter:
        raise HTTPException(503, "Config service not available")

    deleted = app_config_adapter.delete_value(
        namespace=namespace, key=key.upper(), scope=scope, scope_id=scope_id
    )
    if not deleted:
        raise HTTPException(404, "Config entry not found")
    return {"deleted": True}

"""
Admin Event Monitoring Routes

Provides paginated event listing, aggregate summary, event config management,
trace querying, and handler info endpoints for the hook_events audit trail.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import logging

from routes.admin.general import get_admin_user_dependency
from ports.data_persistence import DataPersistencePort

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring/events", tags=["Admin Event Monitor"])

# Injected via admin/__init__.py set_dependencies()
data_persistence_adapter: Optional[DataPersistencePort] = None
event_config_service = None  # EventConfigService instance


# --- Pydantic models ---

class EventConfigUpdate(BaseModel):
    event_type: str
    handler_name: str
    enabled: bool

class EventConfigBulkUpdate(BaseModel):
    updates: List[EventConfigUpdate]


# --- Existing endpoints ---

@router.get("")
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    event_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    _admin=Depends(get_admin_user_dependency),
):
    """
    List hook events with optional filters and pagination.
    Returns sanitized event data (sensitive fields are stripped at write time).
    """
    return data_persistence_adapter.get_hook_events(
        page=page,
        page_size=page_size,
        event_type=event_type,
        source=source,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/summary")
async def events_summary(
    window_hours: int = Query(24, ge=1, le=720),
    _admin=Depends(get_admin_user_dependency),
):
    """
    Aggregate event counts grouped by event_type and source
    for the given time window (in hours).
    """
    return data_persistence_adapter.get_hook_events_summary(window_hours=window_hours)


# --- Event Config endpoints ---

@router.get("/config")
async def get_event_config(
    _admin=Depends(get_admin_user_dependency),
):
    """
    Return full event config matrix, registered handlers, and known event types.
    """
    from ports.hooks.base_handler import HookEventType
    from ports.hooks import hook_manager

    configs = event_config_service.get_configs_list() if event_config_service else []

    handlers_info = []
    for h in hook_manager.get_handlers():
        handlers_info.append(h.name)

    event_types = [e.value for e in HookEventType if e.value != "custom"]

    return {
        "configs": configs,
        "handlers": handlers_info,
        "event_types": event_types,
    }


@router.put("/config")
async def update_event_config(
    body: EventConfigUpdate,
    _admin=Depends(get_admin_user_dependency),
):
    """Upsert a single event config entry."""
    if not event_config_service:
        return {"error": "Event config service not available"}
    result = event_config_service.set_config(body.event_type, body.handler_name, body.enabled)
    return result


@router.put("/config/bulk")
async def bulk_update_event_config(
    body: EventConfigBulkUpdate,
    _admin=Depends(get_admin_user_dependency),
):
    """Bulk upsert event config entries."""
    if not event_config_service:
        return {"error": "Event config service not available"}
    updates = [u.model_dump() for u in body.updates]
    count = event_config_service.bulk_set_configs(updates)
    return {"updated": count}


# --- Trace endpoints ---

@router.get("/trace/{trace_id}")
async def get_trace(
    trace_id: str,
    _admin=Depends(get_admin_user_dependency),
):
    """Return all events for a given trace_id, ordered chronologically."""
    return data_persistence_adapter.get_events_by_trace_id(trace_id)


@router.get("/traces")
async def list_traces(
    country_code: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin=Depends(get_admin_user_dependency),
):
    """Return recent traces grouped by trace_id with summary info."""
    return data_persistence_adapter.get_recent_traces(
        country_code=country_code,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


# --- Handlers info ---

@router.get("/handlers")
async def list_handlers(
    _admin=Depends(get_admin_user_dependency),
):
    """Return registered handler names and their subscribed events."""
    from ports.hooks import hook_manager

    handlers = []
    for h in hook_manager.get_handlers():
        subscribed = h.subscribed_events
        # Convert enums to strings
        subscribed_strs = [
            getattr(e, "value", str(e)) for e in subscribed
        ]
        handlers.append({
            "name": h.name,
            "enabled": h.enabled,
            "subscribed_events": subscribed_strs,
        })
    return {"handlers": handlers}

"""Admin endpoints for the TikTok-bot module.

Subscriptions CRUD, room/event read API, and a WebSocket fan-out for
real-time events. All admin-protected via the framework's RBAC.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field

from domain.entities.auth_models import AuthContext
from utils.security.rbac import rbac

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin TikTok"])

# Dependency placeholder (set via routes/admin/__init__.set_dependencies).
tiktok_service = None  # type: ignore[assignment]
config_service = None  # type: ignore[assignment]


# ── request / response models ───────────────────────────────────────


class SubscriptionRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    enabled: bool = True


class SubscriptionUpdate(BaseModel):
    enabled: bool


class SubscriptionPublicUpdate(BaseModel):
    is_public: bool


# Note on integer types: TikTok room_ids, user_ids and our event ids are
# 64-bit BigInts that exceed Number.MAX_SAFE_INTEGER (2^53). JSON numbers
# decoded by browsers lose precision on values > 9 × 10^15. We serialize
# all such ids as strings on the wire — backend keeps native int internally.


class SubscriptionResponse(BaseModel):
    unique_id: str
    enabled: bool
    # Public-lives opt-in: when True the handle surfaces on the
    # unauthenticated /public/tiktok/lives endpoint (with a sanitized
    # subset of fields). Independent of `enabled`.
    is_public: bool = False
    state: str
    room_id: Optional[str] = None
    is_connected: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Cached public-profile fields (refreshed every ~1h by the service).
    profile_user_id: Optional[str] = None
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    verified: Optional[bool] = None
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    profile_refreshed_at: Optional[str] = None
    profile_error: Optional[str] = None
    # Centralized live-status cache (updated by worker's scraper task).
    is_live: Optional[bool] = None
    live_checked_at: Optional[str] = None
    current_room_id: Optional[str] = None


class EventResponse(BaseModel):
    id: str
    room_id: str
    user_id: Optional[str] = None
    ts: str
    type: str
    payload: dict[str, Any]


class RoomResponse(BaseModel):
    room_id: str
    host_unique_id: Optional[str]
    host_user_id: Optional[str]
    title: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    first_seen_at: Optional[str]
    last_seen_at: Optional[str]
    # Per-broadcast rollups — populated by `/lives/{handle}/rooms` so
    # the dropdown can render `💎 / ⚔ / ❤` next to each entry without
    # a follow-up query. Optional because other routes that build a
    # RoomResponse from a single Room dataclass don't have the totals.
    diamonds: Optional[int] = None
    matches: Optional[int] = None
    likes: Optional[int] = None


class HandleLookupResponse(BaseModel):
    """Preview data for the "Add Live" confirmation modal."""
    handle: str
    exists: Optional[bool] = None
    # Tri-state: True = confirmed live, False = confirmed offline,
    # None = TikTok's webcast API refused our probe (typical without auth).
    is_live: Optional[bool] = None
    nickname: Optional[str] = None
    user_id: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    room_id: Optional[str] = None
    title: Optional[str] = None
    viewer_count: Optional[int] = None
    source: Optional[str] = None
    error: Optional[str] = None
    warning: Optional[str] = None
    already_subscribed: bool = False


class GiftResponse(BaseModel):
    gift_id: str
    name: Optional[str]
    diamond_count: Optional[int]
    icon_url: Optional[str]
    streakable: Optional[bool]
    first_seen_at: Optional[str]
    last_seen_at: Optional[str]


class MatchResponse(BaseModel):
    id: int
    room_id: str
    battle_id: str
    opponents: list[dict[str, Any]] = []
    scores: dict[str, int] = {}
    settings: dict[str, Any] = {}
    winner_user_id: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    # Enrichment (computed from events): total diamonds during this match
    # and a derived host-result label ("won" / "lost" / "draw" / "ongoing").
    diamonds_total: int = 0
    result: str = "ongoing"


# ── helpers ─────────────────────────────────────────────────────────


def _require_service():
    if tiktok_service is None:
        raise HTTPException(status_code=503, detail="TikTok service unavailable")
    return tiktok_service


def _need_admin():
    return rbac.require_any_read_only(["admin:write"])


# ── subscriptions CRUD ──────────────────────────────────────────────


@router.get("/lives/bundle")
async def lives_bundle(
    response: Response,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Single round-trip rollup for the /admin/tiktok Lives page.

    Returns `{subs, summary, totals}` — replaces the previous
    `GET /lives/summary` + `GET /lives/totals` pair, which together
    with `GET /lives` required three HTTP round-trips on cold mount
    plus a duplicate `list_subscriptions()` query inside `/lives/summary`.
    The bundle runs `list_subscriptions` once and threads the handle
    list into the parallel summary/totals fan-out.

    `GET /lives` itself stays — five other consumers (match events
    modal, gifter modal, live-detail rival pills, history page,
    `getLiveByHandle` lookup) only need the cheap subscription list
    and shouldn't pay for the heavy summary aggregation. The lives
    page is the one that needs all three pieces in lockstep.

    Service-layer caches still apply: `get_lives_summary` has a 35 s
    TTL keyed by `tuple(sorted(handles))` with a singleflight lock,
    and `get_lives_totals` has the same 35 s TTL on a single slot.
    A warm-cache hit is sub-50 ms wall-clock. The browser cache
    header lets a re-mount within the poll cycle skip the request
    entirely."""
    svc = _require_service()
    response.headers["Cache-Control"] = "private, max-age=30"
    return await svc.get_lives_bundle()


@router.get("/lives", response_model=list[SubscriptionResponse])
async def list_lives(
    response: Response,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Cheap subscription-list lookup. Used by every consumer that
    only needs handle enumeration (match events modal monitor pills,
    gifter modal favourite-state, live-detail rival pills, history
    filter, single-handle `getLiveByHandle` lookup).

    The lives page itself uses `/lives/bundle` instead, which folds
    this list together with summary + totals into a single trip.

    `Cache-Control: private, max-age=15` lets a re-mount within the
    same 30 s window skip the wire entirely. Lower than the bundle's
    30 s cap because this endpoint's freshness matters for the
    post-CRUD `refresh()` path — operators expect a just-added
    subscription to surface immediately on the next paint."""
    svc = _require_service()
    response.headers["Cache-Control"] = "private, max-age=15"
    return await svc.list_subscriptions()


@router.get("/lookup", response_model=HandleLookupResponse)
async def lookup_handle(
    handle: str = Query(..., min_length=1, max_length=64, description="@handle to preview"),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    data = await svc.lookup_handle(handle)
    return HandleLookupResponse(**data)


@router.post("/lives", response_model=SubscriptionResponse)
async def create_live(
    req: SubscriptionRequest,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    svc = _require_service()
    sub = await svc.create_subscription(req.username, enabled=req.enabled)
    items = await svc.list_subscriptions()
    for s in items:
        if s["unique_id"] == sub.unique_id:
            return s
    raise HTTPException(status_code=500, detail="subscription created but not found")


@router.patch("/lives/{handle}", response_model=SubscriptionResponse)
async def patch_live(
    handle: str,
    update: SubscriptionUpdate,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    svc = _require_service()
    sub = await svc.set_enabled(handle, update.enabled)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    items = await svc.list_subscriptions()
    for s in items:
        if s["unique_id"] == sub.unique_id:
            return s
    raise HTTPException(status_code=500, detail="subscription updated but not found")


@router.patch("/lives/{handle}/public", status_code=status.HTTP_204_NO_CONTENT)
async def patch_live_public(
    handle: str,
    update: SubscriptionPublicUpdate,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Flip the `is_public` flag for a subscription. When true the
    handle surfaces on the unauthenticated /public/tiktok/lives
    endpoint (sanitized payload). 204 on success, 404 if the handle
    isn't tracked.

    Independent of `enabled` — a paused-but-public sub stays listed,
    but its live state will read offline until the listener resumes.
    """
    svc = _require_service()
    handle = handle.lstrip("@")
    try:
        svc.set_subscription_public(handle, bool(update.is_public))
    except LookupError:
        raise HTTPException(status_code=404, detail="subscription not found")
    # 204 — caller polls /admin/tiktok/lives if it needs the new row.
    return None


@router.post("/lives/{handle}/refresh", response_model=SubscriptionResponse)
async def refresh_live_profile(
    handle: str,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Force-refresh the cached profile data for one subscription."""
    svc = _require_service()
    handle = handle.lstrip("@")
    await svc.refresh_profile(handle)
    items = await svc.list_subscriptions()
    for s in items:
        if s["unique_id"] == handle:
            return s
    raise HTTPException(status_code=404, detail="subscription not found")


@router.delete("/lives/{handle}")
async def delete_live(
    handle: str,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    svc = _require_service()
    ok = await svc.delete_subscription(handle)
    if not ok:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"ok": True}


@router.post("/lives/{handle}/reconnect")
async def reconnect_live(
    handle: str,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Force the listener for `@handle` to teardown + start fresh —
    bypassing any backoff sleep its supervisor is currently parked on
    (e.g. the 3-min AgeRestricted retry, or the 30-min UserNotFound).
    Useful when the streamer just resolved an age-restriction flag and
    the admin doesn't want to wait for the next scheduled retry.

    In worker mode this is delivered via tiktok_worker_log; in API
    (in-process listener) mode it's a synchronous stop+start."""
    svc = _require_service()
    ok = await svc.request_reconnect(handle)
    if not ok:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"ok": True}


# ── rooms + events read ─────────────────────────────────────────────


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(
    room_id: int,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    room = svc.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="room not found")
    return RoomResponse(
        room_id=str(room.room_id),
        host_unique_id=room.host_unique_id,
        host_user_id=str(room.host_user_id) if room.host_user_id else None,
        title=room.title,
        started_at=room.started_at.isoformat() if room.started_at else None,
        ended_at=room.ended_at.isoformat() if room.ended_at else None,
        first_seen_at=room.first_seen_at.isoformat() if room.first_seen_at else None,
        last_seen_at=room.last_seen_at.isoformat() if room.last_seen_at else None,
    )


@router.get("/rooms/{room_id}/events", response_model=list[EventResponse])
async def list_room_events(
    room_id: int,
    type: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    before_id: Optional[int] = None,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    rows = svc.list_events(room_id, type=type, limit=limit, before_id=before_id)
    return [
        EventResponse(
            id=str(r.id or 0),
            room_id=str(r.room_id),
            user_id=str(r.user_id) if r.user_id else None,
            ts=r.ts.isoformat() if r.ts else "",
            type=r.type,
            payload=r.payload or {},
        )
        for r in rows
    ]


@router.get("/buckets/aggregated")
async def aggregated_buckets(
    room_ids: str = Query(
        ...,
        description="Comma-separated list of room ids to aggregate.",
    ),
    since: datetime = Query(..., description="Window start (inclusive)"),
    until: datetime = Query(..., description="Window end (inclusive)"),
    bucket_seconds: Optional[int] = Query(None, ge=10, le=86400),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Bucketed event series summed across multiple rooms — single
    SQL round-trip replaces the per-room parallel-fetch pattern the
    calendar's day-view used to do client-side. Returns the same
    `{starts, by_type, diamonds, diamonds_total}` shape as the
    `buckets` field of `/rooms/{room_id}/stats`, so the frontend can
    splice the response directly into the chart without reshape."""
    svc = _require_service()
    ids: list[int] = []
    for raw in (room_ids or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ids.append(int(raw))
        except ValueError:
            continue
    if not ids:
        raise HTTPException(status_code=400, detail="room_ids must be a non-empty comma-separated list of integers")
    return svc.get_aggregated_buckets(
        ids, since=since, until=until, bucket_seconds=bucket_seconds,
    )


@router.get("/lives/{handle}/calendar")
async def host_calendar(
    handle: str,
    weeks: int = Query(26, ge=1, le=104),
    tz: str = Query(
        "UTC",
        description=(
            "IANA timezone for day bucketing — events with `ts` falling on "
            "the same calendar day in this zone are grouped into one cell. "
            "A Lima viewer should pass `America/Lima` so a stream from "
            "23:55 May 6 → 02:00 May 7 (Lima) attributes its events to "
            "the correct day."
        ),
    ),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Per-day broadcast counts for the GitHub-style heatmap on the
    live-detail page. Window ends today and reaches `weeks` weeks back,
    snapped to Monday so the 7×N grid is rectangular."""
    svc = _require_service()
    handle = handle.lstrip("@")
    return svc.host_calendar(handle, weeks=weeks, tz=tz)


@router.get("/lives/{handle}/rooms", response_model=list[RoomResponse])
async def list_host_rooms(
    handle: str,
    limit: int = Query(50, ge=1, le=200),
    since: Optional[datetime] = Query(
        None,
        description=(
            "Optional UTC lower bound for diamonds / matches / likes "
            "totals. The day-picker modal passes this so a broadcast "
            "that spanned midnight only contributes the slice on the "
            "selected calendar day."
        ),
    ),
    until: Optional[datetime] = Query(
        None,
        description="Optional UTC upper bound for totals (see `since`).",
    ),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    handle = handle.lstrip("@")
    rooms = svc.list_rooms_for_host(handle, limit=limit)
    # Per-room rollups (diamonds / matches / likes) so the dropdown
    # selector can show them inline. One extra round-trip; the SQL
    # itself is a single CTE join scoped to this host's rooms. When
    # `since` / `until` are provided, totals are clipped to that
    # window so the modal chips match the day-aggregate chart.
    totals = (
        svc.room_totals([r.room_id for r in rooms], since=since, until=until)
        if rooms else {}
    )
    return [
        RoomResponse(
            room_id=str(r.room_id),
            host_unique_id=r.host_unique_id,
            host_user_id=str(r.host_user_id) if r.host_user_id else None,
            title=r.title,
            started_at=r.started_at.isoformat() if r.started_at else None,
            ended_at=r.ended_at.isoformat() if r.ended_at else None,
            first_seen_at=r.first_seen_at.isoformat() if r.first_seen_at else None,
            last_seen_at=r.last_seen_at.isoformat() if r.last_seen_at else None,
            diamonds=totals.get(int(r.room_id), {}).get("diamonds"),
            matches=totals.get(int(r.room_id), {}).get("matches"),
            likes=totals.get(int(r.room_id), {}).get("likes"),
        )
        for r in rooms
    ]


# ── gift catalog ────────────────────────────────────────────────────


@router.get("/gifts", response_model=list[GiftResponse])
async def list_gifts(
    limit: int = Query(200, ge=1, le=1000),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    gifts = svc.list_gifts(limit=limit)
    return [
        GiftResponse(
            gift_id=str(g.gift_id),
            name=g.name,
            diamond_count=g.diamond_count,
            icon_url=g.icon_url,
            streakable=g.streakable,
            first_seen_at=g.first_seen_at.isoformat() if g.first_seen_at else None,
            last_seen_at=g.last_seen_at.isoformat() if g.last_seen_at else None,
        )
        for g in gifts
    ]


# ── listener pool status + control ──────────────────────────────────


class ListenerSessionStatus(BaseModel):
    handle: str
    state: str
    events_total: int
    last_event_at: Optional[str] = None
    last_event_age_s: Optional[float] = None
    # Seconds remaining before this session's slot is recycled by the
    # reconcile loop's offline-release hysteresis. None when the
    # session isn't being watched for release.
    recycle_release_in_s: Optional[float] = None
    # Loss-detection metrics. `gaps_count` = times we saw a non-contiguous
    # offset jump within a single connection. `gaps_total_missed` = sum of
    # (delta-1) across all gaps. `disconnect_count` is the other loss
    # boundary — events lost while reconnecting aren't visible as gaps.
    messages_observed: Optional[int] = None
    gaps_count: Optional[int] = None
    gaps_total_missed: Optional[int] = None
    last_gap_size: Optional[int] = None
    last_gap_age_s: Optional[float] = None
    disconnect_count: Optional[int] = None
    connect_count: Optional[int] = None
    connection_uptime_s: Optional[float] = None
    # Allow extra keys silently — the metadata snapshot can carry
    # fields the client doesn't render yet (e.g. `room_id`, error
    # detail) without us redeclaring every one.
    model_config = {"extra": "ignore"}


class RedisStatus(BaseModel):
    """Real-time fan-out depends on Redis pub/sub. When unavailable in
    worker mode, DB persistence still works but the live admin UI loses
    real-time pushes (it falls back to polling)."""
    available: bool
    url: Optional[str] = None  # masked
    error: Optional[str] = None
    # True when fan-out is actually load-bearing (worker mode). In
    # `in_process` mode the API has the events in-memory and Redis is
    # not on the live-update path.
    required_for_live_updates: bool


class WorkerRowStatus(BaseModel):
    """One worker registry row (multi-worker view)."""
    id: int
    worker_key: str
    host: str
    pid: int
    status: str                                  # 'running' | 'paused' | 'stopped' | 'stale'
    capacity: int
    sessions_count: int
    # Subset of `sessions_count` actually CONNECTED right now. The UI
    # uses this to surface "12 live / 30 slots" so the dashboard
    # doesn't look stuck when capacity is held by offline subs.
    connected_session_count: Optional[int] = None
    started_at: Optional[str] = None
    last_heartbeat_at: Optional[str] = None
    heartbeat_age_s: Optional[float] = None
    alive: bool
    sessions: list[ListenerSessionStatus] = []


class ListenerStatusResponse(BaseModel):
    mode: str                                  # "in_process" | "worker"
    api_passive: bool                          # True iff this API is in worker mode
    worker_alive: Optional[bool] = None        # legacy aggregate: True iff any worker is alive
    worker_pid: Optional[int] = None           # legacy: any-alive worker's PID
    worker_uptime_s: Optional[float] = None
    worker_paused: Optional[bool] = None
    worker_heartbeat_age_s: Optional[float] = None
    worker_heartbeat_source: Optional[str] = None
    sessions: list[ListenerSessionStatus] = []  # legacy union of all workers' sessions
    redis: RedisStatus
    # Multi-worker view: every registered worker (running, paused, stopped,
    # or stale) with its own session list. Empty when mode=in_process.
    workers: list[WorkerRowStatus] = []


@router.get("/listener/status", response_model=ListenerStatusResponse)
async def listener_status(
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Listener-pool health snapshot. Source depends on mode:
      - `in_process`: snapshot from the API's own service.
      - `worker`: heartbeat from Redis/file + lockfile PID.
    """
    import os as _os
    import time as _time
    from adapters.tiktok_listener_status import (
        read_heartbeat, read_lockfile_pid, is_pid_alive,
    )

    svc = _require_service()
    mode = (_os.getenv("PHOVEU_BACKEND_TIKTOK_LISTENER_MODE", "in_process")
            .strip().lower()) or "in_process"

    redis = await _probe_redis_status(required_for_live=(mode == "worker"))

    if mode != "worker":
        # In-process: the API IS the listener; ask its service directly.
        local = svc.get_listener_status_local()
        return ListenerStatusResponse(
            mode="in_process",
            api_passive=False,
            worker_alive=None,
            worker_pid=local.get("pid"),
            worker_uptime_s=local.get("uptime_s"),
            worker_paused=local.get("paused"),
            sessions=[ListenerSessionStatus(**s) for s in local.get("sessions", [])],
            redis=redis,
        )

    # Worker mode: query the DB registry (canonical multi-worker source).
    # Fall back to the heartbeat file for backward-compat with workers
    # that haven't registered yet.
    workers: list[WorkerRowStatus] = []
    aggregate_sessions: list[ListenerSessionStatus] = []
    aggregate_alive = False
    aggregate_pid: Optional[int] = None
    aggregate_uptime: Optional[float] = None
    aggregate_paused: Optional[bool] = None
    aggregate_age: Optional[float] = None

    try:
        # Best-effort stale-reaper at read time so the UI never shows a
        # ghost worker for more than 30s after its heartbeat dies.
        try:
            svc._persistence.reap_stale_workers(stale_after_seconds=30)
        except Exception:
            logger.debug("reap_stale_workers in status endpoint failed", exc_info=True)
        rows = svc._persistence.list_workers()
    except Exception:
        logger.exception("list_workers failed in listener_status")
        rows = []

    now_ts = _time.time()
    for w in rows:
        last_hb = w.last_heartbeat_at
        age_s: Optional[float] = None
        if last_hb is not None:
            try:
                age_s = max(0.0, now_ts - last_hb.timestamp())
            except Exception:
                age_s = None
        alive_w = (w.status == "running" or w.status == "paused") and (
            age_s is not None and age_s < 30.0
        )
        meta = w.metadata or {}
        sess_list = meta.get("sessions") or []
        sess_models = [ListenerSessionStatus(**s) for s in sess_list]
        workers.append(WorkerRowStatus(
            id=w.id or 0,
            worker_key=w.worker_key,
            host=w.host,
            pid=w.pid,
            status=w.status,
            capacity=w.capacity,
            sessions_count=w.sessions_count,
            connected_session_count=meta.get("connected_session_count"),
            started_at=w.started_at.isoformat() if w.started_at else None,
            last_heartbeat_at=w.last_heartbeat_at.isoformat() if w.last_heartbeat_at else None,
            heartbeat_age_s=age_s,
            alive=alive_w,
            sessions=sess_models,
        ))
        aggregate_sessions.extend(sess_models)
        if alive_w:
            aggregate_alive = True
            if aggregate_pid is None:
                aggregate_pid = w.pid
                aggregate_uptime = float(meta.get("uptime_s")) if meta.get("uptime_s") else None
                aggregate_paused = bool(meta.get("paused")) if meta.get("paused") is not None else None
                aggregate_age = age_s

    # Legacy file-based fallback when no rows exist yet (just-restarted
    # worker before its first heartbeat tick).
    if not workers:
        hb = await read_heartbeat()
        if hb is not None:
            written_at = float(hb.get("written_at") or 0)
            aggregate_age = max(0.0, _time.time() - written_at) if written_at else None
            aggregate_alive = aggregate_age is not None and aggregate_age < 30.0
            aggregate_pid = hb.get("pid")
            aggregate_uptime = hb.get("uptime_s")
            aggregate_paused = hb.get("paused")
            aggregate_sessions = [
                ListenerSessionStatus(**s) for s in (hb.get("sessions") or [])
            ]

    return ListenerStatusResponse(
        mode="worker",
        api_passive=True,
        worker_alive=aggregate_alive,
        worker_pid=aggregate_pid,
        worker_uptime_s=aggregate_uptime,
        worker_paused=aggregate_paused,
        worker_heartbeat_age_s=aggregate_age,
        worker_heartbeat_source="db" if workers else "file",
        sessions=aggregate_sessions,
        workers=workers,
        redis=redis,
    )


async def _probe_redis_status(*, required_for_live: bool) -> RedisStatus:
    """Best-effort Redis health probe. We try a PING with a short timeout
    so a flaky Redis can't slow down the status endpoint."""
    from utils.redis_client import get_redis, _redis_url  # type: ignore
    url_for_display: Optional[str] = None
    if _redis_url:
        # Mask credentials: strip user:pass@ from the URL.
        try:
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(_redis_url)
            netloc = parts.hostname or ""
            if parts.port:
                netloc = f"{netloc}:{parts.port}"
            url_for_display = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
        except Exception:
            url_for_display = None

    r = get_redis()
    if r is None:
        return RedisStatus(
            available=False,
            url=url_for_display,
            error="Not configured" if not _redis_url else "Connection unavailable",
            required_for_live_updates=required_for_live,
        )
    try:
        await asyncio.wait_for(r.ping(), timeout=0.5)
        return RedisStatus(
            available=True,
            url=url_for_display,
            required_for_live_updates=required_for_live,
        )
    except Exception as e:
        return RedisStatus(
            available=False,
            url=url_for_display,
            error=f"PING failed: {e}",
            required_for_live_updates=required_for_live,
        )


def _set_listener_target(*, desired_status: str | None, command: str | None,
                         worker_id: int | None) -> dict[str, Any]:
    """DB-driven worker control. Writes to `tiktok_workers.desired_status`
    and/or `command`; the worker observes on its next reconcile tick and
    acts accordingly.

    `worker_id=None` targets EVERY running worker (admin "pause all").
    Otherwise targets just one worker. Returns a list of affected worker
    ids."""
    svc = _require_service()
    rows = svc._persistence.list_workers()
    targets = [
        w for w in rows
        if (worker_id is None and w.status in ("running", "paused"))
        or (worker_id is not None and w.id == worker_id)
    ]
    if not targets:
        raise HTTPException(
            status_code=409,
            detail="No matching live worker(s).",
        )
    affected: list[int] = []
    for w in targets:
        ok = svc._persistence.set_worker_command(
            w.id, desired_status=desired_status, command=command,
        )
        if ok:
            affected.append(w.id)
    return {
        "ok": True,
        "affected_worker_ids": affected,
        "desired_status": desired_status,
        "command": command,
    }


@router.post("/listener/pause")
async def listener_pause(
    worker_id: int | None = None,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Stop every active session on the target worker(s). Worker stays
    alive — `desired_status='paused'`. `worker_id` query param targets
    one worker; omitted = pause every live worker."""
    import os as _os
    mode = (_os.getenv("PHOVEU_BACKEND_TIKTOK_LISTENER_MODE", "in_process")
            .strip().lower())
    if mode != "worker":
        svc = _require_service()
        return await svc.pause_all()
    return _set_listener_target(
        desired_status="paused", command=None, worker_id=worker_id,
    )


@router.post("/listener/resume")
async def listener_resume(
    worker_id: int | None = None,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Re-spawn sessions on the target worker(s)."""
    import os as _os
    mode = (_os.getenv("PHOVEU_BACKEND_TIKTOK_LISTENER_MODE", "in_process")
            .strip().lower())
    if mode != "worker":
        svc = _require_service()
        return await svc.resume_all()
    return _set_listener_target(
        desired_status="running", command=None, worker_id=worker_id,
    )


@router.post("/listener/kill")
async def listener_kill(
    worker_id: int | None = None,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Tell the target worker(s) to exit. The worker observes
    `command='kill'` on its next reconcile tick, releases assignments,
    and exits cleanly (your supervisor / systemd job restarts it)."""
    import os as _os
    mode = (_os.getenv("PHOVEU_BACKEND_TIKTOK_LISTENER_MODE", "in_process")
            .strip().lower())
    if mode != "worker":
        raise HTTPException(
            status_code=409,
            detail=(
                "Refusing to kill the API process in 'in_process' mode "
                "(would kill the API itself). Switch to worker mode "
                "(PHOVEU_BACKEND_TIKTOK_LISTENER_MODE=worker)."
            ),
        )
    return _set_listener_target(
        desired_status="stopped", command="kill", worker_id=worker_id,
    )


@router.post("/lives/{handle}/release")
async def listener_release_handle(
    handle: str,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Yank a subscription's worker assignment so another worker can
    claim it. The currently-owning worker's reconcile tick will notice
    its lease was cleared, stop the session, and the next reconcile
    pass on any worker can re-claim. Doesn't touch `enabled`."""
    svc = _require_service()
    handle = handle.lstrip("@").strip()
    ok = svc._persistence.release_subscription(handle)
    if not ok:
        raise HTTPException(status_code=404, detail=f"@{handle} not found")
    return {"ok": True, "handle": handle}


@router.get("/listener/log")
async def listener_log(
    worker_id: int | None = None,
    handle: str | None = None,
    event_prefix: str | None = None,
    limit: int = 200,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Recent worker log rows. Filters: `worker_id`, `handle`,
    `event_prefix` (matches the start of the event tag — useful for
    grouping e.g. 'profile_probe' which covers '_failed' + '_partial')."""
    svc = _require_service()
    rows = svc._persistence.list_worker_log(
        worker_id=worker_id,
        handle=handle.lstrip("@") if handle else None,
        event_prefix=event_prefix,
        limit=limit,
    )
    return [
        {
            "id": r.id,
            "worker_id": r.worker_id,
            "ts": r.ts.isoformat() if r.ts else None,
            "level": r.level,
            "event": r.event,
            "handle": r.handle,
            "detail": r.detail,
        }
        for r in rows
    ]


# ── sign-engine config ──────────────────────────────────────────────


class SignConfigResponse(BaseModel):
    """Current sign-engine settings. Sensitive values are masked unless
    the explicit `?reveal=1` query is set + the caller already had write
    permission to land on this endpoint."""
    provider: str  # "euler" | "session" | "local"
    euler_api_key: Optional[str] = None
    euler_api_key_set: bool = False
    session_id: Optional[str] = None
    session_id_set: bool = False
    session_tt_target_idc: Optional[str] = None
    local_sign_url: Optional[str] = None


class SignConfigUpdate(BaseModel):
    provider: str = Field(pattern=r"^(euler|session|local)$")
    euler_api_key: Optional[str] = None
    session_id: Optional[str] = None
    session_tt_target_idc: Optional[str] = None
    local_sign_url: Optional[str] = None


_SIGN_KEY_MAP = {
    "provider": "TIKTOK_SIGN_PROVIDER",
    "euler_api_key": "TIKTOK_EULER_API_KEY",
    "session_id": "TIKTOK_SESSION_ID",
    "session_tt_target_idc": "TIKTOK_SESSION_TT_TARGET_IDC",
}


def _mask(value: str | None) -> Optional[str]:
    """Show first 8 chars + ellipsis. Caller can re-enter to overwrite;
    we never round-trip the cleartext to the browser."""
    if not value:
        return None
    if len(value) <= 8:
        return "•" * len(value)
    return value[:8] + "•" * 8


@router.get("/sign/config", response_model=SignConfigResponse)
async def get_sign_config(
    reveal: bool = False,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Current sign-engine settings."""
    if config_service is None:
        raise HTTPException(503, "Config service unavailable")
    cs = config_service
    provider = (cs.get("TIKTOK_SIGN_PROVIDER") or "euler").strip().lower()
    euler_key = (cs.get("TIKTOK_EULER_API_KEY") or "").strip()
    session_id = (cs.get("TIKTOK_SESSION_ID") or "").strip()
    tt_idc = (cs.get("TIKTOK_SESSION_TT_TARGET_IDC") or "").strip()
    local_url = (cs.get("TIKTOK_LOCAL_SIGN_URL") or "http://127.0.0.1:21214").strip()
    return SignConfigResponse(
        provider=provider,
        euler_api_key=(euler_key if reveal else _mask(euler_key)),
        euler_api_key_set=bool(euler_key),
        session_id=(session_id if reveal else _mask(session_id)),
        session_id_set=bool(session_id),
        session_tt_target_idc=tt_idc,
        local_sign_url=local_url,
    )


class SignTestResponse(BaseModel):
    ok: bool
    user_id: Optional[str] = None
    nickname: Optional[str] = None
    unique_id: Optional[str] = None
    sec_uid: Optional[str] = None
    follower_count: Optional[int] = None
    error: Optional[str] = None


@router.post("/sign/test", response_model=SignTestResponse)
async def test_sign_config(
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Validate the currently-saved sign config.

    For session mode: probes TikTok's `passport/web/account/info/` with the
    sessionid cookie. A successful response means the cookie is valid and
    we can authenticate as the user.

    For euler mode: probes EulerStream's status endpoint with the API key.
    """
    if config_service is None:
        raise HTTPException(503, "Config service unavailable")
    cs = config_service
    provider = (cs.get("TIKTOK_SIGN_PROVIDER") or "euler").strip().lower()

    if provider == "session":
        sid = (cs.get("TIKTOK_SESSION_ID") or "").strip()
        if not sid:
            return SignTestResponse(ok=False, error="No sessionid configured.")
        return await _probe_session(sid, (cs.get("TIKTOK_SESSION_TT_TARGET_IDC") or "").strip())

    if provider == "local":
        broker_url = (cs.get("TIKTOK_LOCAL_SIGN_URL") or "http://127.0.0.1:21214").strip()
        return await _probe_local_broker(broker_url)

    # Euler: simplest validation is asking EulerStream for a sign with a
    # cheap test room. We don't have a room handy without picking one of
    # the user's subscriptions; instead just confirm reachability + that
    # the key is accepted by hitting their `/quota` endpoint when present,
    # otherwise return a non-fatal "configured" status.
    api_key = (cs.get("TIKTOK_EULER_API_KEY") or "").strip()
    return SignTestResponse(
        ok=True,
        nickname=("EulerStream API key configured" if api_key else "EulerStream free tier"),
    )


async def _probe_local_broker(broker_url: str) -> SignTestResponse:
    """Hit the broker's `/health` endpoint. Tells us whether the Electron
    sign-broker is alive on the configured port."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(broker_url.rstrip("/") + "/health")
        if r.status_code != 200:
            return SignTestResponse(
                ok=False,
                error=f"Broker reachable but returned HTTP {r.status_code}",
            )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return SignTestResponse(
            ok=True,
            nickname=body.get("status") or "Local broker reachable",
            unique_id=body.get("logged_in_as") or None,
        )
    except Exception as e:
        return SignTestResponse(
            ok=False,
            error=(
                f"Could not reach the local broker at {broker_url}. "
                f"Is the Electron client running? ({type(e).__name__}: {e})"
            ),
        )


async def _probe_session(sessionid: str, tt_target_idc: str) -> SignTestResponse:
    """Hit `tiktok.com/passport/web/account/info/` with the given cookie.
    A real signed-in account returns user_id + nickname; an expired cookie
    returns a `session_expired` error. We use TikTokLive's curl_cffi-backed
    HTTP client to carry a Chrome-like TLS fingerprint past the WAF."""
    from TikTokLive import TikTokLiveClient
    client = TikTokLiveClient(unique_id="@tiktok")  # any valid handle
    try:
        client.web.cookies.set("sessionid", sessionid)
        client.web.cookies.set("sessionid_ss", sessionid)
        client.web.cookies.set("sid_tt", sessionid)
        if tt_target_idc:
            client.web.cookies.set("tt-target-idc", tt_target_idc)
        resp = await client.web.get(
            url="https://www.tiktok.com/passport/web/account/info/",
            base_params=False,
        )
        try:
            body = resp.json()
        except Exception:
            return SignTestResponse(ok=False, error=f"Non-JSON response (HTTP {resp.status_code})")
        # message=='success' + data.user_id → valid session
        if body.get("message") == "success":
            data = body.get("data") or {}
            return SignTestResponse(
                ok=True,
                user_id=str(data.get("user_id")) if data.get("user_id") else None,
                nickname=data.get("nickname") or None,
                unique_id=data.get("unique_id") or data.get("display_id") or None,
                sec_uid=data.get("sec_uid") or None,
            )
        # message=='error' + name=='session_expired'
        err_name = ((body.get("data") or {}).get("name")) or body.get("description") or "unknown error"
        return SignTestResponse(ok=False, error=f"Session check failed: {err_name}")
    except Exception as e:
        return SignTestResponse(ok=False, error=f"{type(e).__name__}: {e}")
    finally:
        try:
            await client.web.close()
        except Exception:
            pass


@router.put("/sign/config", response_model=SignConfigResponse)
async def update_sign_config(
    body: SignConfigUpdate,
    user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Persist sign-engine settings to the typed config (DB-backed).
    Empty strings clear a value back to env / default; `None` (omitted
    field) leaves the existing value unchanged."""
    if config_service is None:
        raise HTTPException(503, "Config service unavailable")

    entries: dict[str, Any] = {"TIKTOK_SIGN_PROVIDER": body.provider}
    # Only write fields the caller actually supplied (None = no change).
    if body.euler_api_key is not None:
        entries["TIKTOK_EULER_API_KEY"] = body.euler_api_key.strip()
    if body.session_id is not None:
        entries["TIKTOK_SESSION_ID"] = body.session_id.strip()
    if body.session_tt_target_idc is not None:
        entries["TIKTOK_SESSION_TT_TARGET_IDC"] = body.session_tt_target_idc.strip()
    if body.local_sign_url is not None:
        entries["TIKTOK_LOCAL_SIGN_URL"] = body.local_sign_url.strip()

    config_service.bulk_set(entries, updated_by=getattr(user.user, "username", None) or "admin")

    # Mirror the change into the runtime CONFIG dict so already-running
    # listeners pick it up on their next reconnect without a restart.
    try:
        from config import CONFIG
        if "TIKTOK_SIGN_PROVIDER" in entries:
            CONFIG["TIKTOK_SIGN_PROVIDER"] = entries["TIKTOK_SIGN_PROVIDER"]
        for src_k, dst_k in (
            ("TIKTOK_EULER_API_KEY", "TIKTOK_EULER_API_KEY"),
            ("TIKTOK_SESSION_ID", "TIKTOK_SESSION_ID"),
            ("TIKTOK_SESSION_TT_TARGET_IDC", "TIKTOK_SESSION_TT_TARGET_IDC"),
            ("TIKTOK_LOCAL_SIGN_URL", "TIKTOK_LOCAL_SIGN_URL"),
        ):
            if src_k in entries:
                CONFIG[dst_k] = entries[src_k]
    except Exception:
        logger.exception("Failed to mirror sign-config into runtime CONFIG")

    return await get_sign_config(reveal=False, _user=user)


# ── matches ─────────────────────────────────────────────────────────


@router.get("/matches", response_model=list[MatchResponse])
async def list_matches(
    handle: Optional[str] = None,
    room_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    host = handle.lstrip("@") if handle else None
    matches = svc.list_matches(
        host_unique_id=host,
        room_id=room_id,
        limit=limit,
    )
    # Enrich each match with total diamonds during the battle and a derived
    # host-result label.
    diamonds = svc.match_diamonds_totals([m.id for m in matches if m.id is not None])
    out: list[MatchResponse] = []
    for m in matches:
        result = _derive_match_result(m, host)
        out.append(
            MatchResponse(
                id=m.id or 0,
                room_id=str(m.room_id),
                battle_id=str(m.battle_id),
                opponents=[_serialize_opponent(o) for o in (m.opponents or [])],
                scores=m.scores or {},
                settings=m.settings or {},
                winner_user_id=str(m.winner_user_id) if m.winner_user_id else None,
                started_at=m.started_at.isoformat() if m.started_at else None,
                ended_at=m.ended_at.isoformat() if m.ended_at else None,
                last_seen_at=m.last_seen_at.isoformat() if m.last_seen_at else None,
                diamonds_total=int(diamonds.get(m.id or 0, 0)),
                result=result,
            )
        )
    return out


@router.get("/matches/{match_id}", response_model=MatchResponse)
async def get_match_by_id(
    match_id: int,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Single-match fetch enriched with the same fields as the list
    endpoint (diamonds_total + result). Used by the debug "open match
    by ID" form so the operator can paste a match id and load the
    deep-detail modal directly without scrolling the host page."""
    svc = _require_service()
    match = svc.get_match_by_id(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail=f"match {match_id} not found")
    host = svc.get_room_host_handle(match.room_id) if match.room_id else None
    diamonds = svc.match_diamonds_totals([match.id]) if match.id else {}
    return MatchResponse(
        id=match.id or 0,
        room_id=str(match.room_id),
        battle_id=str(match.battle_id),
        opponents=[_serialize_opponent(o) for o in (match.opponents or [])],
        scores=match.scores or {},
        settings=match.settings or {},
        winner_user_id=str(match.winner_user_id) if match.winner_user_id else None,
        started_at=match.started_at.isoformat() if match.started_at else None,
        ended_at=match.ended_at.isoformat() if match.ended_at else None,
        last_seen_at=match.last_seen_at.isoformat() if match.last_seen_at else None,
        diamonds_total=int(diamonds.get(match.id or 0, 0)),
        result=_derive_match_result(match, host),
    )


@router.get("/matches/{match_id}/score_timeline")
async def get_match_score_timeline(
    match_id: int,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Decoded `match_update` score series for a single PK battle.
    Returns rows of `{ts, scores: {team_id: score}}` in ascending ts
    order — drives the dual-line score chart on the match-detail
    Score Timeline tab."""
    svc = _require_service()
    return svc.get_match_score_timeline(match_id)


@router.get("/matches/{match_id}/gifters_by_side")
async def get_match_gifters_by_side(
    match_id: int,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Top gifters during this PK battle, split by which side they
    backed (host / opponent / unknown). Drives the side-split tables
    on the Gifters tab."""
    svc = _require_service()
    return svc.get_match_gifters_by_side(match_id)


@router.get("/matches/{match_id}/head_to_head")
async def get_match_head_to_head(
    match_id: int,
    limit: int = Query(50, ge=1, le=200),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Prior PK battles between this host and (any of) the same
    opponent unique_ids. Used by the Head-to-Head tab. Each row is
    pre-enriched with host_score / opp_score / margin / outcome /
    decisive_pct / duration_seconds so the frontend doesn't need to
    re-derive on render."""
    svc = _require_service()
    return svc.get_match_head_to_head(match_id, limit=limit)


@router.get("/matches/{match_id}/h2h_common_gifters")
async def get_h2h_common_gifters(
    match_id: int,
    min_battles: int = Query(2, ge=1, le=20),
    limit: int = Query(12, ge=1, le=50),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Viewers who gifted in ≥`min_battles` of the head-to-head set
    for this match. Drives the H2H "regulars" bench."""
    svc = _require_service()
    return svc.get_h2h_common_gifters(match_id, min_battles=min_battles, limit=limit)


@router.get("/users/{user_id}/matches")
async def list_user_matches(
    user_id: int,
    room_ids: Optional[str] = Query(
        None,
        description=(
            "Comma-separated list of room ids to scope the matches to. "
            "Omit for cross-host (every match the user ever gifted in)."
        ),
    ),
    since: Optional[datetime] = Query(None, description="Lower-bound on gift ts."),
    until: Optional[datetime] = Query(None, description="Upper-bound on gift ts (exclusive)."),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Matches this user contributed gifts to, scoped by room set
    + optional time window. Drives the gifter-modal "Matches" tab.

    Each entry carries the match identity (room, host, opponents,
    scores, timestamps) + this user's per-match contribution
    (`user_gifts`, `user_diamonds`)."""
    svc = _require_service()
    rids: Optional[list[int]] = None
    if room_ids:
        rids = []
        for raw in room_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rids.append(int(raw))
            except ValueError:
                continue
        if not rids:
            rids = None
    return svc.list_user_matches(
        user_id=user_id,
        room_ids=rids,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}/host-daily-series")
async def user_host_daily_series(
    user_id: int,
    handle: str = Query(..., description="Host handle to scope to."),
    days: int = Query(30, ge=1, le=180),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Per-day diamond + gift totals for a single (user, host) pair
    over the last N days. Drives the Timeline heatmap tab on the
    in-room gifter modal — scoped to "this host's broadcasts" rather
    than every room the viewer has ever touched.

    Lighter than the cross-host `common_gifter_detail` endpoint
    (single grouped SQL query, no momentum/loyalty/intensity
    extras) so it's cheap to fetch every time the user opens the
    Timeline tab."""
    svc = _require_service()
    return svc.get_user_host_daily_series(
        user_id=int(user_id), host_unique_id=handle.lstrip("@"), days=int(days),
    )


def _serialize_opponent(o: dict[str, Any]) -> dict[str, Any]:
    """Coerce numeric ids to str so JS BigInt loss doesn't bite us."""
    if not isinstance(o, dict):
        return {}
    out = dict(o)
    if out.get("user_id") is not None:
        out["user_id"] = str(out["user_id"])
    return out


def _derive_match_result(match, host_handle: Optional[str]) -> str:
    """Determine the host's outcome — "won" / "lost" / "draw" / "ongoing".

    We rely on TikTok's scoring: each opponent has a team_id, and scores is
    {team_id: score}. The host's team is whichever team_id appears in
    opponents alongside their handle. If we can't disambiguate the host's
    team (e.g. opponents list lacks a team for the host), we fall back to
    higher-score-wins under the assumption that the host's team is the one
    NOT shared with named opponents."""
    if match.ended_at is None:
        return "ongoing"
    scores = match.scores or {}
    if not scores:
        # Fallback: TikTok sometimes ships scores only via the per-
        # anchor `opponents[].score` field, leaving `match.scores`
        # empty. Resolve from there. Each opponent entry has a
        # `unique_id` and a numeric `score`; the host is typically
        # listed alongside the actual opponents (TikTok's anchors
        # array is "everyone in the PK", not "everyone except us").
        host_score: int | None = None
        opp_scores: list[int] = []
        for o in (match.opponents or []):
            if not isinstance(o, dict):
                continue
            sc = o.get("score")
            if sc is None:
                continue
            try:
                sc_int = int(sc)
            except (TypeError, ValueError):
                continue
            if host_handle and (o.get("unique_id") or o.get("nickname")) == host_handle:
                host_score = sc_int
            else:
                opp_scores.append(sc_int)
        if host_score is None or not opp_scores:
            return "ended"
        top_opp = max(opp_scores)
        if host_score == top_opp:
            return "draw"
        return "won" if host_score > top_opp else "lost"
    # Highest score among teams.
    sorted_teams = sorted(scores.items(), key=lambda kv: int(kv[1]), reverse=True)
    if len(sorted_teams) >= 2 and int(sorted_teams[0][1]) == int(sorted_teams[1][1]):
        return "draw"

    top_team = str(sorted_teams[0][0])
    if not host_handle:
        return "ended"

    # Find opponents with team_ids; the team that does NOT match an opponent
    # team is presumed to be the host's. If only one team is in opponents
    # (the others are foreign), we know the host's team.
    opp_teams = {
        str(o.get("team_id"))
        for o in (match.opponents or [])
        if o.get("team_id") is not None
        and (o.get("unique_id") or o.get("nickname")) != host_handle
    }
    if not opp_teams:
        # Can't disambiguate — report neutral.
        return "ended"
    host_won = top_team not in opp_teams
    return "won" if host_won else "lost"


# ── stats / dashboard ───────────────────────────────────────────────


@router.get("/rooms/{room_id}/stats")
async def get_room_stats(
    room_id: int,
    window_minutes: int = Query(30, ge=1, le=10080),  # up to a week sliding
    bucket_seconds: Optional[int] = Query(None, ge=10, le=86400),
    since: Optional[datetime] = Query(None, description="Override window: start"),
    until: Optional[datetime] = Query(None, description="Override window: end"),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    return svc.get_room_stats(
        room_id,
        window_minutes=window_minutes,
        bucket_seconds=bucket_seconds,
        since=since,
        until=until,
    )


@router.get("/rooms/{room_id}/recipients")
async def get_room_recipients(
    room_id: int,
    since: Optional[datetime] = Query(None, description="Window start (inclusive)"),
    until: Optional[datetime] = Query(None, description="Window end (exclusive)"),
    limit: int = Query(20, ge=1, le=200),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    return svc.get_room_recipients(
        room_id,
        since=since,
        until=until,
        limit=limit,
    )


@router.get("/rooms/{room_id}/gifters")
async def get_room_gifters(
    room_id: int,
    since: Optional[datetime] = Query(None, description="Window start (inclusive)"),
    until: Optional[datetime] = Query(None, description="Window end (exclusive)"),
    q: Optional[str] = Query(None, description="Match nickname or @unique_id (case-insensitive)"),
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
    room_ids: Optional[str] = Query(
        None,
        description=(
            "Optional comma-separated extra room ids — included alongside the "
            "path room_id so the day-aggregate UI can leaderboard across "
            "every broadcast of the day in one query."
        ),
    ),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    extras: list[int] = []
    if room_ids:
        for raw in room_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                extras.append(int(raw))
            except ValueError:
                continue
    target: int | list[int]
    if extras:
        target = list({int(room_id), *extras})
    else:
        target = int(room_id)
    return svc.get_room_gifters(
        target,
        since=since,
        until=until,
        q=q,
        limit=limit,
        offset=offset,
    )


# ── Notifications history ────────────────────────────────────────


class NotificationCreate(BaseModel):
    type: str = Field(..., description="gift | comment | join | system")
    title: str
    body: Optional[str] = None
    host_unique_id: Optional[str] = None
    user_id: Optional[str] = None  # str for JS BigInt safety
    payload: Optional[dict[str, Any]] = None
    ts: Optional[datetime] = None


@router.get("/notifications")
async def list_notifications(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    type: Optional[str] = None,
    handle: Optional[str] = None,
    unread_only: bool = False,
    include_cleared: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Persistent notification stream backing the iOS-style center.
    Default ordering: newest first. Cleared rows are hidden unless
    `include_cleared=true` (used to show the post-cleanup state for
    a brief undo window)."""
    svc = _require_service()
    return svc.list_notifications(
        since=since, until=until,
        type=type,
        host_unique_id=handle.lstrip("@") if handle else None,
        unread_only=unread_only,
        include_cleared=include_cleared,
        limit=limit, offset=offset,
    )


@router.get("/notifications/unread_count")
async def unread_notifications(
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    return {"unread": int(svc.count_unread_notifications())}


@router.post("/notifications", status_code=201)
async def create_notification(
    body: NotificationCreate,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    svc = _require_service()
    parsed_user_id: int | None = None
    if body.user_id:
        try:
            parsed_user_id = int(body.user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid user_id: {body.user_id!r}")
    nid = svc.insert_notification(
        type=body.type,
        title=body.title,
        body=body.body,
        host_unique_id=body.host_unique_id,
        user_id=parsed_user_id,
        payload=body.payload,
        ts=body.ts,
    )
    return {"id": int(nid)}


@router.patch("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: int,
    read: bool = True,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    ok = svc.mark_notification_read(notification_id, read=read)
    if not ok:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True}


@router.post("/notifications/mark_all_read")
async def mark_all_read(
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    n = svc.mark_all_notifications_read()
    return {"updated": int(n)}


@router.delete("/notifications/{notification_id}")
async def clear_notification(
    notification_id: int,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    ok = svc.clear_notification(notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True}


@router.delete("/notifications")
async def clear_all_notifications(
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    n = svc.clear_all_notifications()
    return {"cleared": int(n)}


# ── Favourite gifters ─────────────────────────────────────────────


@router.get("/favorite-gifters")
async def list_favorite_gifters(
    q: Optional[str] = Query(None, description="Match nickname or @unique_id"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Favourites tab list — admin-curated watchlist of viewers with
    their cross-host totals so each row can render the same way as
    the Common Gifters list."""
    svc = _require_service()
    return svc.list_favorite_gifters(limit=limit, offset=offset, q=q)


@router.get("/favorite-gifters/ids")
async def list_favorite_gifter_ids(
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Bare id list — feeds the WS-driven alert filter on the frontend
    without round-tripping the full enriched payload."""
    svc = _require_service()
    return {"ids": svc.list_favorite_gifter_ids()}


@router.get("/favorite-gifters/notify-config")
async def list_favorite_gifter_notify_config(
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Per-favourite notification toggles — what event types should
    trigger a toast for each starred user. Drives the page-level
    `<TikTokFavoritesWatcher />` filter."""
    svc = _require_service()
    return {"items": svc.list_favorite_gifter_notify_config()}


def _bool_or_none(v: Any) -> Optional[bool]:
    if v is None: return None
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "y", "on"):  return True
        if s in ("0", "false", "no", "n", "off"): return False
    return None


@router.post("/favorite-gifters/{user_id}")
async def add_favorite_gifter(
    user_id: int,
    body: Optional[dict[str, Any]] = Body(None),
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Add (or update) a favourite gifter. Body fields are all
    optional: `note`, `notify_gift`, `notify_comment`, `notify_join`.
    Missing fields preserve existing values; on first insert they
    fall back to the column defaults (gift=true, others=false)."""
    svc = _require_service()
    body = body if isinstance(body, dict) else {}
    note = body.get("note") if isinstance(body.get("note"), str) else None
    svc.add_favorite_gifter(
        user_id,
        note=note,
        notify_gift=_bool_or_none(body.get("notify_gift")),
        notify_comment=_bool_or_none(body.get("notify_comment")),
        notify_join=_bool_or_none(body.get("notify_join")),
    )
    return {"ok": True, "is_favorite": True}


@router.patch("/favorite-gifters/{user_id}")
async def update_favorite_gifter(
    user_id: int,
    body: dict[str, Any] = Body(...),
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    """Update notify toggles / note on an existing favourite. Same
    body shape as POST. Convenience: callers don't have to know
    whether the row exists — the service uses an UPSERT so PATCH and
    POST converge to the same result."""
    svc = _require_service()
    body = body or {}
    svc.add_favorite_gifter(
        user_id,
        note=body.get("note") if isinstance(body.get("note"), str) else None,
        notify_gift=_bool_or_none(body.get("notify_gift")),
        notify_comment=_bool_or_none(body.get("notify_comment")),
        notify_join=_bool_or_none(body.get("notify_join")),
    )
    return {"ok": True, "is_favorite": True}


@router.delete("/favorite-gifters/{user_id}")
async def remove_favorite_gifter(
    user_id: int,
    _user: AuthContext = Depends(rbac.require("admin:write")),
):
    svc = _require_service()
    removed = svc.remove_favorite_gifter(user_id)
    return {"ok": True, "is_favorite": False, "removed": removed}


@router.get("/favorite-gifters/{user_id}")
async def is_favorite_gifter(
    user_id: int,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    return {"user_id": str(user_id), "is_favorite": svc.is_favorite_gifter(user_id)}


@router.get("/common-gifters/{user_id}/detail")
async def get_common_gifter_detail(
    user_id: int,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Deep-analysis payload for one viewer: identity, cross-host
    totals, and per-host breakdown (top gift kinds, recent rooms,
    comment count). Powers the modal opened from the Common Gifters
    table."""
    svc = _require_service()
    return svc.get_common_gifter_detail(user_id)


@router.get("/common-gifters")
async def get_common_gifters(
    min_hosts: int = Query(2, ge=1, le=20),
    q: Optional[str] = Query(None, description="Match nickname or @unique_id (case-insensitive)"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Cross-creator gifter leaderboard: viewers who have gifted to
    `min_hosts` or more distinct hosts. Default min=2 surfaces anyone
    who's bridged at least two of the creators we track. Each row
    carries a per-host breakdown so the UI can render which hosts they
    bridged (with diamond and gift totals per host)."""
    svc = _require_service()
    return svc.get_common_gifters(
        min_hosts=min_hosts, q=q, limit=limit, offset=offset,
    )


@router.get("/runtime-config")
async def admin_tiktok_runtime_config(
    response: Response,
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Admin view of the TikTok runtime config — full set of typed
    keys (`poll_interval_ms`, `admin_realtime`, `public_realtime`).

    The public mirror at `/public/tiktok/runtime-config` trims to a
    public-safe slice; this admin endpoint returns everything so the
    admin frontend can render the right WS-vs-poll behaviour on its
    own pages AND show what the public surface is currently configured
    to do (without anonymous viewers learning the admin mode).

    `Cache-Control: no-store` — toggle in the Configuration UI takes
    effect on the next page reload."""
    response.headers["Cache-Control"] = "no-store"
    # Reuse the public-side reader so the resolve/clamp/validate logic
    # lives in exactly one place. The hexagonal-ish thing to do would
    # be to put it on the service layer; left here because it's a
    # 30-line config read with no cross-cutting concerns.
    from routes.public_tiktok import _read_tiktok_runtime_config
    return _read_tiktok_runtime_config()


@router.get("/lives/{handle}/cross-live-gifters")
async def get_cross_live_gifters_for_host(
    handle: str,
    min_other_hosts: int = Query(1, ge=1, le=20),
    q: Optional[str] = Query(None, description="Match nickname or @unique_id (case-insensitive)"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Cross-live gifters scoped to one host: viewers who have gifted
    to `handle` AND to >= `min_other_hosts` other hosts we track. Same
    shape as `/admin/tiktok/common-gifters` plus per-row `here` vs
    `elsewhere` totals so the UI can surface "spends X on this live,
    Y across N other lives" inline."""
    svc = _require_service()
    return svc.get_cross_live_gifters_for_host(
        handle,
        min_other_hosts=min_other_hosts,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/dashboard")
async def get_dashboard(
    since_hours: int = Query(24, ge=1, le=24 * 30),
    bucket_seconds: int = Query(3600, ge=60, le=86400),
    tz: str = Query(
        "UTC",
        description=(
            "IANA zone for bucket boundary alignment. With `bucket_seconds=86400` "
            "(per-day), a Lima viewer should pass `America/Lima` so day buckets "
            "are 00:00→24:00 Lima rather than UTC."
        ),
    ),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    return svc.get_dashboard_stats(
        since_hours=since_hours,
        bucket_seconds=bucket_seconds,
        tz=tz,
    )


@router.get("/events/search", response_model=list[EventResponse])
async def search_events(
    handle: Optional[str] = None,
    room_id: Optional[int] = None,
    room_ids: Optional[str] = Query(
        None,
        description="Comma-separated room ids — used by the day-aggregate UI to span every broadcast of a day.",
    ),
    # `user_id` accepted as string (TikTok ids are int64, beyond JS
    # Number safe range, so the frontend serialises them as strings).
    # Parsed once at the boundary; service layer takes int.
    user_id: Optional[str] = None,
    match_id: Optional[int] = None,
    type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    q: Optional[str] = None,
    # Cap raised to 2000: the deep-analysis modal's hour-band drill-
    # down needs a wider window to client-filter sparse predicates,
    # and the query is bounded by user_id so the cost is linear in
    # the user's history (typically <1k events).
    limit: int = Query(100, ge=1, le=2000),
    before_id: Optional[int] = None,
    offset: int = Query(0, ge=0),
    to_user_id: Optional[str] = None,
    min_diamonds: Optional[int] = Query(None, ge=0),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    svc = _require_service()
    parsed_ids: list[int] | None = None
    if room_ids:
        parsed_ids = []
        for raw in room_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                parsed_ids.append(int(raw))
            except ValueError:
                continue
        if not parsed_ids:
            parsed_ids = None
    parsed_user_id: int | None = None
    if user_id is not None and user_id != "":
        try:
            parsed_user_id = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid user_id: {user_id!r}")
    parsed_to_user_id: int | None = None
    if to_user_id is not None and to_user_id != "":
        try:
            parsed_to_user_id = int(to_user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid to_user_id: {to_user_id!r}")
    rows = svc.search_events(
        host_unique_id=handle.lstrip("@") if handle else None,
        room_id=room_id,
        room_ids=parsed_ids,
        user_id=parsed_user_id,
        match_id=match_id,
        type=type,
        since=since,
        until=until,
        q=q,
        to_user_id=parsed_to_user_id,
        min_diamonds=min_diamonds,
        limit=limit,
        before_id=before_id,
        offset=offset,
    )
    return [
        EventResponse(
            id=str(r.id or 0),
            room_id=str(r.room_id),
            user_id=str(r.user_id) if r.user_id else None,
            ts=r.ts.isoformat() if r.ts else "",
            type=r.type,
            payload=r.payload or {},
        )
        for r in rows
    ]


@router.get("/events/count")
async def count_events(
    handle: Optional[str] = None,
    room_id: Optional[int] = None,
    room_ids: Optional[str] = Query(
        None,
        description="Comma-separated room ids — used by the day-aggregate UI to span every broadcast of a day.",
    ),
    user_id: Optional[str] = None,  # str for JS BigInt safety; see /events/search
    match_id: Optional[int] = None,
    type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    q: Optional[str] = None,
    to_user_id: Optional[str] = None,
    min_diamonds: Optional[int] = Query(None, ge=0),
    _user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
):
    """Counterpart to /events/search — same filter shape, returns the
    total row count. Drives the `(N)` badges on paginated tabs."""
    svc = _require_service()
    parsed_ids: list[int] | None = None
    if room_ids:
        parsed_ids = []
        for raw in room_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                parsed_ids.append(int(raw))
            except ValueError:
                continue
        if not parsed_ids:
            parsed_ids = None
    parsed_user_id: int | None = None
    if user_id is not None and user_id != "":
        try:
            parsed_user_id = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid user_id: {user_id!r}")
    parsed_to_user_id: int | None = None
    if to_user_id is not None and to_user_id != "":
        try:
            parsed_to_user_id = int(to_user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid to_user_id: {to_user_id!r}")
    total = svc.count_events(
        host_unique_id=handle.lstrip("@") if handle else None,
        room_id=room_id,
        room_ids=parsed_ids,
        user_id=parsed_user_id,
        match_id=match_id,
        type=type,
        since=since,
        until=until,
        q=q,
        to_user_id=parsed_to_user_id,
        min_diamonds=min_diamonds,
    )
    return {"total": int(total)}


# ── real-time events WebSocket ──────────────────────────────────────


@router.websocket("/ws")
async def ws_events(ws: WebSocket):
    """Streams TikTok events to the client.

    Auth: the client appends `?token=<jwt>` to the URL. We validate it
    against the same AuthService used by HTTP admin routes and require
    `admin:write`. Without this gate, anyone who can reach the host
    can stream the in-memory fan-out for every tracked subscription —
    including handles the operator has NOT flipped `is_public=True` —
    bypassing the allowlist on the `/public/tiktok/*` HTTP surface.

    By default the WS forwards EVERY event for every active subscription.
    The client can filter to specific creators by sending a JSON control
    message at any time:

        {"type": "subscribe", "handles": ["puchofrio", "kiba.066"]}

    Pass `["*"]` (or omit / send `null`) to receive everything again.
    The server filters by `envelope.unique_id` BEFORE sending — saves
    bandwidth and CPU when a tab only cares about one creator.

    Two delivery modes:
      - In-process listener (default): registers an in-memory listener on
        the local TikTokService.
      - Worker mode (PHOVEU_BACKEND_TIKTOK_LISTENER_MODE=worker): subscribes
        to the Redis pub/sub channel that the worker publishes to.
    """
    # Validate JWT BEFORE ws.accept(). Closing without accepting sends
    # an HTTP rejection on the upgrade — no half-open WS that an
    # unauthenticated viewer could mine for events. Close codes follow
    # the 4000-range convention (app-defined): 4401 = unauthenticated,
    # 4403 = authenticated but missing admin permission.
    #
    # Authorisation matches the rest of the admin TikTok surface:
    # `admin:write` OR any documented read-only equivalent. The HTTP
    # handlers above use `rbac.require_any_read_only(["admin:write"])`
    # — so a user with `admin:read` works on the REST endpoints. The
    # WS originally hard-required `admin:write` and so rejected those
    # read-only admins (visible as a stream of 403s in the dev log
    # while the page still rendered fine). We align here by accepting
    # `admin:write` OR `admin:read`. If you need a "no read-only WS"
    # policy (e.g. WS leaks an internal state the read role shouldn't
    # see), tighten this back to `admin:write` only.
    token = ws.query_params.get("token")
    if not token:
        logger.info("WS auth reject: no token in query string.")
        await ws.close(code=4401)
        return
    try:
        from utils.auth_provider import get_auth_service
        auth_context = get_auth_service().get_auth_context(token)
    except Exception:
        logger.exception("WS auth reject: get_auth_context raised.")
        auth_context = None
    if auth_context is None:
        logger.info("WS auth reject: invalid or expired token.")
        await ws.close(code=4401)
        return
    has_write = auth_context.has_permission("admin:write")
    has_read = auth_context.has_permission("admin:read")
    if not (has_write or has_read):
        logger.info(
            "WS auth reject: user=%s lacks admin:write OR admin:read "
            "(permissions=%s).",
            getattr(auth_context.user, "username", "?"),
            sorted(list(getattr(auth_context, "permissions", []) or [])),
        )
        await ws.close(code=4403)
        return

    import os
    listener_mode = os.getenv(
        "PHOVEU_BACKEND_TIKTOK_LISTENER_MODE", "in_process"
    ).strip().lower()

    await ws.accept()
    logger.info(
        "WS /admin/tiktok/ws client connected (mode=%s, user=%s).",
        listener_mode,
        auth_context.user.username,
    )

    # Filter state: None = no filter (receive everything). Otherwise a
    # set of allowed unique_ids. Mutated by the control-message reader
    # task and read by the pump tasks; both run on the same event loop
    # so a plain dict-of-state is safe (no lock needed).
    state: dict[str, Any] = {"handles": None}

    # Phase 9D: resolve the state cache (if wired). Used by the
    # delta-subscriber parallel task AND the request-snapshot inbound
    # control message. `None` when `PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH=off`
    # — in that case the WS reduces to its pre-Phase-9 behavior
    # (event fan-out only, no per-host state deltas, no snapshot path).
    state_cache = getattr(
        getattr(tiktok_service, "_persistence", None),
        "_state_cache",
        None,
    ) if tiktok_service is not None else None

    async def control_reader() -> None:
        """Reads control messages from the client. Updates `state` in place."""
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("type")
                if mtype == "subscribe":
                    handles = msg.get("handles")
                    if handles is None or handles == "*" or (
                        isinstance(handles, list) and "*" in handles
                    ):
                        state["handles"] = None  # receive everything
                    elif isinstance(handles, list):
                        state["handles"] = {
                            h.lstrip("@").strip() for h in handles if isinstance(h, str)
                        }
                elif mtype == "request-snapshot":
                    # Phase 9D: per-host state snapshot reply for clients
                    # that detected a `version` gap. One reply frame per
                    # handle; missing handles get `version=0, data={}` so
                    # the client always has a baseline.
                    if state_cache is None:
                        continue
                    handles = msg.get("handles") or []
                    if not isinstance(handles, list):
                        continue
                    for h in handles:
                        if not isinstance(h, str):
                            continue
                        norm = h.lstrip("@").strip().lower()
                        try:
                            cached = state_cache.get(norm)
                        except Exception:
                            logger.exception(
                                "state-cache.get failed for %s (admin ws)", norm,
                            )
                            cached = None
                        if cached is None:
                            payload = {
                                "type": "snapshot",
                                "host": norm,
                                "version": 0,
                                "data": {},
                            }
                        else:
                            version, data = cached
                            # Strip `_*` aux fields — same convention the
                            # delta-publish path uses.
                            public_data = {
                                k: v for k, v in data.items()
                                if not k.startswith("_")
                            }
                            payload = {
                                "type": "snapshot",
                                "host": norm,
                                "version": version,
                                "data": public_data,
                            }
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            return  # client disconnected mid-reply
        except WebSocketDisconnect:
            return
        except Exception:
            # Bad message format — ignore and keep reading.
            return

    def passes_filter(envelope: dict) -> bool:
        allowed = state["handles"]
        if allowed is None:
            return True
        return envelope.get("unique_id") in allowed

    async def state_delta_pump() -> None:
        """Phase 9D: forwards `tiktok:lives:delta:admin` to the client
        as `{type:"summary-delta", host, version, patch}`. Applies the
        same per-handle filter as the event stream — a client that
        narrowed to `["host_x"]` doesn't get summary deltas for other
        hosts.

        No-op when no state cache is wired."""
        if state_cache is None:
            return
        try:
            async for delta in state_cache.subscribe("admin"):
                if not isinstance(delta, dict):
                    continue
                host = delta.get("host", "")
                allowed = state["handles"]
                if allowed is not None and host not in allowed:
                    continue
                try:
                    await ws.send_json({"type": "summary-delta", **delta})
                except Exception:
                    return  # client disconnected
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("state_delta_pump (admin) failed")
            return

    try:
        reader = asyncio.create_task(control_reader())
        delta_pump = asyncio.create_task(state_delta_pump())
        try:
            if listener_mode == "worker":
                await _ws_pump_from_redis(ws, passes_filter)
            else:
                if tiktok_service is None:
                    await ws.send_json({"error": "TikTok service unavailable"})
                    await ws.close(code=1011)
                    return
                await _ws_pump_from_service(ws, tiktok_service, passes_filter)
        finally:
            for t in (reader, delta_pump):
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("ws_events: unexpected error")
    finally:
        logger.info("WS /admin/tiktok/ws client disconnected.")


async def _ws_pump_from_service(
    ws: WebSocket, svc: Any, passes_filter: Any
) -> None:
    """In-process fan-out: register a listener on the service."""
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)

    async def listener(envelope: dict) -> None:
        if not passes_filter(envelope):
            return
        try:
            queue.put_nowait(envelope)
        except asyncio.QueueFull:
            logger.warning("WS subscriber queue full; dropping event.")

    svc.add_listener(listener)
    try:
        while True:
            msg = await queue.get()
            await ws.send_json(msg)
    finally:
        svc.remove_listener(listener)


async def _ws_pump_from_redis(ws: WebSocket, passes_filter: Any) -> None:
    """Worker-mode fan-out: subscribe to the Redis events channel."""
    from adapters.tiktok_event_bus import subscribe_events
    async for envelope in subscribe_events():
        if not passes_filter(envelope):
            continue
        await ws.send_json(envelope)

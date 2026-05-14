"""Public (unauthenticated) TikTok endpoints.

Exposes the subset of the admin TikTok read API that operators have
explicitly opted into via the `is_public` flag on each subscription.
Mounted at /public/tiktok/* and intentionally has NO auth dependency
— anyone can hit these.

Access-control rule (every endpoint):
  - Input is a `handle`     → lookup subscription, refuse if not public.
  - Input is a `room_id`    → lookup room → host → subscription, refuse.
  - Input is a `match_id`   → lookup match → room → host → subscription.
  - Input is `room_ids`     → EVERY id must map to a public host.
All refusals are 404 (never 401/403) so the API doesn't leak whether
a non-public handle even exists.

Sanitization rule (every endpoint):
  Build responses by allowlist-COPY (fail-closed): never drop-known-
  private. Any new key upstream stays opaque until explicitly added
  to the per-shape allowlist below. Operator-only fields stripped
  EVERYWHERE: reconnects_1h, last_caption, favorites_in_room,
  diamonds_vs_typical, median_diamonds_30d, profile_error,
  profile_refreshed_at, is_connected, enabled, state,
  assigned_worker_id, assignment_lease_until, worker_id, worker_key,
  sec_uid, profile_user_id, private, updated_at, last_event_age_s.

Per-route HTTP caching: every public response carries
`Cache-Control: public, max-age=15` + `Vary: Accept-Encoding` so a
busy detail page running multiple polls can ride the browser /
CDN cache for up to 15s. Server-side caching (where it exists) is
in the service layer (see _public_lives_summary_cache).

Rate limiting is handled by the global rate-limit middleware
(utils/middleware/rate_limiting.py) — no per-route decorator needed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Optional

import asyncio
import json
import os

from fastapi import APIRouter, HTTPException, Query, Response, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Public TikTok"])

# Dependency placeholder — set from routes/main.py:setup_routes().
# Read at request time, NOT bound at import time, so the route picks
# up the service that initialize_services() built.
tiktok_service = None  # type: ignore[assignment]
# Typed-config service — only the small `TIKTOK_*_MODE` and poll-interval
# slice is exposed here (via the /runtime-config endpoint), not the whole
# config surface. Wired by routes/main.py:setup_routes.
config_service = None  # type: ignore[assignment]


# ── access guards ───────────────────────────────────────────────────


def _require_service():
    """Raises 503 when the service hasn't been wired yet. Same code
    the admin routes return for an unwired tiktok_service global."""
    if tiktok_service is None:
        raise HTTPException(status_code=503, detail="TikTok service unavailable")
    return tiktok_service


def _resolve_public_host(handle: str):
    """Resolve `@handle` → Subscription, refuse with 404 unless public.

    Returns the `Subscription` dataclass on success so callers can
    inspect identity/profile fields without re-fetching. 404 (not
    401/403) on every refusal path: missing handle, unknown handle,
    or `is_public=False`. This prevents the API from leaking whether
    a non-public subscription even exists.
    """
    svc = _require_service()
    handle = (handle or "").lstrip("@").strip()
    if not handle:
        raise HTTPException(status_code=404, detail="not found")
    sub = svc._persistence.get_subscription(handle)
    if sub is None or not bool(getattr(sub, "is_public", False)):
        raise HTTPException(status_code=404, detail="not found")
    return sub


def _resolve_public_room(room_id: int):
    """Resolve `room_id` → host_unique_id → Subscription. 404 unless
    the host is opted public.

    Returns the `Subscription` dataclass so the caller can reuse the
    identity. Note: we look up the host via `get_room_host_handle`
    (single-column query) rather than loading the full room row.
    """
    svc = _require_service()
    try:
        rid = int(room_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="not found")
    host = svc._persistence.get_room_host_handle(rid)
    if not host:
        raise HTTPException(status_code=404, detail="not found")
    return _resolve_public_host(host)


def _resolve_public_match(match_id: int):
    """Resolve `match_id` → room → host → Subscription. 404 unless
    the host is opted public.

    Returns `(match, subscription)` so the caller can read the match
    row without re-fetching. We don't return just the subscription
    here because matches are uniformly accessed alongside the match
    row itself (`get_match_by_id` is the source of truth).
    """
    svc = _require_service()
    try:
        mid = int(match_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="not found")
    match = svc._persistence.get_match_by_id(mid)
    if match is None or match.room_id is None:
        raise HTTPException(status_code=404, detail="not found")
    host = svc._persistence.get_room_host_handle(int(match.room_id))
    if not host:
        raise HTTPException(status_code=404, detail="not found")
    sub = _resolve_public_host(host)
    return match, sub


def _resolve_public_room_set(room_ids: Iterable[int]) -> list[int]:
    """Validate every id in `room_ids` maps to a public host.

    Refuses with 404 if ANY id fails the public-host check — partial
    success would be a silent leak of "this room exists but its host
    isn't public" vs "this room doesn't exist". Returns the parsed
    int list (de-duplicated, original order preserved) on success.
    """
    svc = _require_service()
    seen: set[int] = set()
    ordered: list[int] = []
    for rid in room_ids:
        try:
            i = int(rid)
        except (TypeError, ValueError):
            continue
        if i in seen:
            continue
        seen.add(i)
        ordered.append(i)
    if not ordered:
        raise HTTPException(status_code=404, detail="not found")
    # Resolve each — one query per room_id (single-column lookup).
    # For the room set sizes the public detail page actually sends
    # (≤ ~30 ids for a day-aggregate), this is cheaper than building
    # a JOIN-against-subs query and avoids opening up a public bulk
    # endpoint that could be abused to brute-force the public set.
    for rid in ordered:
        host = svc._persistence.get_room_host_handle(rid)
        if not host:
            raise HTTPException(status_code=404, detail="not found")
        sub = svc._persistence.get_subscription(host)
        if sub is None or not bool(getattr(sub, "is_public", False)):
            raise HTTPException(status_code=404, detail="not found")
    return ordered


def _set_cache_headers(response: Response) -> None:
    """Apply the standard public-endpoint cache headers in-place.

    Every public-TikTok endpoint shares the same caching shape:
      - `Cache-Control: public, max-age=15` — browsers + CDNs absorb
        the fan-out from anonymous polling tabs without each one
        rehitting the API every poll cycle.
      - `Vary: Accept-Encoding` — the only request header that
        meaningfully changes our representation is gzip vs identity.
        No auth / cookie / per-user variance.
    """
    # Privacy-sensitive: `no-store` so browsers / CDNs never serve a
    # cached payload after an operator flips `is_public=False`. The
    # 30 s in-process server cache still absorbs anonymous fan-out,
    # but each client always re-asks — and the moment the access
    # guard refuses the handle, the cached browser copy is gone.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Accept-Encoding"


# ── sanitization allowlists ─────────────────────────────────────────


# Per-room-stats `active_match` shape (subset of `_match_to_dict`).
# Drops: nothing additional — every field is either public TikTok
# state (scores/opponents/timestamps) or a server-derived rollup
# (diamonds_total). `settings` is TikTok's own per-battle config.
_ACTIVE_MATCH_FIELDS = (
    "id", "room_id", "battle_id", "opponents", "scores", "settings",
    "winner_user_id", "started_at", "ended_at", "last_seen_at",
    "diamonds_total", "result",
)


# `MatchResponse` shape — same allowlist as the active_match payload
# (the admin endpoint returns the same fields). Kept distinct so we
# can diverge later if /matches grows operator-only enrichment.
_MATCH_FIELDS = _ACTIVE_MATCH_FIELDS


# `EventResponse` shape — id/room_id/user_id/ts/type/payload. The
# payload itself is TikTok-emitted, but we strip a couple of internal
# keys if they happen to be present (defensive — the worker writes
# raw TikTok payloads, so nothing operator-derived is in there today).
_EVENT_FIELDS = ("id", "room_id", "user_id", "ts", "type", "payload")
_EVENT_PAYLOAD_DROP_KEYS = ("last_caption", "message_id")


# `RoomResponse` shape from list_host_rooms.
_ROOM_FIELDS = (
    "room_id", "host_unique_id", "host_user_id",
    "title", "started_at", "ended_at",
    "first_seen_at", "last_seen_at",
    "diamonds", "matches", "likes",
)


def _pick(src: Any, allow: tuple[str, ...]) -> dict[str, Any]:
    """Allowlist-copy. Fails closed when upstream adds a new key —
    nothing leaks unless it's enumerated. Mirrors
    TikTokService._pick (we deliberately re-implement here so the
    route layer doesn't reach into a private helper)."""
    if not src:
        return {}
    is_mapping = isinstance(src, dict)
    out: dict[str, Any] = {}
    for k in allow:
        v = src.get(k) if is_mapping else getattr(src, k, None)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[k] = v
    return out


def _sanitize_event(evt: Any) -> dict[str, Any]:
    """Allowlist-copy an event row + scrub the payload.

    Events are TikTok-emitted (gift/comment/like/etc.) so the payload
    is a JSON map produced by the worker from the live WebSocket. We
    strip a defensive set of keys that *could* sneak in from a future
    worker enrichment (`last_caption` — speech transcript) or an
    internal id (`message_id`).
    """
    is_mapping = isinstance(evt, dict)

    def _get(k: str) -> Any:
        return evt.get(k) if is_mapping else getattr(evt, k, None)

    out: dict[str, Any] = {}
    for k in _EVENT_FIELDS:
        v = _get(k)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        if k == "payload" and isinstance(v, dict):
            v = {pk: pv for pk, pv in v.items() if pk not in _EVENT_PAYLOAD_DROP_KEYS}
        out[k] = v
    # Stringify BigInt ids regardless of input shape.
    if out.get("id") is not None:
        out["id"] = str(out["id"])
    if out.get("room_id") is not None:
        out["room_id"] = str(out["room_id"])
    if out.get("user_id") is not None:
        out["user_id"] = str(out["user_id"])
    return out


def _sanitize_match(match_dict: Any) -> dict[str, Any]:
    """Allowlist-copy a match dict (active_match payload or
    /matches list row). Stringifies BigInt fields explicitly."""
    out = _pick(match_dict, _MATCH_FIELDS)
    # Stringify ids if the caller passed raw ints.
    for k in ("room_id", "battle_id", "winner_user_id"):
        v = out.get(k)
        if v is not None and not isinstance(v, str):
            out[k] = str(v)
    return out


# ── public endpoints ────────────────────────────────────────────────


@router.get("/tiktok/lives")
def public_lives(
    response: Response,
    tz: str = Query(
        "UTC",
        description=(
            "IANA timezone for the per-host `week_calendar` 7-day mini-strip. "
            "Frontend passes the active TZ-pill selection."
        ),
    ),
):
    """Public payload for every subscription marked `is_public=True`.

    Response shape:
        {"items": [
            {
                "subscription": { ...allowlisted Subscription fields... },
                "summary":      { ...allowlisted TikTokLiveSummary fields... },
            },
            ...
        ]}

    See `TikTokService._PUBLIC_SUBSCRIPTION_FIELDS` and
    `_PUBLIC_SUMMARY_FIELDS` for the exact key sets. Operator-only
    signals (favorites_in_room, diamonds_vs_typical, reconnects_1h,
    last_caption, listener state, worker coordination columns, internal
    identifiers) are never copied into the response.

    Cached server-side for 30s (in TikTokService). The response also
    carries `Cache-Control: public, max-age=15` so CDNs and browser
    caches absorb the fan-out from anonymous viewers.
    """
    svc = _require_service()
    _set_cache_headers(response)
    return svc.get_public_lives_summary(tz=tz)


@router.get("/tiktok/lives/{handle}")
def public_live_detail(handle: str, response: Response):
    """Public detail payload for a single handle.

    Returns the same `{subscription, summary}` pair shape as a single
    item of `/public/tiktok/lives`, so the frontend can reuse the
    same card renderer for the detail page header.
    """
    svc = _require_service()
    sub = _resolve_public_host(handle)
    _set_cache_headers(response)

    # Fan out to the admin summary path for this one handle, then
    # apply the public allowlist. Cheaper than building a parallel
    # one-shot service method — re-uses the in-process summary cache
    # when admin + public both poll the same handle.
    h = sub.unique_id
    summary = svc.get_lives_summary([h])
    row = summary.get(h.lstrip("@").lower(), {}) or {}
    return {
        "subscription": svc._pick(sub, svc._PUBLIC_SUBSCRIPTION_FIELDS),
        "summary":      svc._pick(row, svc._PUBLIC_SUMMARY_FIELDS),
    }


def _read_tiktok_runtime_config() -> dict[str, Any]:
    """Shared reader for the typed TikTok runtime keys. Both the public
    slice (below) and the admin endpoint (in `routes/admin/tiktok.py`)
    call into this so the resolve + clamp + validate logic lives in
    one place. Returns `{poll_interval_ms, admin_realtime, public_realtime}`
    with sensible defaults on read failure."""
    defaults = {
        "poll_interval_ms": 30000,
        "admin_realtime": "both",
        "public_realtime": "poll",
    }
    if config_service is None:
        return defaults
    try:
        poll_interval = int(config_service.get("TIKTOK_POLL_INTERVAL_MS"))
        admin_mode = str(config_service.get("TIKTOK_ADMIN_REALTIME_MODE")).strip().lower()
        public_mode = str(config_service.get("TIKTOK_PUBLIC_REALTIME_MODE")).strip().lower()
    except Exception:
        logger.exception("_read_tiktok_runtime_config: config read failed")
        return defaults
    # Clamp poll interval to a sane range so a misconfigured 0 or
    # 1ms doesn't DDOS our own backend. Floor matches the WS
    # heartbeat interval; ceiling at 10 min so it's still
    # recognisably "polling" rather than "off".
    poll_interval = max(1000, min(600000, poll_interval))
    valid_modes = {"poll", "ws", "both"}
    if admin_mode not in valid_modes:
        admin_mode = "both"
    if public_mode not in valid_modes:
        public_mode = "poll"
    return {
        "poll_interval_ms": poll_interval,
        "admin_realtime": admin_mode,
        "public_realtime": public_mode,
    }


@router.get("/tiktok/runtime-config")
def public_tiktok_runtime_config(response: Response):
    """Public, anonymous-readable slice of the TikTok runtime config.
    Returns ONLY the keys a public viewer needs to render `/lives/...`
    correctly: `poll_interval_ms` (REST poll cadence) and
    `public_realtime` (whether the public WS is enabled).

    `admin_realtime` is deliberately NOT included — it tells nothing
    useful to a public viewer, and the project's policy is "admin
    config under admin auth." The admin frontend reads the full set
    from `/admin/tiktok/runtime-config` (auth required).

    `Cache-Control: no-store` so a flip in the Configuration UI
    takes effect on the next page reload."""
    response.headers["Cache-Control"] = "no-store"
    full = _read_tiktok_runtime_config()
    return {
        "poll_interval_ms": full["poll_interval_ms"],
        "public_realtime": full["public_realtime"],
    }


@router.websocket("/tiktok/ws")
async def public_ws_events(ws: WebSocket):
    """Anonymous-readable WS that streams TikTok events for `is_public=True`
    handles only. Mirrors `/admin/tiktok/ws` but filters every outbound
    envelope against the cached public-handle set so a host that's
    NOT `is_public=True` never has its events sent here.

    No JWT required — this is the public surface. The trust model:
    operators explicitly opt each subscription in via the admin
    Configuration UI (sets `is_public=True` on the row). The cache
    behind `get_public_handle_set()` is invalidated immediately on
    flip, so the *next* event after a private-toggle is filtered out.

    Same client protocol as the admin WS: send
        {"type": "subscribe", "handles": ["foo", "bar"]}
    to narrow the subscription. `*` / null / omitted = all public
    handles. The server still enforces public-only filtering — a
    client requesting a non-public handle just gets no events.

    Two delivery modes (same env var as the admin WS):
      - In-process: register a listener on the local TikTokService.
      - Worker mode: subscribe to the Redis `tiktok:events` channel.

    Per-envelope filtering uses `get_public_handle_set()` (TTL-cached,
    invalidated on flip), so heavy event traffic stays cheap — no
    DB hit per event.
    """
    listener_mode = os.getenv(
        "PHOVEU_BACKEND_TIKTOK_LISTENER_MODE", "in_process"
    ).strip().lower()

    await ws.accept()
    logger.info("WS /public/tiktok/ws client connected (mode=%s).", listener_mode)

    # Filter state mirrors the admin WS — None = all public handles
    # (within the public set), otherwise a set of lowercased handles
    # the client explicitly subscribed to. The public-set check is
    # ALWAYS applied on top, regardless of what the client sends.
    state: dict[str, Any] = {"handles": None}

    # Phase 9D extended the reader to also handle `request-snapshot`.
    # The combined handler `control_reader_public` is defined below
    # after `state_cache` is resolved — see the comment block there.

    def passes_filter(envelope: dict) -> bool:
        """Two-layer check: (1) the envelope's host MUST be in the
        current public-handle set (so toggling private kills the
        stream within one event), and (2) if the client narrowed the
        subscription, the host must also be in their requested set."""
        unique_id = envelope.get("unique_id")
        if not isinstance(unique_id, str):
            return False
        normalized = unique_id.lstrip("@").lower()
        # Always-on public-set check.
        if tiktok_service is None:
            return False
        public_set = tiktok_service.get_public_handle_set()
        if normalized not in public_set:
            return False
        # Client-narrowed subscription, if any.
        allowed = state["handles"]
        if allowed is None:
            return True
        return normalized in allowed

    # Reuse the admin pump helpers — they're parameterised on
    # `passes_filter` so the public stream gets the same backpressure
    # semantics (1000-deep async queue, drop on overflow). Importing
    # from a sibling router module is a minor coupling; an extraction
    # to a shared module would be cleaner but isn't load-bearing.
    from routes.admin.tiktok import _ws_pump_from_service, _ws_pump_from_redis

    # Phase 9D: state cache for delta fan-out + snapshot replies.
    # Public channel deltas are pre-sanitized by the adapter (via
    # `service.sanitize_public_patch` injected at construction); we
    # forward them verbatim. Snapshot replies go through the same
    # sanitizer here because we read raw cache state directly.
    state_cache = getattr(
        getattr(tiktok_service, "_persistence", None), "_state_cache", None,
    ) if tiktok_service is not None else None

    async def state_delta_pump_public() -> None:
        """Forwards `tiktok:lives:delta:public` deltas to this client.
        Channel is pre-sanitized; we still apply the public-handle-set
        check AND the client-narrowed filter so flipping a host private
        kills its stream within one event."""
        if state_cache is None:
            return
        try:
            async for delta in state_cache.subscribe("public"):
                if not isinstance(delta, dict):
                    continue
                host = (delta.get("host") or "").lstrip("@").lower()
                # Public-set check: same rule as event filtering.
                if tiktok_service is None:
                    continue
                if host not in tiktok_service.get_public_handle_set():
                    continue
                # Client-narrowed subscription.
                allowed = state["handles"]
                if allowed is not None and host not in allowed:
                    continue
                try:
                    await ws.send_json({"type": "summary-delta", **delta})
                except Exception:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("state_delta_pump (public) failed")
            return

    # Extend the existing reader with `request-snapshot` handling.
    # The base `control_reader` defined above ONLY handles `subscribe`;
    # wrap it with our own that also dispatches snapshots and falls
    # through to the base for everything else.
    async def control_reader_public() -> None:
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
                        state["handles"] = None
                    elif isinstance(handles, list):
                        state["handles"] = {
                            h.lstrip("@").strip().lower()
                            for h in handles if isinstance(h, str)
                        }
                elif mtype == "request-snapshot":
                    if state_cache is None or tiktok_service is None:
                        continue
                    handles = msg.get("handles") or []
                    if not isinstance(handles, list):
                        continue
                    public_set = tiktok_service.get_public_handle_set()
                    for h in handles:
                        if not isinstance(h, str):
                            continue
                        norm = h.lstrip("@").strip().lower()
                        # Public-set check: requests for non-public hosts
                        # get an empty snapshot (same as "no entry yet")
                        # — we don't reveal whether a private host exists.
                        if norm not in public_set:
                            try:
                                await ws.send_json({
                                    "type": "snapshot", "host": norm,
                                    "version": 0, "data": {},
                                })
                            except Exception:
                                return
                            continue
                        try:
                            cached = state_cache.get(norm)
                        except Exception:
                            logger.exception(
                                "state-cache.get failed for %s (public ws)", norm,
                            )
                            cached = None
                        if cached is None:
                            payload = {
                                "type": "snapshot", "host": norm,
                                "version": 0, "data": {},
                            }
                        else:
                            version, data = cached
                            # Strip aux + apply public sanitizer so a
                            # snapshot reply can't leak operator-only
                            # fields. Mirrors the delta channel's
                            # pre-publish sanitization.
                            stripped = {
                                k: v for k, v in data.items()
                                if not k.startswith("_")
                            }
                            sanitized = tiktok_service.sanitize_public_patch(stripped)
                            payload = {
                                "type": "snapshot", "host": norm,
                                "version": version, "data": sanitized,
                            }
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            return
        except WebSocketDisconnect:
            return
        except Exception:
            return

    try:
        reader = asyncio.create_task(control_reader_public())
        delta_pump = asyncio.create_task(state_delta_pump_public())
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
        logger.exception("public_ws_events: unexpected error")
    finally:
        logger.info("WS /public/tiktok/ws client disconnected.")


@router.get("/tiktok/lives/{handle}/status")
def public_live_status(handle: str, response: Response):
    """Three-state visibility probe for `/lives/{handle}` route guards.

    Returns one of:
      - `{"status": "public",     "handle": "..."}` → frontend renders detail page.
      - `{"status": "private",    "handle": "..."}` → frontend shows "currently private."
      - `{"status": "not_found",  "handle": "..."}` → frontend shows "no tracked live."

    Note: this is the ONLY public endpoint that intentionally differentiates
    "exists but not public" from "doesn't exist." Every data endpoint
    (`lives`, `rooms`, `stats`, `events`, ...) still refuses with a uniform
    404 and `detail: "not found"` so the data API leaks nothing. This
    status endpoint exists strictly for UX — so the public route guard
    can show the operator's audience a useful message instead of a blank
    redirect — and is a knowing concession: it confirms whether a handle
    is tracked at all. If you ever expose more data here, you widen that
    leak. Keep this response to the three-state literal + the echo of the
    handle the caller provided.

    `Cache-Control: no-store` so the moment the operator flips visibility,
    the next route-guard probe sees the new state without any browser
    cache lag.
    """
    svc = _require_service()
    cleaned = (handle or "").lstrip("@").strip()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Accept-Encoding"
    if not cleaned:
        return {"status": "not_found", "handle": cleaned}
    sub = svc._persistence.get_subscription(cleaned)
    if sub is None:
        return {"status": "not_found", "handle": cleaned}
    if not bool(getattr(sub, "is_public", False)):
        return {"status": "private", "handle": cleaned}
    return {"status": "public", "handle": cleaned}


@router.get("/tiktok/lives/{handle}/calendar")
def public_live_calendar(
    handle: str,
    response: Response,
    weeks: int = Query(26, ge=1, le=104),
    tz: str = Query(
        "UTC",
        description="IANA timezone for day bucketing.",
    ),
):
    """Per-day broadcast counts for the heatmap on the public detail
    page. Same shape as the admin calendar endpoint — no operator-only
    fields exist in the row shape (date, rooms, duration_minutes,
    diamonds, matches), so this is a sanitized pass-through."""
    svc = _require_service()
    sub = _resolve_public_host(handle)
    _set_cache_headers(response)
    return svc.host_calendar(sub.unique_id, weeks=weeks, tz=tz)


@router.get("/tiktok/lives/{handle}/rooms")
def public_live_rooms(
    handle: str,
    response: Response,
    limit: int = Query(50, ge=1, le=200),
):
    """Per-broadcast list for one public handle. Mirrors the admin
    `list_host_rooms` endpoint with the same `RoomResponse` shape +
    per-room rollups (diamonds / matches / likes) so the broadcast
    selector can label each entry inline."""
    svc = _require_service()
    sub = _resolve_public_host(handle)
    rooms = svc.list_rooms_for_host(sub.unique_id, limit=limit)
    totals = svc.room_totals([r.room_id for r in rooms]) if rooms else {}
    _set_cache_headers(response)
    out: list[dict[str, Any]] = []
    for r in rooms:
        out.append(_pick({
            "room_id":        str(r.room_id),
            "host_unique_id": r.host_unique_id,
            "host_user_id":   str(r.host_user_id) if r.host_user_id else None,
            "title":          r.title,
            "started_at":     r.started_at.isoformat() if r.started_at else None,
            "ended_at":       r.ended_at.isoformat() if r.ended_at else None,
            "first_seen_at":  r.first_seen_at.isoformat() if r.first_seen_at else None,
            "last_seen_at":   r.last_seen_at.isoformat() if r.last_seen_at else None,
            "diamonds":       totals.get(int(r.room_id), {}).get("diamonds"),
            "matches":        totals.get(int(r.room_id), {}).get("matches"),
            "likes":          totals.get(int(r.room_id), {}).get("likes"),
        }, _ROOM_FIELDS))
    return out


@router.get("/tiktok/lives/{handle}/cross-live-gifters")
def public_cross_live_gifters_for_host(
    handle: str,
    response: Response,
    min_other_hosts: int = Query(1, ge=1, le=20),
    q: Optional[str] = Query(None, description="Match nickname or @unique_id (case-insensitive)"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Public mirror of the admin cross-live gifters endpoint. The
    underlying data only exposes user/host edges that already exist in
    the public summary surface (no operator-only counters), but we
    still gate on `is_public` for the queried host so private lives
    can't be probed for their cross-live audience overlap."""
    svc = _require_service()
    sub = _resolve_public_host(handle)
    _set_cache_headers(response)
    return svc.get_cross_live_gifters_for_host(
        sub.unique_id,
        min_other_hosts=min_other_hosts,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/tiktok/common-gifters/{user_id}/detail")
def public_common_gifter_detail(user_id: int, response: Response):
    """Public mirror of `/admin/tiktok/common-gifters/{user_id}/detail`.

    Returns the same deep-analysis shape (identity, totals, hosts,
    momentum, loyalty, tier mix, heatmap, etc.) used by the admin
    Profile tab — but with every host-emitting field filtered to
    hosts the operator has opted public (`is_public=True`). The
    `user_id` itself is global; it identifies a TikTok viewer, not
    a host, so no `_resolve_public_host` resolver applies. The
    filtering happens one layer down in
    `TikTokPersistence.common_gifter_detail(public_only=True)`, which
    drops every entry under `hosts`, `whale_sessions`, `daily_series`,
    `intensity.biggest_session`, `recent_activity`,
    `identity_progression`, `recipients_per_host`, and `loyalty.top_host`
    whose `host_unique_id` isn't in the public allowlist. Totals
    recompute against the filtered subset.

    Without this filter, anonymous viewers could enumerate every host
    in `tiktok_subscriptions` by querying any active viewer id.
    """
    svc = _require_service()
    _set_cache_headers(response)
    return svc.get_common_gifter_detail(int(user_id), public_only=True)


@router.get("/tiktok/rooms/{room_id}/stats")
def public_room_stats(
    room_id: int,
    response: Response,
    window_minutes: int = Query(30, ge=1, le=10080),
    bucket_seconds: Optional[int] = Query(None, ge=10, le=86400),
    since: Optional[datetime] = Query(None, description="Override window: start"),
    until: Optional[datetime] = Query(None, description="Override window: end"),
):
    """Time-bucketed event series + counters for a single room.

    Mirrors `/admin/tiktok/rooms/{room_id}/stats` but sanitizes the
    `active_match` payload through `_sanitize_match` so the inner
    match dict goes through the same allowlist copy as `/matches`.
    Everything else in the response shape is either room identity,
    public TikTok counters, or a server-derived bucket.
    """
    svc = _require_service()
    _resolve_public_room(room_id)
    data = svc.get_room_stats(
        room_id,
        window_minutes=window_minutes,
        bucket_seconds=bucket_seconds,
        since=since,
        until=until,
    )
    # Allowlist-copy the active_match payload (and only that payload).
    am = data.get("active_match")
    if am:
        data["active_match"] = _sanitize_match(am)
    _set_cache_headers(response)
    return data


@router.get("/tiktok/rooms/{room_id}/gifters")
def public_room_gifters(
    room_id: int,
    response: Response,
    since: Optional[datetime] = Query(None, description="Window start (inclusive)"),
    until: Optional[datetime] = Query(None, description="Window end (exclusive)"),
    q: Optional[str] = Query(None, description="Match nickname or @unique_id"),
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
    room_ids: Optional[str] = Query(
        None,
        description=(
            "Optional comma-separated extra room ids — included alongside the "
            "path room_id (every id must belong to the SAME public host)."
        ),
    ),
):
    """Top gifters table — pass-through. TikTok's own gift leaderboard
    is public, so the row shape (user_id, unique_id, nickname,
    avatar_url, gifts, diamonds) has no operator-only fields."""
    svc = _require_service()
    _resolve_public_room(room_id)
    extras: list[int] = []
    if room_ids:
        parsed = [int(x.strip()) for x in room_ids.split(",") if x.strip().isdigit()]
        # Validate every additional id belongs to a public host.
        # Skip the path room_id (already checked above).
        if parsed:
            _resolve_public_room_set(parsed)
            extras = parsed
    target: int | list[int]
    target = list({int(room_id), *extras}) if extras else int(room_id)
    _set_cache_headers(response)
    return svc.get_room_gifters(
        target, since=since, until=until, q=q, limit=limit, offset=offset,
    )


@router.get("/tiktok/rooms/{room_id}/recipients")
def public_room_recipients(
    room_id: int,
    response: Response,
    since: Optional[datetime] = Query(None, description="Window start (inclusive)"),
    until: Optional[datetime] = Query(None, description="Window end (exclusive)"),
    limit: int = Query(20, ge=1, le=200),
):
    """Per-recipient diamond split. Row shape is the same as the
    admin endpoint — only public identity + gift counters."""
    svc = _require_service()
    _resolve_public_room(room_id)
    _set_cache_headers(response)
    return svc.get_room_recipients(room_id, since=since, until=until, limit=limit)


@router.get("/tiktok/buckets/aggregated")
def public_aggregated_buckets(
    response: Response,
    room_ids: str = Query(
        ..., description="Comma-separated list of room ids to aggregate.",
    ),
    since: datetime = Query(..., description="Window start (inclusive)"),
    until: datetime = Query(..., description="Window end (inclusive)"),
    bucket_seconds: Optional[int] = Query(None, ge=10, le=86400),
):
    """Day-aggregate bucket series — EVERY room id must belong to a
    public host. Returns the same `{starts, by_type, diamonds,
    diamonds_total}` shape as the admin endpoint."""
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
    _resolve_public_room_set(ids)
    _set_cache_headers(response)
    return svc.get_aggregated_buckets(
        ids, since=since, until=until, bucket_seconds=bucket_seconds,
    )


@router.get("/tiktok/matches")
def public_matches(
    response: Response,
    handle: str = Query(..., min_length=1, max_length=64),
    room_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """List PK battles for one public host. `handle` is required so
    we can gate on `is_public`. If `room_id` is provided, validate
    it belongs to the same public host (defense in depth)."""
    svc = _require_service()
    sub = _resolve_public_host(handle)
    if room_id is not None:
        room_sub = _resolve_public_room(room_id)
        if (room_sub.unique_id or "").lower() != (sub.unique_id or "").lower():
            # Caller passed a public room but for a different host.
            raise HTTPException(status_code=404, detail="not found")
    matches = svc.list_matches(
        host_unique_id=sub.unique_id, room_id=room_id, limit=limit,
    )
    # Enrich with diamonds_total + derived result (same as admin path).
    from routes.admin.tiktok import _derive_match_result, _serialize_opponent
    diamonds = svc.match_diamonds_totals([m.id for m in matches if m.id is not None])
    _set_cache_headers(response)
    out: list[dict[str, Any]] = []
    for m in matches:
        out.append(_sanitize_match({
            "id": m.id or 0,
            "room_id": str(m.room_id),
            "battle_id": str(m.battle_id),
            "opponents": [_serialize_opponent(o) for o in (m.opponents or [])],
            "scores": m.scores or {},
            "settings": m.settings or {},
            "winner_user_id": str(m.winner_user_id) if m.winner_user_id else None,
            "started_at": m.started_at.isoformat() if m.started_at else None,
            "ended_at": m.ended_at.isoformat() if m.ended_at else None,
            "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
            "diamonds_total": int(diamonds.get(m.id or 0, 0)),
            "result": _derive_match_result(m, sub.unique_id),
        }))
    return out


@router.get("/tiktok/matches/{match_id}")
def public_match_detail(match_id: int, response: Response):
    """Single match. Returns the same enriched `MatchResponse` shape
    as the admin counterpart."""
    svc = _require_service()
    match, sub = _resolve_public_match(match_id)
    from routes.admin.tiktok import _derive_match_result, _serialize_opponent
    diamonds = svc.match_diamonds_totals([match.id]) if match.id else {}
    _set_cache_headers(response)
    return _sanitize_match({
        "id": match.id or 0,
        "room_id": str(match.room_id),
        "battle_id": str(match.battle_id),
        "opponents": [_serialize_opponent(o) for o in (match.opponents or [])],
        "scores": match.scores or {},
        "settings": match.settings or {},
        "winner_user_id": str(match.winner_user_id) if match.winner_user_id else None,
        "started_at": match.started_at.isoformat() if match.started_at else None,
        "ended_at": match.ended_at.isoformat() if match.ended_at else None,
        "last_seen_at": match.last_seen_at.isoformat() if match.last_seen_at else None,
        "diamonds_total": int(diamonds.get(match.id or 0, 0)),
        "result": _derive_match_result(match, sub.unique_id),
    })


@router.get("/tiktok/matches/{match_id}/score_timeline")
def public_match_score_timeline(match_id: int, response: Response):
    """Per-second decoded score frames for a match. Each row is
    `{ts, scores: {key: int}}` — no operator-only fields, pure
    public PK scoreboard data."""
    svc = _require_service()
    _resolve_public_match(match_id)
    _set_cache_headers(response)
    return svc.get_match_score_timeline(match_id)


@router.get("/tiktok/matches/{match_id}/gifters_by_side")
def public_match_gifters_by_side(match_id: int, response: Response):
    """Side-balance + per-side gifter rows. Each gifter row is
    public identity + gift counters.

    `public_only=True` is passed to the service so sibling match rows
    (the rival's parallel `tiktok_matches` row when they're also a
    tracked host) are filtered to public-opted hosts before their
    `room_id` is surfaced in `totals.sibling_room_ids` or their gift
    events are merged into the opponent bucket. Without that filter
    a PK between a public host and a tracked-but-private host would
    leak the private host's room_id and viewer base to anonymous
    callers.
    """
    svc = _require_service()
    _resolve_public_match(match_id)
    _set_cache_headers(response)
    return svc.get_match_gifters_by_side(match_id, public_only=True)


@router.get("/tiktok/matches/{match_id}/head_to_head")
def public_match_head_to_head(
    match_id: int,
    response: Response,
    limit: int = Query(50, ge=1, le=200),
):
    """Prior PK battles between this host and the same opponent(s).
    The row shape (id, battle_id, room_id, opponents, scores,
    winner, host_score/opp_score/margin/outcome/decisive_pct/
    duration_seconds, diamonds_total) is all public-PK derivable."""
    svc = _require_service()
    _resolve_public_match(match_id)
    _set_cache_headers(response)
    return svc.get_match_head_to_head(match_id, limit=limit)


@router.get("/tiktok/matches/{match_id}/h2h_common_gifters")
def public_match_h2h_common_gifters(
    match_id: int,
    response: Response,
    min_battles: int = Query(2, ge=1, le=20),
    limit: int = Query(12, ge=1, le=50),
):
    """Viewers who gifted in ≥`min_battles` of this match's H2H set.
    Row shape is public gifter identity + per-match counter list."""
    svc = _require_service()
    _resolve_public_match(match_id)
    _set_cache_headers(response)
    return svc.get_h2h_common_gifters(
        match_id, min_battles=min_battles, limit=limit,
    )


@router.get("/tiktok/events/search")
def public_events_search(
    response: Response,
    room_ids: str = Query(
        ...,
        description=(
            "Required: comma-separated room ids. Every id must belong "
            "to a public host."
        ),
    ),
    user_id: Optional[str] = None,
    match_id: Optional[int] = None,
    type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=2000),
    before_id: Optional[int] = None,
    offset: int = Query(0, ge=0),
    to_user_id: Optional[str] = None,
    min_diamonds: Optional[int] = Query(None, ge=0),
):
    """Event search scoped to a public-room set. Required: `room_ids`
    — we deliberately don't expose the `host` / cross-host shape on
    the public surface (cross-host events would need a per-event
    public check, which is too slow for the search path)."""
    svc = _require_service()
    parsed_ids: list[int] = []
    for raw in room_ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed_ids.append(int(raw))
        except ValueError:
            continue
    if not parsed_ids:
        raise HTTPException(status_code=400, detail="room_ids must be a non-empty comma-separated list of integers")
    _resolve_public_room_set(parsed_ids)

    parsed_user_id: Optional[int] = None
    if user_id is not None and user_id != "":
        try:
            parsed_user_id = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid user_id: {user_id!r}")
    parsed_to_user_id: Optional[int] = None
    if to_user_id is not None and to_user_id != "":
        try:
            parsed_to_user_id = int(to_user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid to_user_id: {to_user_id!r}")
    if match_id is not None:
        # The match must belong to one of the validated rooms; gate
        # to avoid a sideways read of a private match via match_id.
        match = svc._persistence.get_match_by_id(int(match_id))
        if match is None or int(match.room_id) not in set(parsed_ids):
            raise HTTPException(status_code=404, detail="not found")

    rows = svc.search_events(
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
    _set_cache_headers(response)
    return [_sanitize_event(r) for r in rows]


@router.get("/tiktok/events/count")
def public_events_count(
    response: Response,
    room_ids: str = Query(
        ...,
        description=(
            "Required: comma-separated room ids. Every id must belong "
            "to a public host."
        ),
    ),
    user_id: Optional[str] = None,
    match_id: Optional[int] = None,
    type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    q: Optional[str] = None,
    to_user_id: Optional[str] = None,
    min_diamonds: Optional[int] = Query(None, ge=0),
):
    """Pagination counterpart to `/events/search` — same filter
    surface, returns `{total: N}`."""
    svc = _require_service()
    parsed_ids: list[int] = []
    for raw in room_ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed_ids.append(int(raw))
        except ValueError:
            continue
    if not parsed_ids:
        raise HTTPException(status_code=400, detail="room_ids must be a non-empty comma-separated list of integers")
    _resolve_public_room_set(parsed_ids)

    parsed_user_id: Optional[int] = None
    if user_id is not None and user_id != "":
        try:
            parsed_user_id = int(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid user_id: {user_id!r}")
    parsed_to_user_id: Optional[int] = None
    if to_user_id is not None and to_user_id != "":
        try:
            parsed_to_user_id = int(to_user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid to_user_id: {to_user_id!r}")
    if match_id is not None:
        match = svc._persistence.get_match_by_id(int(match_id))
        if match is None or int(match.room_id) not in set(parsed_ids):
            raise HTTPException(status_code=404, detail="not found")

    total = svc.count_events(
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
    _set_cache_headers(response)
    return {"total": int(total)}


@router.get("/tiktok/users/{user_id}/matches")
def public_user_matches(
    user_id: int,
    response: Response,
    room_ids: str = Query(
        ...,
        description=(
            "Required: comma-separated room ids. Every id must belong "
            "to a public host. Cross-host listing is intentionally "
            "not exposed on the public surface."
        ),
    ),
    since: Optional[datetime] = Query(None, description="Lower-bound on gift ts."),
    until: Optional[datetime] = Query(None, description="Upper-bound on gift ts (exclusive)."),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Per-user match contribution list scoped to a public-room set.

    Note: the admin counterpart allows `room_ids=None` (cross-host),
    but we require it here — the public surface should never leak
    matches across non-public hosts via a user's gift history.
    """
    svc = _require_service()
    parsed_ids: list[int] = []
    for raw in room_ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed_ids.append(int(raw))
        except ValueError:
            continue
    if not parsed_ids:
        raise HTTPException(status_code=400, detail="room_ids must be a non-empty comma-separated list of integers")
    _resolve_public_room_set(parsed_ids)
    _set_cache_headers(response)
    return svc.list_user_matches(
        user_id=int(user_id),
        room_ids=parsed_ids,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/tiktok/users/{user_id}/host-daily-series")
def public_user_host_daily_series(
    user_id: int,
    response: Response,
    handle: str = Query(..., description="Host handle to scope to."),
    days: int = Query(30, ge=1, le=180),
):
    """Public mirror of `/admin/tiktok/users/{user_id}/host-daily-series`.

    The host must be `is_public=True`; resolved via `_resolve_public_host`
    so unknown / private handles 404 with no info leak.
    """
    _resolve_public_host(handle)
    svc = _require_service()
    _set_cache_headers(response)
    return svc.get_user_host_daily_series(
        user_id=int(user_id),
        host_unique_id=handle.lstrip("@"),
        days=int(days),
    )

"""User-facing TikTok monitoring routes.

Mounted at `/tiktok/*` (NOT under `/admin/*`). Any authenticated user
with credits can add a TikTok handle to monitor; the cost is 1 credit
per add, refundable in full within 24 h of the add.

Ownership gate on every endpoint: a user can only see / mutate
subscriptions whose `owner_user_id` matches `current_user.id`. Hitting
someone else's handle returns 404 (same shape as "doesn't exist") so
the API doesn't leak whether a handle is monitored by another user.

`is_public` toggle + worker-control endpoints intentionally live in
`/admin/tiktok/*` only. Public visibility is an operator decision,
not a per-user one.

`credit_service` and `tiktok_service` are injected by
`routes/main.py:setup_routes`. Both must be wired or every endpoint
returns 503.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from domain.entities.auth_models import AuthContext
from routes.auth import get_current_user_swagger_compatible as get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tiktok", tags=["User TikTok"])

# Injected by setup_routes. None at import time; runtime-resolved
# via _require_service / _require_credit at every request.
tiktok_service = None  # type: ignore[assignment]
credit_service = None  # type: ignore[assignment]


# ── service access guards ──────────────────────────────────────────


def _require_service():
    if tiktok_service is None:
        raise HTTPException(status_code=503, detail="TikTok service unavailable")
    return tiktok_service


def _require_credit():
    if credit_service is None:
        raise HTTPException(status_code=503, detail="Credit service unavailable")
    return credit_service


# ── ownership guards ───────────────────────────────────────────────


def _own_or_404(sub: Any, user_id: int):
    """Refuse with 404 unless `sub` is owned by `user_id`. Uniform
    404 (never 403) so the response doesn't tell the user "this
    handle exists, just not for you" — same defensive shape as the
    public-mirror resolvers."""
    if sub is None or int(getattr(sub, "owner_user_id", 0) or 0) != int(user_id):
        raise HTTPException(status_code=404, detail="not found")
    return sub


async def _resolve_owned_handle(handle: str, user_id: int):
    """Resolve `@handle` → Subscription dataclass, refuse with 404
    unless current user owns it. Used by every per-handle route."""
    svc = _require_service()
    cleaned = (handle or "").lstrip("@").strip()
    if not cleaned:
        raise HTTPException(status_code=404, detail="not found")
    sub = await asyncio.to_thread(svc._persistence.get_subscription, cleaned)
    return _own_or_404(sub, user_id)


async def _resolve_owned_room(room_id: int, user_id: int):
    """Resolve `room_id` → host_unique_id → owned sub. Same 404
    semantics as `_resolve_owned_handle`."""
    svc = _require_service()
    try:
        rid = int(room_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="not found")
    host = await asyncio.to_thread(svc._persistence.get_room_host_handle, rid)
    if not host:
        raise HTTPException(status_code=404, detail="not found")
    return await _resolve_owned_handle(host, user_id)


# ── request models ─────────────────────────────────────────────────


class AddMonitorRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    profile: Optional[dict[str, Any]] = Field(
        None,
        description=(
            "Optional pre-fetched profile payload (same shape the "
            "/tiktok/lookup endpoint returns). Seeds the cached "
            "profile fields immediately so the lives table shows "
            "avatar/nickname without waiting for the background "
            "refresh — and saves a redundant Euler/SIGI call."
        ),
    )


# ── credit balance ─────────────────────────────────────────────────


@router.get("/credits")
async def my_credits(current_user: AuthContext = Depends(get_current_user)):
    """Current credit balance for the authenticated user. Drives the
    'You have N credits, add monitor costs 1' UI prompt."""
    cs = _require_credit()
    balance = await asyncio.to_thread(cs.get_credit_balance, int(current_user.user.id))
    return {"balance": int(balance)}


# ── subscription CRUD ──────────────────────────────────────────────


@router.get("/lives")
async def list_my_lives(current_user: AuthContext = Depends(get_current_user)):
    """List the authenticated user's monitored handles. Returns the
    SAME shape as `/admin/tiktok/lives` (so the frontend can reuse
    the existing card components) but filtered to
    `owner_user_id = current_user.id`."""
    svc = _require_service()
    uid = int(current_user.user.id)
    # Single-host filter against the existing list-all path is the
    # cheapest correct option for now (no extra index needed since
    # `ix_tiktok_subscriptions_owner_enabled` from the ownership
    # migration covers it). If user counts grow, push the filter into
    # a dedicated persistence method.
    all_subs = await svc.list_subscriptions()
    return [s for s in all_subs if int(s.get("owner_user_id") or 0) == uid]


@router.post("/lives", status_code=status.HTTP_201_CREATED)
async def add_my_live(
    req: AddMonitorRequest,
    current_user: AuthContext = Depends(get_current_user),
):
    """Add a TikTok handle to the authenticated user's monitored
    list. **Costs 1 credit.** Refuses with HTTP 402 (Payment
    Required) when the user has 0 credits; refuses with HTTP 409
    when the handle is already monitored by SOMEONE — duplicate
    subscriptions across users break the listener pool's invariant
    (one row per @handle).

    Idempotency:
      - If the user re-POSTs the same handle they already own → 200
        with the existing row, no credit debit (treat as no-op).
      - If another user owns the handle → 409 (the listener pool
        invariant is one row per @handle; we don't multi-tenant
        the actual WS connection, just the visibility surface).
    """
    svc = _require_service()
    cs = _require_credit()
    uid = int(current_user.user.id)
    handle = req.username.lstrip("@").strip()
    if not handle:
        raise HTTPException(status_code=400, detail="username required")

    # Existing-row check — gates both the same-user idempotent return
    # and the cross-user 409.
    existing = await asyncio.to_thread(svc._persistence.get_subscription, handle)
    if existing is not None:
        if int(existing.owner_user_id or 0) == uid:
            # Same user re-adding their own handle — no charge, just
            # return the current state.
            return {"sub": existing.__dict__, "credit_debited": False}
        raise HTTPException(
            status_code=409,
            detail="handle already monitored by another user",
        )

    # Credit-first: refuse before we touch the subscription table so
    # the user never sees "sub created but credit failed" weirdness.
    balance = await asyncio.to_thread(cs.get_credit_balance, uid)
    if balance < 1:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credits (have {balance}, need 1).",
        )

    # Debit BEFORE create — if create fails we refund. This ordering
    # protects against the "create succeeded but debit failed" race
    # where a user gets a free monitor.
    await asyncio.to_thread(cs.consume_for_tiktok_monitor, uid, handle)
    try:
        sub = await svc.create_subscription(
            handle,
            owner_user_id=uid,
            enabled=True,
            profile=req.profile,
        )
    except Exception:
        # Compensating refund — the user paid but we couldn't deliver.
        try:
            await asyncio.to_thread(cs.refund_tiktok_monitor, uid, handle)
        except Exception:
            logger.exception(
                "refund_tiktok_monitor failed during create_subscription "
                "compensation for user=%s handle=%s — manual ledger fix needed",
                uid, handle,
            )
        raise

    return {"sub": sub.__dict__, "credit_debited": True}


@router.delete("/lives/{handle}")
async def remove_my_live(
    handle: str,
    current_user: AuthContext = Depends(get_current_user),
):
    """Remove one of the authenticated user's monitors. **Refunds 1
    credit** when removed within 24 h of the original add; otherwise
    no refund. Refuses with 404 if the handle isn't owned by the
    caller (uniform 404 — same shape as 'doesn't exist')."""
    svc = _require_service()
    cs = _require_credit()
    uid = int(current_user.user.id)
    cleaned = (handle or "").lstrip("@").strip()
    if not cleaned:
        raise HTTPException(status_code=404, detail="not found")

    # Ownership gate BEFORE delete — same 404 shape whether the row
    # doesn't exist or belongs to someone else.
    await _resolve_owned_handle(cleaned, uid)

    result = await svc.delete_subscription(cleaned)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="not found")

    refunded = False
    if result["within_refund_window"]:
        try:
            await asyncio.to_thread(cs.refund_tiktok_monitor, uid, cleaned)
            refunded = True
        except Exception:
            logger.exception(
                "Refund failed after delete for user=%s handle=%s — "
                "manual ledger fix needed",
                uid, cleaned,
            )
    return {"deleted": True, "refunded": refunded}


# ── per-handle reads (mirror admin shape) ──────────────────────────


@router.get("/lives/{handle}")
async def get_my_live(
    handle: str,
    current_user: AuthContext = Depends(get_current_user),
):
    """Single-sub detail. Same shape as `/admin/tiktok/lives/{handle}`.
    Ownership-gated 404."""
    svc = _require_service()
    sub = await _resolve_owned_handle(handle, int(current_user.user.id))
    # Wrap the persistence-dataclass in the same admin-summary slice
    # the lives-list page uses so the frontend card component works
    # without conditional rendering.
    summary = await asyncio.to_thread(svc.get_lives_summary, [sub.unique_id])
    row = summary.get(sub.unique_id.lstrip("@").lower(), {}) or {}
    return {"sub": sub.__dict__, "summary": row}


@router.get("/lives/{handle}/calendar")
async def my_live_calendar(
    handle: str,
    weeks: int = Query(26, ge=1, le=104),
    tz: str = Query("UTC"),
    current_user: AuthContext = Depends(get_current_user),
):
    svc = _require_service()
    sub = await _resolve_owned_handle(handle, int(current_user.user.id))
    return await asyncio.to_thread(
        svc.host_calendar, sub.unique_id, weeks=weeks, tz=tz,
    )


@router.get("/lives/{handle}/rooms")
async def my_live_rooms(
    handle: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: AuthContext = Depends(get_current_user),
):
    svc = _require_service()
    sub = await _resolve_owned_handle(handle, int(current_user.user.id))
    rooms, totals = await asyncio.to_thread(
        svc.list_host_rooms_with_totals, sub.unique_id, limit=limit,
    )
    out: list[dict[str, Any]] = []
    for r in rooms:
        out.append({
            "room_id":        str(r.room_id),
            "host_unique_id": r.host_unique_id,
            "title":          r.title,
            "started_at":     r.started_at.isoformat() if r.started_at else None,
            "ended_at":       r.ended_at.isoformat() if r.ended_at else None,
            "first_seen_at":  r.first_seen_at.isoformat() if r.first_seen_at else None,
            "last_seen_at":   r.last_seen_at.isoformat() if r.last_seen_at else None,
            "diamonds":       totals.get(int(r.room_id), {}).get("diamonds"),
            "matches":        totals.get(int(r.room_id), {}).get("matches"),
            "likes":          totals.get(int(r.room_id), {}).get("likes"),
        })
    return out


@router.get("/rooms/{room_id}/stats")
async def my_room_stats(
    room_id: int,
    window_minutes: int = Query(30, ge=1, le=10080),
    bucket_seconds: Optional[int] = Query(None, ge=10, le=86400),
    current_user: AuthContext = Depends(get_current_user),
):
    svc = _require_service()
    await _resolve_owned_room(room_id, int(current_user.user.id))
    return await asyncio.to_thread(
        svc.get_room_stats,
        room_id,
        window_minutes=window_minutes,
        bucket_seconds=bucket_seconds,
    )

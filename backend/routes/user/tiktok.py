"""User-facing TikTok credit + monitor-CRUD endpoints.

After the 2026-05-19 architectural rollback, this file has shrunk
to ONLY the credit-debit / add-monitor / remove-monitor flow. The
rich read endpoints I built here (rooms, calendar, matches, etc.)
were a duplication mistake — admin's existing `routes/admin/tiktok.py`
handlers already exist for every read shape. The correct
architectural move (Phase 2) is to rename those handlers' URL prefix
from `/admin/tiktok/*` to `/tiktok/*` and add an ownership filter
inside each handler, rather than mirror them in a parallel module.

Endpoints here:
  GET    /tiktok/credits                 — balance
  POST   /tiktok/lives                   — add monitor (1 credit)
  DELETE /tiktok/lives/{handle}          — remove (refund within 24 h)

`credit_service` and `tiktok_service` are injected by
`routes/main.py:setup_routes`. Both must be wired or every endpoint
returns 503.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from domain.entities.auth_models import AuthContext
from routes.auth import get_current_user_swagger_compatible as get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tiktok", tags=["User TikTok"])

# Injected by setup_routes. None at import time.
tiktok_service = None  # type: ignore[assignment]
credit_service = None  # type: ignore[assignment]


def _require_service():
    if tiktok_service is None:
        raise HTTPException(status_code=503, detail="TikTok service unavailable")
    return tiktok_service


def _require_credit():
    if credit_service is None:
        raise HTTPException(status_code=503, detail="Credit service unavailable")
    return credit_service


class AddMonitorRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    profile: Optional[dict[str, Any]] = Field(
        None,
        description=(
            "Optional pre-fetched profile payload — same shape the "
            "`/admin/tiktok/lookup` endpoint returns. Seeds the cached "
            "profile fields immediately so the lives table shows "
            "avatar/nickname without waiting for the background refresh."
        ),
    )


# ── credit balance ─────────────────────────────────────────────────


@router.get("/credits")
async def my_credits(current_user: AuthContext = Depends(get_current_user)):
    """Current credit balance for the authenticated user. Drives the
    'You have N credits, Add monitor costs 1' UI prompt."""
    cs = _require_credit()
    balance = await asyncio.to_thread(cs.get_credit_balance, int(current_user.user.id))
    return {"balance": int(balance)}


# ── monitor CRUD (credit-gated) ────────────────────────────────────


@router.post("/lives", status_code=status.HTTP_201_CREATED)
async def add_my_live(
    req: AddMonitorRequest,
    current_user: AuthContext = Depends(get_current_user),
):
    """Add a TikTok handle to the authenticated user's monitor list.
    **Costs 1 credit.**

      - 402 (Payment Required) when balance < 1.
      - 409 (Conflict) when the handle is already monitored by ANOTHER
        user. Same-user re-add is idempotent and returns the existing
        sub without debiting.

    Phase 2 (URL repoint) will fold this into admin's `createLive`
    endpoint so the single handler does ownership + credit-debit
    based on the caller's role. Keeping it separate for now so the
    credit-machinery stays unambiguous.
    """
    svc = _require_service()
    cs = _require_credit()
    uid = int(current_user.user.id)
    handle = req.username.lstrip("@").strip()
    if not handle:
        raise HTTPException(status_code=400, detail="username required")

    existing = await asyncio.to_thread(svc._persistence.get_subscription, handle)
    if existing is not None:
        if int(existing.owner_user_id or 0) == uid:
            return {"sub": existing.__dict__, "credit_debited": False}
        raise HTTPException(
            status_code=409,
            detail="handle already monitored by another user",
        )

    balance = await asyncio.to_thread(cs.get_credit_balance, uid)
    if balance < 1:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credits (have {balance}, need 1).",
        )

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
    credit** when removed within 24 h of the original add. Returns
    404 if the handle isn't owned by the caller (uniform 404 — same
    shape as 'doesn't exist')."""
    svc = _require_service()
    cs = _require_credit()
    uid = int(current_user.user.id)
    cleaned = (handle or "").lstrip("@").strip()
    if not cleaned:
        raise HTTPException(status_code=404, detail="not found")

    # Ownership gate.
    sub = await asyncio.to_thread(svc._persistence.get_subscription, cleaned)
    if sub is None or int(getattr(sub, "owner_user_id", 0) or 0) != uid:
        raise HTTPException(status_code=404, detail="not found")

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

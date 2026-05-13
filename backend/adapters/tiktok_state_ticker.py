"""Phase 9B — periodic refresh of age-derived state-cache fields.

The per-host state cache stores raw timestamps in aux fields
(`_last_gift_at`, `_last_comment_at`, `_last_pause_at`,
`_last_event_at`, `_active_poll_at`). The current
`get_lives_summary` SQL output uses *age* values (seconds since the
event) — to maintain parity, we need to recompute those ages on a
clock-driven cadence so client-visible `last_*_age_s` fields keep
ticking even when no events arrive.

Cadence: 5 s. Only active hosts (`active_room_id` set) produce a
publish; idle hosts are skipped to keep the publish traffic
proportional to live count rather than tracked-handle count.

Deployment:
- `in_process` mode → started from `api_main.py:lifespan`.
- `worker` mode → started from the listener CLI
  (`cli/commands/system/tiktok.py:run-listener`).

The factory ensures exactly one tick task is running per state-cache
backing (Redis or in-process) regardless of deployment shape.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ports.tiktok_state_cache import TikTokStateCachePort

logger = logging.getLogger(__name__)


# Tick cadence. Five seconds is the sweet spot: clients see age
# fields advance in human-perceivable jumps without flooding the
# wire (active host count is small, typically 5-15 at peak, so 5 s
# × 10 active hosts ≈ 2 deltas/sec).
_TICK_INTERVAL_S = 5.0

# Active poll expiry. TikTok fires `message_type=2` events every
# few seconds while a poll is open; absence of one for this long
# implies the poll dropped. Matches the existing summary semantic.
_POLL_TTL_S = 60.0


async def run_state_tick_loop(
    state_cache: TikTokStateCachePort,
    *,
    interval_s: float = _TICK_INTERVAL_S,
    poll_ttl_s: float = _POLL_TTL_S,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Forever loop. Cancellable via `stop_event` (for clean shutdown
    in deployments that own a stop signal) or via `task.cancel()`."""
    logger.info(
        "state-cache tick task started (interval=%.1fs, poll_ttl=%.1fs)",
        interval_s, poll_ttl_s,
    )
    try:
        while True:
            try:
                # Tick body runs in a thread so it doesn't block the
                # event loop. State-cache operations are sync (the
                # adapter's get / apply_patch are sync), and the in-
                # process adapter holds a threading.Lock briefly per
                # host — keeping all that off the loop is the right
                # call.
                await asyncio.to_thread(_tick_once, state_cache, poll_ttl_s)
            except Exception:
                logger.exception("state tick failed (continuing)")

            # Sleep with cancel-aware wait. If `stop_event` is set
            # mid-wait, we exit promptly.
            if stop_event is None:
                await asyncio.sleep(interval_s)
            else:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=interval_s,
                    )
                    return  # stop_event fired
                except asyncio.TimeoutError:
                    pass  # next iteration
    except asyncio.CancelledError:
        logger.info("state-cache tick task cancelled")
        raise


def _tick_once(state_cache: TikTokStateCachePort, poll_ttl_s: float) -> None:
    """One sweep. Reads `list_versions()` to find known hosts,
    inspects each for activeness, and publishes age updates.

    Implemented as a plain sync function so the test suite can drive
    it directly without a running event loop."""
    now = datetime.now(timezone.utc)
    versions = state_cache.list_versions()
    for host in versions:
        cached = state_cache.get(host)
        if not cached:
            continue
        _, state = cached
        if not state.get("active_room_id"):
            continue  # idle host — no publish
        patch = _build_age_patch(state, now, poll_ttl_s)
        if patch:
            state_cache.apply_patch(host, patch)


def _build_age_patch(
    state: dict[str, Any],
    now: datetime,
    poll_ttl_s: float,
) -> dict[str, Any]:
    """Compute the per-host patch for a single tick. Returns `{}`
    when nothing changed (no publish needed)."""
    patch: dict[str, Any] = {}

    # Age fields. For each `(visible, aux_at_key)` pair, compute
    # seconds-since-last and only emit if the value changed by at
    # least 1 s (avoids hammering subscribers with no-op deltas).
    age_pairs = (
        ("last_gift_age_s",    "_last_gift_at"),
        ("last_comment_age_s", "_last_comment_at"),
        ("last_event_age_s",   "_last_event_at"),
        ("last_pause_age_s",   "_last_pause_at"),
    )
    for visible_key, aux_key in age_pairs:
        ts_iso = state.get(aux_key)
        if not ts_iso:
            continue
        new_age = _age_seconds(ts_iso, now)
        if new_age is None:
            continue
        cur = state.get(visible_key)
        if cur != new_age:
            patch[visible_key] = new_age

    # active_poll: bump `fresh_age_s` OR expire if past TTL.
    active_poll = state.get("active_poll")
    poll_at = state.get("_active_poll_at")
    if active_poll and poll_at:
        elapsed = _age_seconds(poll_at, now)
        if elapsed is not None:
            if elapsed > poll_ttl_s:
                patch["active_poll"] = None
            else:
                # Deep-merge updates the field in place — title +
                # poll_id stay put, only fresh_age_s ticks.
                if active_poll.get("fresh_age_s") != elapsed:
                    patch["active_poll"] = {"fresh_age_s": elapsed}

    return patch


def _age_seconds(ts_iso: Any, now: datetime) -> int | None:
    """Parse an ISO-8601 string (or datetime) and return integer
    seconds since `now`. Returns None on parse failure or future
    timestamps (clock skew safety)."""
    if ts_iso is None:
        return None
    try:
        if isinstance(ts_iso, datetime):
            dt = ts_iso
        else:
            dt = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
        delta = (now - dt).total_seconds()
        if delta < 0:
            return 0
        return int(delta)
    except (ValueError, TypeError):
        return None

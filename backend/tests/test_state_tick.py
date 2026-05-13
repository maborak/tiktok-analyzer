"""Phase 9B — tick task tests.

The tick task is a plain async loop calling `_tick_once` every 5 s.
Tests drive `_tick_once` directly (sync) so we don't need an event
loop fixture. The loop's cancellability + interval logic is
exercised by a single async test at the bottom.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from adapters.tiktok_state_cache_inproc import TikTokStateCacheInProc
from adapters.tiktok_state_ticker import (
    _build_age_patch,
    _tick_once,
    run_state_tick_loop,
)


@pytest.fixture
def cache() -> TikTokStateCacheInProc:
    return TikTokStateCacheInProc(public_sanitizer=None)


def _iso_ago(seconds: int) -> str:
    """ISO timestamp `seconds` ago (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


# ── _build_age_patch ────────────────────────────────────────────────


def test_age_patch_empty_when_no_aux_timestamps():
    state = {"active_room_id": "1"}
    patch = _build_age_patch(state, datetime.now(timezone.utc), 60.0)
    assert patch == {}


def test_age_patch_computes_last_gift_age():
    state = {
        "active_room_id": "1",
        "_last_gift_at": _iso_ago(42),
    }
    patch = _build_age_patch(state, datetime.now(timezone.utc), 60.0)
    assert patch["last_gift_age_s"] == 42


def test_age_patch_skips_when_unchanged():
    """If the current `last_gift_age_s` already matches the computed
    one, no publish. Avoids hammering subscribers with no-op deltas
    when no time has passed between ticks (artificial test setup,
    but real-world race when ticks land within the same second)."""
    now = datetime.now(timezone.utc)
    ts = now - timedelta(seconds=42)
    state = {
        "active_room_id": "1",
        "_last_gift_at": ts.isoformat(),
        "last_gift_age_s": 42,  # already correct
    }
    patch = _build_age_patch(state, now, 60.0)
    assert "last_gift_age_s" not in patch


def test_age_patch_handles_all_four_aux_fields():
    state = {
        "active_room_id": "1",
        "_last_gift_at": _iso_ago(10),
        "_last_comment_at": _iso_ago(20),
        "_last_pause_at": _iso_ago(30),
        "_last_event_at": _iso_ago(5),
    }
    patch = _build_age_patch(state, datetime.now(timezone.utc), 60.0)
    assert patch["last_gift_age_s"] == 10
    assert patch["last_comment_age_s"] == 20
    assert patch["last_pause_age_s"] == 30
    assert patch["last_event_age_s"] == 5


def test_age_patch_active_poll_ticks_fresh_age():
    state = {
        "active_room_id": "1",
        "active_poll": {"title": "?", "poll_id": "p", "fresh_age_s": 0},
        "_active_poll_at": _iso_ago(15),
    }
    patch = _build_age_patch(state, datetime.now(timezone.utc), 60.0)
    # Deep-merge: only `fresh_age_s` changes; title + poll_id preserved
    # in cache because deep-merge keeps them.
    assert patch["active_poll"] == {"fresh_age_s": 15}


def test_age_patch_active_poll_expires_past_ttl():
    state = {
        "active_room_id": "1",
        "active_poll": {"title": "?", "poll_id": "p", "fresh_age_s": 0},
        "_active_poll_at": _iso_ago(120),  # well past 60s TTL
    }
    patch = _build_age_patch(state, datetime.now(timezone.utc), 60.0)
    assert patch["active_poll"] is None


def test_age_patch_clock_skew_negative_age_clamped_to_zero():
    state = {
        "active_room_id": "1",
        "_last_gift_at": (
            datetime.now(timezone.utc) + timedelta(seconds=30)
        ).isoformat(),  # future timestamp (clock skew)
    }
    patch = _build_age_patch(state, datetime.now(timezone.utc), 60.0)
    assert patch["last_gift_age_s"] == 0


def test_age_patch_handles_malformed_timestamp():
    state = {
        "active_room_id": "1",
        "_last_gift_at": "not a date",
    }
    patch = _build_age_patch(state, datetime.now(timezone.utc), 60.0)
    # No emission for an unparseable timestamp — silently skipped.
    assert "last_gift_age_s" not in patch


# ── _tick_once ──────────────────────────────────────────────────────


def test_tick_skips_idle_hosts(cache):
    """Hosts without `active_room_id` are idle — no publish."""
    cache.set("idle", version=1, data={
        "_last_gift_at": _iso_ago(99),
    })
    _tick_once(cache, poll_ttl_s=60.0)
    _, data = cache.get("idle")
    # `last_gift_age_s` was never set by the tick because the host is idle.
    assert "last_gift_age_s" not in data


def test_tick_publishes_for_active_hosts(cache):
    cache.set("live", version=1, data={
        "active_room_id": "1",
        "_last_gift_at": _iso_ago(7),
    })
    _tick_once(cache, poll_ttl_s=60.0)
    _, data = cache.get("live")
    assert data["last_gift_age_s"] == 7


def test_tick_bumps_version(cache):
    cache.set("live", version=5, data={
        "active_room_id": "1",
        "_last_gift_at": _iso_ago(5),
    })
    _tick_once(cache, poll_ttl_s=60.0)
    v, _ = cache.get("live")
    assert v == 6  # tick incremented


def test_tick_does_not_publish_for_active_host_with_no_aux(cache):
    """An active host with no timestamps yields no patch → no version
    bump → no wire traffic."""
    cache.set("live", version=1, data={"active_room_id": "1"})
    _tick_once(cache, poll_ttl_s=60.0)
    v, _ = cache.get("live")
    assert v == 1


def test_tick_processes_multiple_hosts(cache):
    cache.set("a", version=1, data={
        "active_room_id": "1", "_last_gift_at": _iso_ago(10),
    })
    cache.set("b", version=1, data={
        "active_room_id": "2", "_last_gift_at": _iso_ago(20),
    })
    cache.set("c", version=1, data={  # idle
        "_last_gift_at": _iso_ago(30),
    })
    _tick_once(cache, poll_ttl_s=60.0)
    assert cache.get("a")[1]["last_gift_age_s"] == 10
    assert cache.get("b")[1]["last_gift_age_s"] == 20
    assert "last_gift_age_s" not in cache.get("c")[1]


# ── async loop (sanity) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_state_tick_loop_cancellable(cache):
    """The forever loop exits cleanly on cancellation."""
    cache.set("h", version=1, data={
        "active_room_id": "1", "_last_gift_at": _iso_ago(1),
    })
    task = asyncio.create_task(
        run_state_tick_loop(cache, interval_s=0.05, poll_ttl_s=60.0),
    )
    await asyncio.sleep(0.12)  # ~2 ticks
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # At least one tick fired → age field is set.
    _, data = cache.get("h")
    assert "last_gift_age_s" in data


@pytest.mark.asyncio
async def test_run_state_tick_loop_stop_event(cache):
    """`stop_event` is the graceful-shutdown signal — loop exits
    without raising CancelledError."""
    cache.set("h", version=1, data={
        "active_room_id": "1", "_last_gift_at": _iso_ago(1),
    })
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_state_tick_loop(
            cache, interval_s=10.0, poll_ttl_s=60.0, stop_event=stop,
        ),
    )
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    # Task returned cleanly (no exception); no assertion on cache
    # state because the interval is 10 s and we set the stop event
    # immediately. Tested behavior: no hang, no raise.
    assert task.done()
    assert not task.cancelled()

"""Per-session offset gap tracker.

TikTokLive's WebSocket protocol numbers each message with a monotonic
`offset` field on `ProtoMessageFetchResultBaseProtoMessage`. Within a
single continuous connection that number increments by 1 per message.
A jump (e.g., +1 → +5) means the client missed messages between, which
is the closest thing TikTok gives us to a "you lost N events" signal.

This module hooks into the live-client adapter:
  - On each batch arriving, observe every message's offset.
  - When `offset_n != offset_(n-1) + 1`, log a gap of size delta-1.
  - On ConnectEvent: reset state; that connection's counter starts fresh.
    The disconnect → reconnect window IS lost, but the lib doesn't expose
    a way to enumerate what's missing in that gap (TikTok server-side).
    We surface it as `disconnect_count` instead.

State is per-handle and in-process. Resets when the worker restarts.
For longer-term audit, persist counters somewhere durable.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class _SessionStats:
    last_offset: int | None = None
    last_offset_at: float = 0.0
    messages_observed: int = 0
    gaps_count: int = 0
    gaps_total_missed: int = 0
    last_gap_at: float | None = None
    last_gap_size: int | None = None
    disconnect_count: int = 0
    connect_count: int = 0
    connection_started_at: float = 0.0


class GapTracker:
    """Thread-safe in-memory gap statistics, keyed by handle.

    Single-process: the worker is the only ingester (flock-enforced),
    so no cross-process coordination is needed.
    """

    def __init__(self) -> None:
        # RLock (re-entrant) — `all_snapshots()` holds the lock and
        # then calls `snapshot()` for each session, which itself
        # acquires the same lock. With a non-reentrant Lock the second
        # acquire deadlocks the heartbeat thread (this was the cause
        # of "tick 1: building snapshot" hanging forever in the
        # asyncio loop). RLock allows the owning thread to re-enter.
        self._lock = threading.RLock()
        self._sessions: dict[str, _SessionStats] = {}

    # ── lifecycle hooks ──────────────────────────────────────────

    def on_connect(self, handle: str) -> None:
        """Called when ConnectEvent fires for a handle. Resets the
        offset cursor — a fresh connection has its own offset stream."""
        with self._lock:
            s = self._sessions.setdefault(handle, _SessionStats())
            s.last_offset = None
            s.last_offset_at = 0.0
            s.connect_count += 1
            s.connection_started_at = time.time()

    def on_disconnect(self, handle: str) -> None:
        with self._lock:
            s = self._sessions.setdefault(handle, _SessionStats())
            s.disconnect_count += 1

    # ── batch hook ───────────────────────────────────────────────

    def observe_batch(self, handle: str, messages: Iterable[Any]) -> None:
        """Record offsets for every message in a batch.

        `messages` is an iterable of `ProtoMessageFetchResultBaseProtoMessage`.
        We pull `getattr(m, "offset", None)` defensively — heartbeat
        messages and out-of-band frames may not carry one.
        """
        now = time.time()
        with self._lock:
            s = self._sessions.setdefault(handle, _SessionStats())
            for m in messages:
                off = getattr(m, "offset", None)
                if off is None or not isinstance(off, int):
                    continue
                # TikTok sometimes seeds offsets at 0. Skip zero-offset
                # messages (typically initial-state seeds, not part of
                # the live stream's monotonic flow).
                if off == 0:
                    continue
                if s.last_offset is None:
                    # First message of this connection — bootstrap.
                    s.last_offset = off
                    s.last_offset_at = now
                    s.messages_observed += 1
                    continue
                # Compare.
                delta = off - s.last_offset
                if delta == 1:
                    # Continuous — happy path.
                    pass
                elif delta > 1:
                    missed = delta - 1
                    s.gaps_count += 1
                    s.gaps_total_missed += missed
                    s.last_gap_at = now
                    s.last_gap_size = missed
                    logger.warning(
                        "TikTokLive offset gap for @%s: prev=%d new=%d (missed %d)",
                        handle, s.last_offset, off, missed,
                    )
                elif delta < 0:
                    # Out-of-order or rewound. Could be reconnect "rewind"
                    # without a fresh ConnectEvent. Don't count as a gap;
                    # just adopt the new offset.
                    pass
                # delta == 0: duplicate. Ignore.
                s.last_offset = off
                s.last_offset_at = now
                s.messages_observed += 1

    # ── snapshot ─────────────────────────────────────────────────

    def snapshot(self, handle: str) -> dict[str, Any]:
        with self._lock:
            s = self._sessions.get(handle)
            if s is None:
                return {
                    "messages_observed": 0,
                    "gaps_count": 0,
                    "gaps_total_missed": 0,
                    "last_gap_size": None,
                    "last_gap_age_s": None,
                    "disconnect_count": 0,
                    "connect_count": 0,
                    "connection_uptime_s": None,
                }
            now = time.time()
            return {
                "messages_observed": s.messages_observed,
                "gaps_count": s.gaps_count,
                "gaps_total_missed": s.gaps_total_missed,
                "last_gap_size": s.last_gap_size,
                "last_gap_age_s": (
                    now - s.last_gap_at if s.last_gap_at else None
                ),
                "disconnect_count": s.disconnect_count,
                "connect_count": s.connect_count,
                "connection_uptime_s": (
                    now - s.connection_started_at
                    if s.connection_started_at
                    else None
                ),
            }

    def all_snapshots(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {h: self.snapshot(h) for h in list(self._sessions.keys())}

    def remove(self, handle: str) -> None:
        with self._lock:
            self._sessions.pop(handle, None)


# Module-level singleton — the live-client adapter and the service
# both import this. Single instance per process.
gap_tracker = GapTracker()

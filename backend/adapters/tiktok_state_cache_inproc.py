"""In-process implementation of `TikTokStateCachePort`.

Used when the listener pool runs inside the same uvicorn process as
the API (`PHOVEU_BACKEND_TIKTOK_LISTENER_MODE=in_process` — the dev
default). State lives in a `dict` guarded by a `threading.Lock`;
deltas fan out to subscribers via per-channel `asyncio.Queue`s.

This adapter is fully self-contained — no Redis dependency, no
external process required. It works in tests and in the dev path
identically.

Persist path is sync (FastAPI runs handlers via `to_thread` against
this sync method, listener handlers run on the asyncio loop and call
this via `to_thread` too). Subscribers are async (WS routes).
Bridging sync publish → async subscriber uses
`loop.call_soon_threadsafe(queue.put_nowait, delta)`.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
from typing import Any, AsyncIterator, Callable, Optional

from ports.tiktok_state_cache import (
    CHANNEL_ADMIN,
    CHANNEL_PUBLIC,
    Channel,
    TikTokStateCachePort,
)

logger = logging.getLogger(__name__)

# Max queued messages per subscriber before we drop them. The Phase 9
# plan calls this out as the backpressure rule: a client that falls
# behind by more than this is dropped, reconnects, and resyncs via the
# snapshot path. 100 is generous — at 1 event/sec/host × 80 hosts that's
# >1 second of buffering before any subscriber is dropped.
_SUBSCRIBER_QUEUE_MAXSIZE = 100


class _Subscriber:
    """One active subscription. Carries the asyncio queue we feed and
    the event loop the queue lives on (needed for thread-safe puts
    when the publish call originates from a non-loop thread)."""

    __slots__ = ("queue", "loop", "channel", "dropped")

    def __init__(
        self,
        queue: asyncio.Queue[dict[str, Any]],
        loop: asyncio.AbstractEventLoop,
        channel: Channel,
    ) -> None:
        self.queue = queue
        self.loop = loop
        self.channel = channel
        # Once a subscriber overflows we stop feeding it. The async
        # iterator side observes the "dropped" sentinel and raises.
        self.dropped = False


class TikTokStateCacheInProc(TikTokStateCachePort):
    """In-process state cache. Thread-safe; works in both the API
    process and (when the listener runs in_process) the listener
    side. State is shared because there's only one process."""

    def __init__(
        self,
        *,
        public_sanitizer: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    ) -> None:
        # `_state` and `_versions` are guarded by `_lock`. `_subscribers`
        # is guarded by `_sub_lock` (separate lock to avoid holding the
        # state lock during fan-out — fan-out can call `put_nowait` for
        # N subscribers and we don't want to block apply_patch on slow
        # consumers more than we already do).
        self._state: dict[str, dict[str, Any]] = {}
        self._versions: dict[str, int] = {}
        self._lock = threading.Lock()
        self._subscribers: dict[Channel, list[_Subscriber]] = {
            CHANNEL_ADMIN: [],
            CHANNEL_PUBLIC: [],
        }
        self._sub_lock = threading.Lock()
        # Sanitizer applied to patches before publishing on the public
        # channel. None means "pass through" (used in tests).
        self._public_sanitizer = public_sanitizer

    # ── reads ────────────────────────────────────────────────────────

    def get(self, handle: str) -> tuple[int, dict[str, Any]] | None:
        with self._lock:
            data = self._state.get(handle)
            if data is None:
                return None
            # Deep-copy on the way out so callers can mutate freely
            # without poisoning the cache. The trade-off is a copy per
            # read; the alternative (returning the live dict) creates
            # subtle aliasing bugs that are nasty to debug.
            return self._versions[handle], copy.deepcopy(data)

    def list_versions(self) -> dict[str, int]:
        with self._lock:
            return dict(self._versions)

    # ── writes ───────────────────────────────────────────────────────

    def set(self, handle: str, version: int, data: dict[str, Any]) -> None:
        with self._lock:
            self._state[handle] = copy.deepcopy(data)
            self._versions[handle] = version

    def apply_patch(
        self,
        handle: str,
        patch: dict[str, Any],
    ) -> int | None:
        if not patch:
            return None

        # Apply under the lock for atomicity. Build the delta to
        # publish (with the new version) BEFORE releasing the lock so
        # subscribers see the same `{version, patch}` tuple every
        # apply_patch produces — even under concurrent calls.
        with self._lock:
            current = self._state.setdefault(handle, {})
            _deep_merge(current, patch)
            new_version = self._versions.get(handle, 0) + 1
            self._versions[handle] = new_version

        # Fan-out happens outside the state lock — see __init__.
        # Admin channel always gets the raw delta. Public channel may
        # get a sanitized + possibly empty patch, in which case we
        # skip the public publish (the version gap will trigger a
        # snapshot request on the public client, which is correct).
        admin_delta = {
            "host": handle,
            "version": new_version,
            "patch": patch,
        }
        self._publish(CHANNEL_ADMIN, admin_delta)

        public_patch = self._sanitize_for_public(patch)
        if public_patch:
            self._publish(
                CHANNEL_PUBLIC,
                {"host": handle, "version": new_version, "patch": public_patch},
            )

        return new_version

    def clear(self) -> None:
        with self._lock:
            self._state.clear()
            self._versions.clear()

    # ── subscribers ──────────────────────────────────────────────────

    async def subscribe(
        self,
        channel: Channel,
    ) -> AsyncIterator[dict[str, Any]]:
        if channel not in (CHANNEL_ADMIN, CHANNEL_PUBLIC):
            raise ValueError(f"unknown channel: {channel!r}")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAXSIZE,
        )
        sub = _Subscriber(queue=queue, loop=loop, channel=channel)
        with self._sub_lock:
            self._subscribers[channel].append(sub)

        try:
            while True:
                # `queue.get` blocks until a delta arrives. When the
                # subscriber is dropped (backpressure), the publish
                # side sets `sub.dropped` and we drain the queue then
                # raise — caller's WS layer catches and reconnects.
                item = await queue.get()
                if sub.dropped and queue.empty():
                    raise RuntimeError(
                        f"state-cache subscriber for channel={channel!r} "
                        "dropped due to backpressure; reconnect required"
                    )
                yield item
        finally:
            # Always clean up on iterator exit (close, exception, GC).
            with self._sub_lock:
                try:
                    self._subscribers[channel].remove(sub)
                except ValueError:
                    pass

    # ── internals ────────────────────────────────────────────────────

    def _publish(self, channel: Channel, delta: dict[str, Any]) -> None:
        """Push `delta` to every subscriber on `channel`. Non-blocking;
        drops slow subscribers rather than queue-blocking publishers."""
        with self._sub_lock:
            subs = list(self._subscribers[channel])
        for sub in subs:
            if sub.dropped:
                continue
            self._enqueue(sub, delta)

    def _enqueue(self, sub: _Subscriber, delta: dict[str, Any]) -> None:
        # Bridge sync→async: `put_nowait` is loop-bound. Schedule it
        # via `call_soon_threadsafe` so any thread can publish. If the
        # queue is already full, the subscriber is too slow — drop it.
        def _do_put() -> None:
            if sub.dropped:
                return
            try:
                sub.queue.put_nowait(delta)
            except asyncio.QueueFull:
                sub.dropped = True
                # Wake the consumer so it observes `dropped`. A sentinel
                # works because the queue is full → the consumer was
                # already going to wake up on its own anyway as soon
                # as a slot frees, but we don't want to wait.
                try:
                    # Best-effort wakeup. If this also fails, the
                    # consumer will eventually time out / disconnect.
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(delta)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
                logger.warning(
                    "state-cache subscriber dropped (channel=%s, queue full)",
                    sub.channel,
                )

        try:
            sub.loop.call_soon_threadsafe(_do_put)
        except RuntimeError:
            # Loop closed — subscriber is dead.
            sub.dropped = True

    def _sanitize_for_public(self, patch: dict[str, Any]) -> dict[str, Any]:
        if self._public_sanitizer is None:
            # No sanitizer wired (typical for tests). Pass through —
            # callers wiring this in production MUST provide a
            # sanitizer or risk leaking operator-only fields to public
            # subscribers.
            return patch
        return self._public_sanitizer(patch)


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Recursively merge `source` into `target`, mutating `target`.

    For dict values: recurse. For everything else (including lists):
    replace. Lists are NOT merged element-wise — a patch that sets
    `viewer_history` to a 30-element array replaces the prior array
    wholesale. This is correct for the Phase 9 event-mapping table
    where every list-valued field is recomputed on the listener side
    and shipped as a complete replacement."""
    for k, v in source.items():
        if (
            isinstance(v, dict)
            and isinstance(target.get(k), dict)
        ):
            _deep_merge(target[k], v)
        else:
            target[k] = v

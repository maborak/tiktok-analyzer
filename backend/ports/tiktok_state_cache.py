"""Port for the TikTok lives-list state cache.

Holds the per-host `{summary, version}` snapshot that powers the
`/admin/tiktok/lives/bundle` endpoint AND fan-outs deltas over WS to
connected clients. Two adapters implement this port:

- `adapters/tiktok_state_cache_inproc.py` — Python dict + Lock +
  in-process asyncio.Queue subscribers. Used when the listener and
  the API run in the same uvicorn process
  (`PHOVEU_BACKEND_TIKTOK_LISTENER_MODE=in_process`).
- `adapters/tiktok_state_cache_redis.py` — Redis HSET/INCR/PUBLISH.
  Used in worker-mode deployments where the listener is a separate
  process from the API workers.

Phase 9 (see `.claude/tracking/perf/PHASE9_PLAN.md`) wires this into
the persist path so every event mutates the cache + publishes a
delta. Phase A (this commit) defines the port and ships both
adapters with tests — no callers yet.

Consistency model: strong, per-host monotonic version. Every
`apply_patch` increments the host's version atomically and emits a
single `{host, version, patch}` delta to each subscribed channel.
Clients track a `versionByHost` map and request a snapshot when they
see a gap — see the Phase 9 plan for the full protocol.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Literal

# Channel names. Two channels: admin gets the raw delta, public gets
# the same delta after a sanitizer call (constructor-injected in the
# adapter). Sanitizing at publish time keeps the public subscriber
# trivial — it doesn't need to know which fields are operator-only.
CHANNEL_ADMIN: Literal["admin"] = "admin"
CHANNEL_PUBLIC: Literal["public"] = "public"
Channel = Literal["admin", "public"]


class TikTokStateCachePort(ABC):
    """Per-host summary state cache + delta pub-sub.

    The cache stores the latest known `summary` dict per host along
    with a monotonic `version` integer. The cache backing
    (`in-process dict + threading.Lock` vs Redis) is the adapter's
    concern; the port stays the same. The persist path calls
    `apply_patch` per event; the API service calls `get` /
    `set` on cache miss; the WS handler calls `subscribe`.
    """

    @abstractmethod
    def get(self, handle: str) -> tuple[int, dict[str, Any]] | None:
        """Returns `(version, summary_dict)` for `handle`, or `None`
        if no entry exists. Synchronous because the persist path and
        the service layer that calls it are both sync — async paths
        wrap this in `asyncio.to_thread`.
        """

    @abstractmethod
    def set(self, handle: str, version: int, data: dict[str, Any]) -> None:
        """Replace the full slice for `handle` with `(version, data)`.
        Used for cold backfill (after the SQL fan-out populates a
        previously-empty cache) and not for incremental updates.
        Race-with-apply_patch behavior is undefined; callers must
        ensure they don't overlap (e.g. backfill before listener
        starts publishing).
        """

    @abstractmethod
    def apply_patch(
        self,
        handle: str,
        patch: dict[str, Any],
    ) -> int | None:
        """Atomically deep-merge `patch` into the cached state for
        `handle`, increment the version, and publish a delta to both
        the admin and public channels.

        Empty `patch` is a no-op and returns `None` without
        bumping version or publishing.

        Returns the new version on a successful apply.

        Adapter contract: the deep-merge, version increment, and
        publish MUST be atomic w.r.t. concurrent `apply_patch` calls
        for the same handle. The Redis adapter uses a Lua script
        (single round-trip, server-side atomicity). The in-process
        adapter uses a `threading.Lock`.

        Publishing to the public channel goes through the adapter's
        constructor-injected sanitizer; an empty post-sanitize patch
        is dropped from the public channel only — the admin channel
        always sees the full delta. Public clients that see a
        resulting version gap fall back to the snapshot path.
        """

    @abstractmethod
    def list_versions(self) -> dict[str, int]:
        """Returns `{handle: current_version}` for every known host.
        Diagnostic / health-check use only — not hot-path.
        """

    @abstractmethod
    async def subscribe(self, channel: Channel) -> AsyncIterator[dict[str, Any]]:
        """Async iterator yielding `{host, version, patch}` dicts as
        deltas arrive on `channel` (`'admin'` or `'public'`).

        Consumer protocol: `async for delta in cache.subscribe('admin'):`.
        The iterator is meant to be tied to a single subscriber (one
        WS connection); closing the iterator unsubscribes.

        Implementations should drop the subscriber if its receive
        queue grows past a small bound (~100 messages) and signal
        via raising — the WS layer reconnects and requests a fresh
        snapshot for affected hosts. This is the backpressure rule
        from the Phase 9 plan.
        """

    @abstractmethod
    def clear(self) -> None:
        """Wipe all cached state and version counters. Used for
        tests + the admin "reset cache" path. Does NOT bump versions
        of any kind — clients holding versions higher than the
        post-clear state will trigger snapshot requests, which is
        the correct recovery."""

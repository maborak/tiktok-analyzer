"""TikTok-bot service: subscription CRUD + multi-live event pool.

Responsibilities:
  - Maintain the registry of @handles we monitor (subscriptions).
  - Spin up one TikTokLive listener session per enabled subscription.
  - On each event from any session: persist to DB AND broadcast to
    interested WebSocket subscribers.

The service depends only on ports (TikTokPersistencePort,
TikTokLiveSessionFactoryPort), never on adapters or the framework.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from domain.entities.tiktok_models import (
    Subscription,
    Room,
    SubscriptionState,
    TikTokGift,
    TikTokViewer,
    TikTokWorker,
)
from ports.tiktok_persistence import TikTokPersistencePort
from ports.tiktok_live import (
    TikTokLiveSessionFactoryPort,
    TikTokLiveSessionPort,
)

logger = logging.getLogger(__name__)


# Listener type for WS broadcasting.
EventListener = Callable[[dict[str, Any]], Awaitable[None]]


class ListenerLockUnavailableError(RuntimeError):
    """Legacy alias — file-flock days. The DB now coordinates via
    `WorkerKeyConflictError` (raised by `upsert_worker`); this class
    survives only so old import sites keep working. Treat any raise
    of this — whether the legacy name or the new one — as fatal at
    the CLI level."""


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _auto_bucket_seconds(range_seconds: int) -> int:
    """Pick a bucket size that keeps the chart at ~30–120 points for the
    given range. Round to "nice" numbers a viewer can read on the axis."""
    target_buckets = 60
    raw = max(1, range_seconds // target_buckets)
    # Snap to nearest sensible bucket boundary (in seconds).
    for snap in (15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400):
        if raw <= snap:
            return snap
    return 86400


def _settings_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract BattleSetting-derived fields from an event payload."""
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for k in ("duration_seconds", "start_time_ms", "end_time_ms", "extra_duration_seconds"):
        v = payload.get(k)
        if v:
            out[k] = v
    return out


def _serialize_opponent(o: dict[str, Any]) -> dict[str, Any]:
    """Coerce numeric ids to str so JS BigInt loss doesn't bite us."""
    if not isinstance(o, dict):
        return {}
    out = dict(o)
    if "user_id" in out and out["user_id"] is not None:
        out["user_id"] = str(out["user_id"])
    return out


def _favorite_notification_text(
    type: str,
    viewer: Any,
    payload: dict[str, Any] | None,
) -> tuple[str, str | None]:
    """Build the (title, body) tuple persisted into
    `tiktok_notifications` when a favourite gifter triggers an event.
    Title is the bell-drawer headline; body is the optional second
    line. Mirrors the frontend toast format minus the emoji prefix
    so the persisted text reads cleanly when rendered as a structured
    card."""
    p = payload or {}
    user_blob = p.get("user") if isinstance(p, dict) else None
    nickname = None
    unique_id = None
    if isinstance(user_blob, dict):
        nickname = user_blob.get("nickname") or None
        unique_id = user_blob.get("unique_id") or None
    display = (
        nickname
        or (viewer.nickname if getattr(viewer, "nickname", None) else None)
        or (viewer.unique_id if getattr(viewer, "unique_id", None) else None)
        or (unique_id)
        or f"User {getattr(viewer, 'user_id', '?')}"
    )
    if type == "gift":
        gift_name = p.get("gift_name") or "a gift"
        repeat = int(p.get("repeat_count") or 1)
        diamonds = int(p.get("diamond_count") or 0) * repeat
        title = (
            f"{display} sent {gift_name}"
            + (f" ×{repeat}" if repeat > 1 else "")
        )
        body = f"{diamonds:,} 💎"
        return title, body
    if type == "comment":
        text = (p.get("text") or "")
        text = text[:200] if isinstance(text, str) else ""
        return f"{display} commented", text or None
    if type == "join":
        return f"{display} joined", None
    return f"{display} · {type}", None


def _match_to_dict(m: Any, *, diamonds_total: int = 0) -> dict[str, Any]:
    """Serialize a Match dataclass for JSON. BigInt fields → str.

    Shape mirrors the route's MatchResponse so the frontend can use the
    same TikTokMatch type for both `room_stats.active_match` and the
    /matches list response.
    """
    return {
        "id": m.id,
        "room_id": str(m.room_id),
        "battle_id": str(m.battle_id),
        "opponents": [_serialize_opponent(o) for o in (m.opponents or [])],
        "scores": m.scores or {},
        "settings": getattr(m, "settings", None) or {},
        "winner_user_id": str(m.winner_user_id) if m.winner_user_id else None,
        "started_at": m.started_at.isoformat() if m.started_at else None,
        "ended_at": m.ended_at.isoformat() if m.ended_at else None,
        "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
        "diamonds_total": int(diamonds_total),
        # Active matches are by definition still ongoing; closed matches
        # are computed at /matches with team-aware result derivation.
        "result": "ongoing" if m.ended_at is None else "ended",
    }


class TikTokService:
    # How often to wake the periodic profile refresher.
    PROFILE_REFRESH_PERIOD_SECONDS = 15 * 60
    # Subscription-claim lease length. A worker that fails to extend
    # its lease within this window loses its claims to other workers.
    # Set generously so brief GC pauses or DB hiccups don't trigger
    # a re-claim. The reconcile loop extends every ~10s.
    LEASE_SECONDS = 60
    # Delay between consecutive _start_session calls at boot. Prevents
    # the simultaneous N-connect burst that trips TikTok's per-IP
    # anti-bot (DEVICE_BLOCKED). 500ms spreads 30 connects over ~15s.
    STARTUP_STAGGER_SECONDS = 0.5
    # A profile is considered stale this long after its last successful
    # fetch (default; applies when `is_live=True` or unknown).
    PROFILE_STALE_AFTER_SECONDS = 60 * 60
    # Stretched cadence for handles whose probe says they're NOT live.
    # Chronically-offline hosts get refreshed at 1/4 the rate — saves a
    # lot of Euler quota that was going to "is @offline_host still
    # offline?" probes that almost always answer "yes, still offline".
    # If the host comes back online, the live-status scraper picks it
    # up immediately on its own cadence (60s TTL) — this longer window
    # only governs the rich-profile refresh (followers / bio / etc).
    PROFILE_STALE_AFTER_SECONDS_OFFLINE = 60 * 60 * 4
    # How long between API calls when refreshing a batch — be a polite scraper.
    PROFILE_REFRESH_PER_HANDLE_DELAY_SECONDS = 1.0

    # Capacity-recycling for offline subscriptions. The reconcile loop
    # releases an owned sub when ALL of the following hold:
    #   • the central live-status probe last said `is_live=false`
    #     and that observation is fresher than `LIVE_STATUS_FRESHNESS_S`
    #     (so we trust it),
    #   • the supervisor's local state isn't CONNECTED (we'd contradict
    #     the probe — events are arriving despite is_live=false),
    #   • we've been observing offline for at least `OFFLINE_RELEASE_HYSTERESIS_S`
    #     consecutive seconds (absorbs network blips / rapid live-end-then-restart).
    # When all three line up, the supervisor is torn down and the
    # claim is dropped — capacity opens up for actually-live creators.
    OFFLINE_RELEASE_HYSTERESIS_S = 300.0   # 5 min
    LIVE_STATUS_FRESHNESS_S      = 180.0   # 3 min

    # Stuck-slot defenses (2026-05-14) — see `backend/docs/WORKER.md` §3.
    # The probe-based recycle above gates on `is_live ∈ {True, False, None}`
    # where `None` means "probe was inconclusive" (WAF, 403, missing SIGI).
    # Conservative-on-None protects against transient probe failures but
    # leaks slots when a host's live ENDED and the profile probe is
    # permanently stuck returning None (WAF on the profile URL,
    # banned/deleted account, age-restriction).
    #
    # Two additional release conditions, both gated on long thresholds
    # so they fire only on genuinely stuck slots:
    #
    #   Stage 1 — local-signal release:
    #     The listener's WebSocket disconnect callback knows for CERTAIN
    #     when the live ended (TikTok closed our WS, or the lib bailed
    #     after retry exhaustion). If local state has been DISCONNECTED
    #     / LIVE_ENDED / ERROR continuously for `LOCAL_OFFLINE_RELEASE_S`,
    #     force-release regardless of probe.
    #
    #   Stage 2 — probe-None patience cap:
    #     If the central probe has returned `None` continuously for
    #     `PROBE_UNKNOWN_RELEASE_S`, treat as effectively False. The
    #     "1 sec of 403s → cascade" the original probe code feared
    #     doesn't fit a 30-minute window.
    #
    # Both thresholds are intentionally generous; neither triggers on
    # transient flaps.
    LOCAL_OFFLINE_RELEASE_S   = 600.0    # 10 min — local WS signal
    PROBE_UNKNOWN_RELEASE_S   = 1800.0   # 30 min — probe-None patience

    # Postgres advisory-lock key. Cross-process mutex: only one listener
    # pool may hold this at a time. Constant chosen to never collide with
    # any framework-managed advisory locks (the framework's range is small
    # int IDs; this is a custom 64-bit value with the high bit clear).
    LISTENER_ADVISORY_LOCK_KEY = 0x71_4B_57_43_4D_53_4D_56  # ASCII "qKWCMSMV"

    def __init__(
        self,
        persistence: TikTokPersistencePort,
        session_factory: TikTokLiveSessionFactoryPort,
        *,
        passive: bool = False,
    ) -> None:
        self._persistence = persistence
        self._session_factory = session_factory
        self._sessions: dict[str, TikTokLiveSessionPort] = {}
        self._states: dict[str, str] = {}
        self._listeners: set[EventListener] = set()
        self._lock = asyncio.Lock()
        # Active match per room: room_id → {match_id, battle_id}.
        # Lets us tag every persisted event with the current battle.
        self._active_match: dict[int, dict[str, int]] = {}
        # Passive mode: subscription CRUD writes to DB but does NOT manage
        # TikTokLive sessions locally. Used by the API process when the
        # listener pool runs in a separate worker — the worker reconciles
        # session lifecycle from DB state on its own poll cadence.
        self._passive = passive
        # Captured asyncio loop. Set by `_on_event` (which always runs
        # on the loop thread) so background-task spawns from executor
        # threads can dispatch back via `run_coroutine_threadsafe`.
        self._loop: asyncio.AbstractEventLoop | None = None
        # Periodic profile refresher task handle.
        self._profile_refresher_task: asyncio.Task[None] | None = None
        # Centralized live-status scraper. Replaces N parallel
        # `_wait_until_live` polls — one task per worker that walks the
        # claimed handles round-robin and updates the DB cache.
        self._live_scraper_task: asyncio.Task[None] | None = None
        # Cross-process listener mutex. We use a filesystem `flock` on a
        # well-known path so this works regardless of DB topology — Postgres
        # advisory locks are unreliable behind pgbouncer in transaction or
        # statement pool modes (the lock gets released the moment pgbouncer
        # rebinds the backend connection to another client). flock is held
        # by the kernel against this process's file descriptor and released
        # automatically on process exit.
        # Stop request flipped by `check_db_orders` when the admin sets
        # desired_status='stopped' or command='kill' on this worker's
        # row. The CLI's outer loop watches `stop_requested` and exits.
        self._stop_requested: bool = False
        # Dedicated thread pools so the asyncio loop's control-plane
        # tasks (heartbeat, audit log) can NEVER be starved by event
        # persistence under load. The default ThreadPoolExecutor is
        # shared globally; under 100+ events/sec it saturates and
        # heartbeat run_in_executor calls queue indefinitely behind
        # event persists. Splitting the work into separate pools
        # means each has a private, predictable thread budget.
        import concurrent.futures
        # Single thread = serialized heartbeat + worker-log writes.
        # Each is a single UPDATE/INSERT, sub-second; no point in
        # parallelism here, and serialization prevents lock contention
        # against the worker's own row.
        self._control_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="tiktok-ctrl"
        )
        # Bounded event-persist pool. Each persist is one transaction
        # (room upsert + viewer upsert + event insert). 4 threads is
        # enough to saturate the DB on a single host without piling
        # up sleeping retry threads. If event rate exceeds throughput,
        # the asyncio submit queue grows — bounded by event arrival,
        # not runaway.
        self._event_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="tiktok-evt"
        )
        # Multi-worker registry identity. `worker_key` is the stable
        # logical identity used by the DB registry — defaults to
        # hostname, overridable via PHOVEU_BACKEND_TIKTOK_WORKER_NAME
        # so multiple workers per host get distinct rows.
        import socket
        host = socket.gethostname()
        self._worker_host: str = host
        self._worker_key: str = (
            os.getenv("PHOVEU_BACKEND_TIKTOK_WORKER_NAME") or host
        )
        try:
            self._worker_capacity: int = int(
                os.getenv("PHOVEU_BACKEND_TIKTOK_WORKER_CAPACITY") or "30"
            )
        except (TypeError, ValueError):
            self._worker_capacity = 30
        self._worker_id: int | None = None
        # Tracked background tasks (fire-and-forget jobs whose exceptions
        # should still be logged + GC pinned). Keyed by id() to allow
        # multiple tasks for the same logical operation.
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        # Per-handle event counters + last-event timestamp. Used by the
        # listener status endpoint so the admin UI can show "events_total"
        # and "last event 4s ago" per handle without a DB query.
        self._handle_event_count: dict[str, int] = {}
        self._handle_last_event_at: dict[str, float] = {}
        # Per-handle running count of WS events dropped by the dedup
        # unique index (`(room_id, message_id)`). Surfaced in the
        # listener-status snapshot so we can track the WS cursor-replay
        # rate over time. Resets only when the worker restarts.
        self._handle_dedup_dropped: dict[str, int] = {}
        # Most recent terminal connect-time error per handle. Keyed by
        # unique_id; cleared on a successful (re)start. Surfaced via the
        # listener-status snapshot so the UI can show "age-restricted
        # stream" instead of a bare "ERROR" state.
        self._handle_last_error: dict[str, dict[str, Any]] = {}
        # Highest worker_log row id we've already processed for a
        # `reconnect_requested` signal — see `request_reconnect`. The
        # reconcile loop scans for rows with id > this and tears down +
        # restarts the matching local supervisor (waking it from any
        # parked backoff sleep).
        self._reconnect_processed_id: int = 0
        # Per-handle marker for "we first observed is_live=false at
        # this UTC time". Cleared the moment we see is_live=true. Drives
        # the offline-release hysteresis below: only after this marker
        # is older than OFFLINE_RELEASE_HYSTERESIS_S do we tear down
        # the supervisor and free the slot.
        self._offline_observed_at: dict[str, datetime] = {}
        # Stuck-slot defense state (2026-05-14, see WORKER.md §3.4):
        #   `_local_offline_since`: time.time() of the most recent
        #     transition INTO DISCONNECTED/LIVE_ENDED/ERROR. Cleared
        #     when state returns to CONNECTED. Drives Stage-1 release.
        #   `_probe_unknown_since`: time.time() of the most recent
        #     contiguous-None probe run. Cleared when probe returns a
        #     definite True/False. Drives Stage-2 release.
        self._local_offline_since: dict[str, float] = {}
        self._probe_unknown_since: dict[str, float] = {}
        # Process-wide pause flag. When set, supervisor refuses to start
        # new sessions and `start_all_enabled()` is a no-op. Triggered by
        # the SIGUSR1 control signal from the API.
        self._paused: bool = False
        # Process boot time (used by status snapshot for uptime).
        self._started_at: float = time.time()
        # Last time we bumped last_seen_at for a (kind, id). Used to debounce
        # housekeeping writes — a popular creator at 80 evt/sec generates
        # 80 row updates/sec just from last_seen_at otherwise.
        self._last_seen_pushed: dict[str, float] = {}
        # Push interval for last_seen_at — see _should_push_seen.
        self._LAST_SEEN_THROTTLE_SECONDS = 30.0

    # ── lifecycle ────────────────────────────────────────────────────

    def _build_oneoff_client(self):
        """A throwaway TikTokLiveClient just for HTTP API calls (gift
        catalog, unique-id lookup) — no WebSocket. Applies sign globals
        first so the request goes through whichever provider the admin
        configured."""
        from TikTokLive import TikTokLiveClient
        # Apply sign provider globals (Euler / session / local) before
        # the client is constructed — `tiktok_sign_api_key` is read once
        # at construction time and a later set has no effect.
        try:
            from adapters.tiktok_live_client import _apply_sign_globals
            _apply_sign_globals()
        except Exception:
            logger.debug("apply_sign_globals failed for one-off client", exc_info=True)
        return TikTokLiveClient(unique_id="@tiktok")

    async def bootstrap_gift_catalog(self) -> int:
        """Fetch TikTok's full gift list once and upsert into
        `tiktok_gifts`. Only runs when the catalog is empty — gift
        events themselves keep individual rows fresh as they fly past.

        Returns the number of catalog rows written.
        """
        existing = self._persistence.list_gifts(limit=1)
        if existing:
            return 0
        try:
            client = self._build_oneoff_client()
            try:
                # Returns the raw `data` payload from /webcast/gift/list/.
                # Gift records live under "gifts" — a list of dicts.
                data = await client.web.fetch_gift_list()
            finally:
                try:
                    await client.web.close()
                except Exception:
                    pass
        except Exception:
            logger.exception("fetch_gift_list bootstrap failed; skipping catalog refresh.")
            return 0

        gifts: list[dict[str, Any]] = []
        if isinstance(data, dict):
            raw = data.get("gifts") or []
            if isinstance(raw, list):
                gifts = [g for g in raw if isinstance(g, dict)]

        count = 0
        for g in gifts:
            try:
                gid = int(g.get("id"))
            except (TypeError, ValueError):
                continue
            icon_url = None
            for key in ("image", "icon", "image_thumb"):
                img = g.get(key)
                if isinstance(img, dict):
                    urls = img.get("url_list") or []
                    if urls:
                        icon_url = urls[0]
                        break
            try:
                self._persistence.upsert_gift(
                    TikTokGift(
                        gift_id=gid,
                        name=g.get("name"),
                        diamond_count=_safe_int(g.get("diamond_count")),
                        icon_url=icon_url,
                        streakable=g.get("type") == 1 if "type" in g else None,
                    )
                )
                count += 1
            except Exception:
                logger.exception("Gift catalog row upsert failed for gift_id=%s", gid)
        if count:
            logger.info("Gift catalog bootstrapped: %d entries.", count)
        return count

    async def lookup_unique_id_by_user_id(self, user_id: int) -> str | None:
        """Reverse lookup: TikTok user_id → @handle via TikTokLive's
        `fetch_user_unique_id` route. Used to resolve PK opponents when
        we have the numeric id but not the handle."""
        try:
            client = self._build_oneoff_client()
            try:
                handle = await client.web.fetch_user_unique_id(user_id=int(user_id))
                return str(handle).lstrip("@") if handle else None
            finally:
                try:
                    await client.web.close()
                except Exception:
                    pass
        except Exception:
            logger.exception("lookup_unique_id_by_user_id failed for %s", user_id)
            return None

    async def start_all_enabled(self) -> None:
        """Worker bootstrap: register in tiktok_workers, reap any stale
        siblings, then claim a slice of enabled subscriptions up to
        `worker_capacity` and start sessions for them.

        Multi-worker safe: each worker takes a disjoint set via
        SELECT FOR UPDATE SKIP LOCKED. The reconcile loop subsequently
        keeps the lease alive and grabs more if capacity opens up.
        """
        if self._passive:
            return  # worker process handles startup

        if self._paused:
            logger.info("TikTok listener pool is paused; skipping session startup.")
            return

        # 1. Reap stale siblings that died without releasing claims.
        # Run this BEFORE our own register so an "old me" row with
        # heartbeat <30s ago doesn't block us — the reaper marks rows
        # stale based on heartbeat, not status.
        try:
            reaped = self._persistence.reap_stale_workers(stale_after_seconds=30)
            if reaped:
                logger.info("Reaped %d stale worker registration(s).", reaped)
        except Exception:
            logger.exception("reap_stale_workers failed; continuing.")

        # 2. Register this worker in the DB registry. This is now the
        # ONLY mutex — no more flock. `upsert_worker` raises
        # `WorkerKeyConflictError` if another live worker holds the
        # same worker_key (heartbeat <30s old). The CLI converts that
        # raise to a clean non-zero exit so the supervisor crashloops
        # until the conflict is gone.
        worker = self._persistence.upsert_worker(
            TikTokWorker(
                id=None,
                worker_key=self._worker_key,
                host=self._worker_host,
                pid=os.getpid(),
                capacity=self._worker_capacity,
            )
        )
        self._worker_id = worker.id
        # Seed the reconnect-signal cursor to whatever's already in the
        # worker_log so a fresh worker boot doesn't replay every
        # historical `reconnect_requested` row from before we started.
        try:
            recent = self._persistence.list_worker_log(
                event_prefix="reconnect_requested", limit=1,
            )
            if recent:
                self._reconnect_processed_id = int(recent[0].id or 0)
        except Exception:
            logger.exception(
                "failed to seed reconnect_processed_id; "
                "worker may briefly replay stale reconnect signals",
            )
        # Capture the sign-provider config in effect for THIS worker
        # boot. Surfaces it in both the console log and the
        # tiktok_worker_log audit row so we can confirm which Euler
        # key (or local broker / session cookie) the worker is using
        # without grepping config.
        try:
            from adapters.tiktok_live_client import _read_sign_settings
            sign_cfg = _read_sign_settings()
        except Exception:
            sign_cfg = {}
        provider = sign_cfg.get("TIKTOK_SIGN_PROVIDER") or "euler"
        api_key = sign_cfg.get("TIKTOK_EULER_API_KEY") or ""
        # Fingerprint: show enough to match against .env without
        # dumping the full credential to disk on every restart.
        if api_key:
            if len(api_key) > 16:
                key_fp = f"{api_key[:8]}…{api_key[-6:]} (len={len(api_key)})"
            else:
                key_fp = f"len={len(api_key)}"
        else:
            key_fp = "(none)"
        logger.info(
            "Worker registered: id=%s key=%s host=%s pid=%d capacity=%d "
            "sign_provider=%s euler_api_key=%s",
            worker.id, self._worker_key, self._worker_host, os.getpid(),
            self._worker_capacity, provider, key_fp,
        )
        self._log_worker(
            "startup",
            detail={
                "worker_key": self._worker_key,
                "host": self._worker_host,
                "pid": os.getpid(),
                "capacity": self._worker_capacity,
                "sign_provider": provider,
                "euler_api_key_fp": key_fp,
            },
        )

        # 3. Bootstrap gift catalog (one-shot; multiple workers checking
        # the empty-table guard ⇒ exactly one populates it).
        try:
            await self.bootstrap_gift_catalog()
        except Exception:
            logger.exception("Gift catalog bootstrap failed; continuing startup.")

        # 4. Use the periodic reconcile pass for the actual claim+start
        # work. It covers three cases in one place:
        #   • previously-claimed handles whose lease survived our restart
        #     (`claim_subscriptions` skips these because they're not
        #     "free" — they're already assigned to us — so we'd never
        #     resume them otherwise; that was the silent stuck-handle
        #     bug where a worker would heartbeat fine but ingest 0
        #     events because no session was actually running),
        #   • disabled/deleted subs whose lease is still ours,
        #   • new claims up to remaining capacity.
        # Stagger inside `_start_session` callers; reconcile honours the
        # same STARTUP_STAGGER_SECONDS for both resume and new-claim paths.
        result = await self.reconcile_assignments()
        logger.info(
            "Boot reconcile: resumed=%d claimed=%d held=%d",
            result.get("resumed_count", 0),
            len(result.get("claimed", [])),
            result.get("held", 0),
        )

        # 5. Periodic profile refresher (existing behavior).
        if self._profile_refresher_task is None or self._profile_refresher_task.done():
            self._profile_refresher_task = asyncio.create_task(
                self._profile_refresher_loop()
            )
        # 6. Centralized live-status scraper. ONE network call every
        # ~5s instead of N parallel pollers from N supervisors.
        if self._live_scraper_task is None or self._live_scraper_task.done():
            self._live_scraper_task = asyncio.create_task(
                self._live_scraper_loop()
            )

    async def stop_all(self) -> None:
        """Called at app shutdown."""
        if self._profile_refresher_task and not self._profile_refresher_task.done():
            self._profile_refresher_task.cancel()
            try:
                await self._profile_refresher_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Profile refresher cancel raised.")
            self._profile_refresher_task = None
        if self._live_scraper_task and not self._live_scraper_task.done():
            self._live_scraper_task.cancel()
            try:
                await self._live_scraper_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Live scraper cancel raised.")
            self._live_scraper_task = None
        async with self._lock:
            handles = list(self._sessions.keys())
        # Parallel teardown — each session.stop() awaits a websocket
        # disconnect that can take ~1s, so 18 serial stops blew past
        # the supervisor's 10s SIGKILL fallback. Cap the gather with
        # asyncio.wait_for so a single stuck session doesn't hold up
        # the rest. Each stop has its own try/except so one failure
        # doesn't propagate.
        async def _safe_stop(h: str) -> None:
            try:
                await self._stop_session(h)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Error stopping subscription @%s", h)

        if handles:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(_safe_stop(h) for h in handles),
                        return_exceptions=True,
                    ),
                    timeout=8.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "stop_all: %d session(s) didn't stop in 8s; abandoning.",
                    len(handles),
                )
        # Release the registry row + every claim we held so siblings
        # pick up our handles immediately rather than waiting for the
        # 30s stale-reaper threshold.
        if self._worker_id is not None:
            try:
                self._persistence.mark_worker_stopped(self._worker_id)
            except Exception:
                logger.exception("mark_worker_stopped failed for id=%s", self._worker_id)
            self._worker_id = None
        # Wind down the private executors. wait=False so we don't
        # block the asyncio loop on pending event persists; pending
        # tasks will be abandoned but the row is already marked
        # stopped + assignments released, so no work is lost.
        try:
            self._control_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self._event_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    # ── multi-worker reconcile / heartbeat ──────────────────────────

    async def reconcile_assignments(self) -> dict[str, Any]:
        """One reconcile pass: extend leases on currently-held handles,
        notice DB changes (deletions, disables, claim losses), claim
        more handles up to capacity. Idempotent.

        Returns a small dict with what changed for telemetry.
        """
        if self._passive or self._worker_id is None:
            return {"skipped": True}

        # 1. Extend leases on what we already hold; the return value is
        #    the set of handles the DB still believes we own. If a
        #    handle is missing here but is in our local _sessions, it
        #    was reaped (e.g., we missed a heartbeat) — tear down so we
        #    don't dual-ingest with whoever re-claimed it.
        try:
            still_mine = set(
                self._persistence.extend_my_leases(
                    self._worker_id, lease_seconds=self.LEASE_SECONDS
                )
            )
        except Exception:
            logger.exception("extend_my_leases failed")
            still_mine = set(self._sessions.keys())

        local_handles = set(self._sessions.keys())
        lost = local_handles - still_mine
        for handle in lost:
            logger.warning(
                "Lost claim on @%s (lease expired or reaped) — stopping session.",
                handle,
            )
            try:
                await self._stop_session(handle)
            except Exception:
                logger.exception("Stop after lost claim failed for @%s", handle)

        # 2. Stop sessions for subscriptions that have been disabled or
        #    deleted in the DB (reconcile against the truth source).
        #    Iterate `still_mine` (DB truth) rather than just `_sessions`
        #    so disabled handles whose lease is held but session isn't
        #    running locally also get their assignment released.
        all_subs = {s.unique_id: s for s in self._persistence.list_subscriptions()}
        for handle in list(still_mine):
            sub = all_subs.get(handle)
            if sub is None or not sub.enabled:
                logger.info(
                    "Subscription @%s disabled/deleted — stopping + releasing.",
                    handle,
                )
                try:
                    await self._stop_session(handle)
                except Exception:
                    logger.exception("Stop after disable failed for @%s", handle)
                try:
                    self._persistence.release_my_assignment(self._worker_id, handle)
                except Exception:
                    logger.exception("release_my_assignment failed for @%s", handle)
                # Reflect the release in our local view so the resume-
                # missing pass below doesn't re-start it.
                still_mine.discard(handle)

        # 2.5. Capacity recycling: release owned subs whose creator has
        #     been confirmed offline long enough that they shouldn't be
        #     holding a slot. Without this we fill capacity with
        #     supervisors sitting in cheap-poll mode for offline
        #     creators, locking out actually-live ones from being
        #     claimed. Releasing the assignment lets `claim_subscriptions`
        #     (whose ORDER BY now prefers is_live=true) backfill the
        #     slot with a creator who's actually broadcasting.
        now_utc = datetime.now(timezone.utc)
        now_ts = time.time()
        released_offline: list[str] = []
        for handle in list(still_mine):
            sub = all_subs.get(handle)
            if sub is None:
                continue
            is_live = sub.is_live  # tri-state: True / False / None
            checked_at = sub.live_checked_at

            # Stage-1 stuck-slot defense — local-signal release. If the
            # listener's own state has been offline-equivalent
            # continuously for `LOCAL_OFFLINE_RELEASE_S`, the WS is
            # provably dead from our side. Release REGARDLESS of probe
            # state (handles the case where the probe is permanently
            # stuck on None for this host — WAF, banned account,
            # age-restricted). See `WORKER.md` §3.4.
            local_offline_since = self._local_offline_since.get(handle)
            if (
                local_offline_since is not None
                and (now_ts - local_offline_since) >= self.LOCAL_OFFLINE_RELEASE_S
                and self._states.get(handle) != SubscriptionState.CONNECTED.value
            ):
                logger.info(
                    "Capacity recycle (stage-1, local-signal): @%s "
                    "DISCONNECTED for %.0fs — releasing slot.",
                    handle, now_ts - local_offline_since,
                )
                await self._release_slot(handle, still_mine, released_offline)
                continue

            # Stage-2 stuck-slot defense — probe-None patience cap. If
            # the central probe has returned None continuously for
            # `PROBE_UNKNOWN_RELEASE_S`, treat as effectively offline.
            # Only fires when we're ALSO not locally CONNECTED — if
            # events are flowing, the probe's confusion doesn't matter.
            probe_unknown_since = self._probe_unknown_since.get(handle)
            if (
                probe_unknown_since is not None
                and (now_ts - probe_unknown_since) >= self.PROBE_UNKNOWN_RELEASE_S
                and self._states.get(handle) != SubscriptionState.CONNECTED.value
            ):
                logger.info(
                    "Capacity recycle (stage-2, probe-None): @%s probe "
                    "unknown for %.0fs — treating as offline, releasing slot.",
                    handle, now_ts - probe_unknown_since,
                )
                await self._release_slot(handle, still_mine, released_offline)
                continue

            if is_live is True:
                # Definitely live — clear any prior offline marker so
                # a future flap doesn't trip the hysteresis prematurely.
                self._offline_observed_at.pop(handle, None)
                continue
            if is_live is None or checked_at is None:
                # Unknown / never probed — don't release via the
                # probe-based path; let the next tick decide once the
                # probe runs. (Stage-2 above handles the permanently-
                # stuck case.)
                continue
            # Trust is_live=false only if the probe ran recently. A
            # stale "false" might be hours old (worker-pause incident,
            # scraper outage); we don't want to evict a live creator
            # because of stale cache.
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=timezone.utc)
            check_age_s = (now_utc - checked_at).total_seconds()
            if check_age_s > self.LIVE_STATUS_FRESHNESS_S:
                continue
            # The supervisor's in-process state can contradict the
            # probe: if we're CONNECTED, events are flowing right now
            # — don't release no matter what the cache says.
            local_state = self._states.get(handle)
            if local_state == SubscriptionState.CONNECTED.value:
                # Reset the offline marker — we're clearly live.
                self._offline_observed_at.pop(handle, None)
                continue
            # Start (or extend) the offline observation window. Use the
            # probe's timestamp so a worker that just booted sees the
            # right "we've been offline for X" — without this a fresh
            # worker would think every existing-offline sub had been
            # offline for 0 seconds and never release them.
            first_offline = self._offline_observed_at.get(handle)
            if first_offline is None:
                first_offline = checked_at
                self._offline_observed_at[handle] = first_offline
            offline_for_s = (now_utc - first_offline).total_seconds()
            if offline_for_s < self.OFFLINE_RELEASE_HYSTERESIS_S:
                continue
            # All three conditions met: release.
            logger.info(
                "Capacity recycle: @%s offline for %.0fs (probe age %.0fs, "
                "local state %s) — releasing slot.",
                handle, offline_for_s, check_age_s, local_state,
            )
            await self._release_slot(handle, still_mine, released_offline)

        # 2b. Resume sessions we still own but aren't running locally.
        #     This covers the worker-restart case: leases were extended
        #     for us across the restart (so other workers wouldn't steal
        #     them), but `_sessions` is empty after a process restart, so
        #     without this branch every previously-claimed handle would
        #     be silently dormant — lease forever fresh, listener never
        #     re-attached. Stagger to avoid a 30+ session reconnect storm
        #     against TikTok at boot.
        to_resume = sorted(still_mine - set(self._sessions.keys()))
        for handle in to_resume:
            logger.info(
                "Resuming session for @%s (still our lease, no local listener).",
                handle,
            )
            try:
                await self._start_session(handle)
            except Exception:
                logger.exception("Resume session failed for @%s", handle)
            await asyncio.sleep(self.STARTUP_STAGGER_SECONDS)

        # 3. Claim more if we have capacity.
        free_slots = max(0, self._worker_capacity - len(self._sessions))
        claimed: list[str] = []
        if free_slots > 0:
            try:
                claimed = self._persistence.claim_subscriptions(
                    self._worker_id,
                    max_to_claim=free_slots,
                    lease_seconds=self.LEASE_SECONDS,
                )
            except Exception:
                logger.exception("claim_subscriptions failed")
                claimed = []
            for handle in claimed:
                try:
                    await self._start_session(handle)
                except Exception:
                    logger.exception("Failed to start newly-claimed @%s", handle)
                await asyncio.sleep(self.STARTUP_STAGGER_SECONDS)

        # 4. Drain `reconnect_requested` signals. The API writes a row to
        #    tiktok_worker_log when an admin clicks "Reconnect now"; the
        #    worker that owns that handle observes the new row here and
        #    restarts its supervisor — this is what wakes a session
        #    that's parked on a 30-min slow-retry backoff sleep.
        try:
            log_rows = self._persistence.list_worker_log(
                event_prefix="reconnect_requested", limit=50,
            )
        except Exception:
            logger.exception("list_worker_log(reconnect_requested) failed")
            log_rows = []
        # `list_worker_log` is desc-sorted by id; the highest id is the
        # newest signal. Process in ascending order so multiple back-to-
        # back requests are honoured.
        bounced: list[str] = []
        max_seen_id = self._reconnect_processed_id
        for row in sorted(log_rows, key=lambda r: r.id or 0):
            row_id = int(row.id or 0)
            if row_id <= self._reconnect_processed_id:
                continue
            max_seen_id = max(max_seen_id, row_id)
            handle = (row.handle or "").lstrip("@")
            if not handle or handle not in still_mine:
                # Some other worker owns this handle (or it's been
                # released) — leave the signal for them.
                continue
            sub = all_subs.get(handle)
            if sub is None or not sub.enabled:
                continue
            logger.info("Honouring reconnect_requested for @%s", handle)
            try:
                await self._stop_session(handle)
                await self._start_session(handle)
                bounced.append(handle)
            except Exception:
                logger.exception("Reconnect-bounce failed for @%s", handle)
        if max_seen_id > self._reconnect_processed_id:
            self._reconnect_processed_id = max_seen_id

        return {
            "lost": sorted(lost),
            "released_offline": sorted(released_offline),
            "resumed": to_resume,
            "resumed_count": len(to_resume),
            "claimed": claimed,
            "bounced": bounced,
            "held": len(self._sessions),
        }

    async def _release_slot(
        self,
        handle: str,
        still_mine: set[str],
        released_offline: list[str],
    ) -> None:
        """Tear down a session + drop its DB assignment + clear all
        tracking state for this handle. Used by the three recycle
        paths in `reconcile_assignments`:

          (1) Stage-1 local-signal release (WS confirmed offline)
          (2) Stage-2 probe-None patience release (probe stuck)
          (3) Probe-confirmed-false release (the original path)

        Idempotent — safe to call multiple times for the same handle.
        Failures in either teardown step are logged but don't raise;
        the reconcile loop must finish even when one host is stuck.
        """
        try:
            await self._stop_session(handle)
        except Exception:
            logger.exception("stop_session during recycle failed for @%s", handle)
        try:
            self._persistence.release_my_assignment(self._worker_id, handle)
        except Exception:
            logger.exception("release_my_assignment failed for @%s", handle)
        # Clear all tracking dicts so a future re-claim of this handle
        # starts with a clean slate (no stale stuck-slot timers ticking).
        self._offline_observed_at.pop(handle, None)
        self._local_offline_since.pop(handle, None)
        self._probe_unknown_since.pop(handle, None)
        still_mine.discard(handle)
        released_offline.append(handle)

    def write_heartbeat_to_db(self, snap: dict[str, Any] | None = None) -> None:
        """Push a listener snapshot into tiktok_workers. Called from the
        DB-heartbeat asyncio task every 5s.

        IMPORTANT: pass `snap` precomputed on the asyncio loop. Building
        it here from a thread executor races with the loop's mutations
        of `self._states` / `self._sessions` — `sorted()` raises
        `dictionary changed size during iteration` mid-iteration, which
        intermittently kills the heartbeat tick. Caller responsibility:
        run `service.get_listener_status_local()` from the asyncio
        loop, hand the result here.
        """
        if self._worker_id is None:
            return
        if snap is None:
            # Backward-compat fallback. Best-effort only.
            try:
                snap = self.get_listener_status_local()
            except Exception:
                logger.exception("get_listener_status_local failed inside heartbeat")
                return
        try:
            self._persistence.heartbeat_worker(
                self._worker_id,
                sessions_count=int(snap.get("active_session_count") or 0),
                status="paused" if snap.get("paused") else "running",
                metadata=snap,
            )
        except Exception:
            logger.exception("heartbeat_worker UPDATE failed")

    # ── pause / resume control ──────────────────────────────────────

    async def pause_all(self) -> dict[str, Any]:
        """Stop every active session but keep the process alive. Sets the
        paused flag so reconcile loops + start_all_enabled won't re-spawn
        sessions until `resume_all()` clears it.

        Returns a small status dict so the caller can confirm what was
        actually stopped (handle count, etc.).
        """
        if self._passive:
            return {"ok": False, "detail": "service is passive (worker has control)"}
        self._paused = True
        async with self._lock:
            handles = list(self._sessions.keys())
        for h in handles:
            try:
                await self._stop_session(h)
            except Exception:
                logger.exception("pause_all: failed to stop @%s", h)
        logger.info("Listener pool paused (%d session(s) stopped).", len(handles))
        return {"ok": True, "stopped": handles, "paused": True}

    async def resume_all(self) -> dict[str, Any]:
        """Clear the paused flag and re-subscribe every enabled handle."""
        if self._passive:
            return {"ok": False, "detail": "service is passive (worker has control)"}
        was_paused = self._paused
        self._paused = False
        if not was_paused:
            return {"ok": True, "detail": "not paused — no-op", "paused": False}
        # Re-claim a slice + start sessions. No flock — the DB registry
        # is the only coordinator now.
        if self._worker_id is not None:
            claimed = self._persistence.claim_subscriptions(
                self._worker_id,
                max_to_claim=self._worker_capacity,
                lease_seconds=self.LEASE_SECONDS,
            )
        else:
            claimed = []
        for handle in claimed:
            try:
                await self._start_session(handle)
            except Exception:
                logger.exception("resume_all: failed to start @%s", handle)
            await asyncio.sleep(self.STARTUP_STAGGER_SECONDS)
        logger.info("Listener pool resumed (%d session(s) started).", len(claimed))
        self._log_worker("resume", detail={"started": claimed})
        return {"ok": True, "started": claimed, "paused": False}

    def get_listener_status_local(self) -> dict[str, Any]:
        """Snapshot of THIS process's view of the listener pool. Used by
        the heartbeat writer (worker) and as a fallback by the API status
        endpoint when the worker is in-process.

        Does NOT consult the heartbeat file or Redis — that's the caller's
        job. This is purely "what does this Python process know right now".
        """
        now = time.time()
        # Pull gap-tracker counters once for all sessions.
        try:
            from adapters.tiktok_offset_tracker import gap_tracker
            gap_snapshots = gap_tracker.all_snapshots()
        except Exception:
            gap_snapshots = {}
        # Defensive copies — supervisor tasks mutate _states and
        # _sessions concurrently. Iterating the live dict raises
        # `RuntimeError: dictionary changed size during iteration`
        # when a state transition lands mid-iteration. `dict(d)` is a
        # GIL-atomic shallow copy, never raises.
        states_snapshot = dict(self._states)
        sessions_snapshot = dict(self._sessions)
        last_event_snapshot = dict(self._handle_last_event_at)
        event_count_snapshot = dict(self._handle_event_count)
        last_error_snapshot = dict(self._handle_last_error)
        dedup_dropped_snapshot = dict(self._handle_dedup_dropped)
        sessions = []
        # Snapshot the offline-observed marker dict so the per-row
        # countdown ("Disconnect in Xs") is computed from a stable
        # view — supervisor tasks mutate this dict on every reconcile.
        offline_observed_snapshot = dict(self._offline_observed_at)
        now_dt = datetime.now(timezone.utc)
        for handle, state in sorted(states_snapshot.items()):
            last_at = last_event_snapshot.get(handle)
            sess = sessions_snapshot.get(handle)
            rid = sess.room_id if sess else None
            gaps = gap_snapshots.get(handle, {})
            err = last_error_snapshot.get(handle)
            # Time-to-release for the offline-recycle hysteresis. None
            # when the session isn't being watched for release (live,
            # connected, or unknown); a positive int otherwise.
            offline_at = offline_observed_snapshot.get(handle)
            recycle_release_in_s: float | None = None
            if offline_at is not None:
                if offline_at.tzinfo is None:
                    offline_at = offline_at.replace(tzinfo=timezone.utc)
                elapsed = (now_dt - offline_at).total_seconds()
                remaining = self.OFFLINE_RELEASE_HYSTERESIS_S - elapsed
                recycle_release_in_s = max(0.0, remaining)
            sessions.append({
                "handle": handle,
                "state": state,
                "room_id": str(rid) if rid else None,
                "is_connected": bool(sess and sess.is_connected),
                "recycle_release_in_s": recycle_release_in_s,
                "events_total": int(event_count_snapshot.get(handle, 0)),
                # Running count of WS events dropped by the dedup unique
                # index. Most are TikTok cursor-replay at reconnect
                # boundaries; a sudden growth would indicate a worker
                # double-ingest bug (two listeners on one handle).
                "dedup_dropped": int(dedup_dropped_snapshot.get(handle, 0)),
                # Last terminal connect-time error (e.g. AgeRestrictedError,
                # UserNotFoundError). Cleared when a successful restart
                # happens. UI shows this as the reason instead of bare ERROR.
                "last_error_kind": err.get("kind") if err else None,
                "last_error_message": err.get("message") if err else None,
                "last_error_at": (
                    datetime.fromtimestamp(err["at"], timezone.utc).isoformat()
                    if err and err.get("at") else None
                ),
                "last_event_at": (
                    datetime.fromtimestamp(last_at, timezone.utc).isoformat()
                    if last_at else None
                ),
                "last_event_age_s": (now - last_at) if last_at else None,
                # Loss-detection metrics derived from TikTokLive's per-message
                # `offset` field. `gaps_count` is "how many times we saw a
                # discontinuity within a single connection" — gaps_total_missed
                # is the sum of (delta-1) across them. disconnect_count is the
                # other loss boundary; events between disconnect + reconnect
                # are silently lost without an offset gap signal.
                "messages_observed": int(gaps.get("messages_observed", 0)),
                "gaps_count": int(gaps.get("gaps_count", 0)),
                "gaps_total_missed": int(gaps.get("gaps_total_missed", 0)),
                "last_gap_size": gaps.get("last_gap_size"),
                "last_gap_age_s": gaps.get("last_gap_age_s"),
                "disconnect_count": int(gaps.get("disconnect_count", 0)),
                "connect_count": int(gaps.get("connect_count", 0)),
                "connection_uptime_s": gaps.get("connection_uptime_s"),
            })
        return {
            "pid": os.getpid(),
            "started_at": datetime.fromtimestamp(self._started_at, timezone.utc).isoformat(),
            "uptime_s": now - self._started_at,
            "passive": self._passive,
            "paused": self._paused,
            "stop_requested": self._stop_requested,
            "active_session_count": len(self._sessions),
            # Subset of `active_session_count` that's actually receiving
            # events right now (state == CONNECTED). Lets the worker
            # dashboard show "12 live / 30 slots" instead of just "29/30",
            # which made it look stuck even when capacity was healthy.
            "connected_session_count": sum(
                1 for st in states_snapshot.values()
                if st == SubscriptionState.CONNECTED.value
            ),
            "sessions": sessions,
        }

    # ── subscription CRUD ───────────────────────────────────────────

    async def lookup_handle(self, handle: str) -> dict[str, Any]:
        """Probe a TikTok handle and return a preview for the "Add Live"
        confirmation modal. Tries TikTok directly first; falls back to our
        viewers cache when TikTok is unreachable / age-gated.
        """
        handle = handle.lstrip("@").strip()
        full = f"@{handle}" if handle else "@"

        out: dict[str, Any] = {
            "handle": handle,
            "exists": None,
            "is_live": None,  # tri-state: True / False / None (unknown)
            "nickname": None,
            "user_id": None,
            "avatar_url": None,
            "bio": None,
            "follower_count": None,
            "following_count": None,
            "room_id": None,
            "title": None,
            "viewer_count": None,
            "source": None,
            "error": None,
            "warning": None,
            "already_subscribed": False,
        }

        if not handle:
            out["error"] = "Empty handle"
            return out

        # Already in our subscription list? Surface so the modal can warn.
        existing = self._persistence.get_subscription(handle)
        if existing is not None:
            out["already_subscribed"] = True

        # Lazy import so we don't spin up TikTokLive deps in test contexts
        # that don't need them.
        from TikTokLive import TikTokLiveClient
        from TikTokLive.client.errors import (
            AgeRestrictedError,
            UserNotFoundError,
            UserOfflineError,
        )

        # Step 1: PUBLIC PROFILE SCRAPE — cheap, comprehensive, no auth.
        # The TikTok profile page (`tiktok.com/@<handle>`) ships rich JSON
        # in a `__UNIVERSAL_DATA_FOR_REHYDRATION__` script tag: nickname,
        # avatar, bio, follower/following/video/like counts, verification,
        # and a `roomId` field that's set exactly when the user is live.
        # This is far more reliable than the webcast API which gates most
        # accounts behind a session cookie.
        from adapters.tiktok_profile_scraper import fetch_public_profile
        profile = await fetch_public_profile(handle)
        if profile.get("exists") is True:
            out["exists"] = True
            out["is_live"] = bool(profile.get("is_live"))
            out["source"] = "profile"
            out["nickname"] = profile.get("nickname")
            out["user_id"] = profile.get("user_id")
            out["avatar_url"] = profile.get("avatar_url")
            out["bio"] = profile.get("bio")
            out["follower_count"] = profile.get("follower_count")
            out["following_count"] = profile.get("following_count")
            if profile.get("is_live"):
                out["room_id"] = profile.get("room_id")
        elif profile.get("exists") is False:
            out["exists"] = False
            out["is_live"] = False
            out["error"] = "User not found on TikTok."
            return out
        else:
            # Profile fetch failed (captcha / network). Try the webcast API
            # as fallback below; otherwise the modal sees `unknown`.
            if profile.get("error"):
                out["warning"] = f"Profile probe degraded: {profile['error']}"

        # Step 2: WEBCAST API ENRICHMENT — only useful when the user IS live,
        # adds room title + viewer count. Often refused without a session,
        # so failures are non-fatal.
        from TikTokLive import TikTokLiveClient
        from TikTokLive.client.errors import (
            AgeRestrictedError,
            UserNotFoundError,
            UserOfflineError,
        )

        if out["is_live"]:
            client = TikTokLiveClient(unique_id=full)
            try:
                info = await client.web.fetch_room_info(unique_id=full)
                data = info.get("data", info) if isinstance(info, dict) else {}
                if isinstance(data, dict):
                    out["title"] = data.get("title") or out["title"]
                    out["viewer_count"] = (
                        data.get("user_count") or data.get("total_user")
                    )
            except (AgeRestrictedError, UserOfflineError, UserNotFoundError):
                # Profile scrape already gave us the truth; webcast just adds bonus fields.
                pass
            except Exception as e:
                logger.info("Webcast enrichment failed for @%s: %r", handle, e)
            finally:
                try:
                    await client.web.close()
                except Exception:
                    pass

        # Fallback to our viewers cache for nickname / avatar when TikTok
        # didn't give us any.
        if (not out["nickname"]) or (not out["avatar_url"]):
            cached = self._persistence.get_viewer_by_unique_id(handle)
            if cached is not None:
                if not out["nickname"] and cached.nickname:
                    out["nickname"] = cached.nickname
                if not out["avatar_url"] and cached.avatar_url:
                    out["avatar_url"] = cached.avatar_url
                if not out["user_id"] and cached.user_id:
                    out["user_id"] = str(cached.user_id)
                if out["exists"] is None:
                    out["exists"] = True
                    out["source"] = out["source"] or "cache"

        return out

    async def list_subscriptions(self) -> list[dict[str, Any]]:
        """Returns list of {unique_id, enabled, state, room_id, ...}.
        room_id is stringified (BigInt > JS Number.MAX_SAFE_INTEGER).
        Includes cached profile fields (avatar, nickname, follower_count,
        etc.) so the Lives table can show real identity at a glance.

        Worker mode: this service is passive — runtime state lives in
        the worker process. We pull it from the heartbeat snapshot so
        the table reflects what the worker sees, not "DISABLED".
        """
        # Pull every live worker's session view in passive mode. The
        # file-based heartbeat used to be the source of truth here;
        # now the DB registry's `metadata` column carries the same
        # snapshot, and supports multi-worker (each worker contributes
        # its own slice of handles).
        worker_sessions: dict[str, dict[str, Any]] = {}
        if self._passive:
            try:
                workers = self._persistence.list_workers()
                now_ts = time.time()
                for w in workers:
                    # Skip stale rows — their metadata is meaningless.
                    if w.last_heartbeat_at is None:
                        continue
                    age = now_ts - w.last_heartbeat_at.timestamp()
                    if age > 30 or w.status not in ("running", "paused"):
                        continue
                    meta = w.metadata or {}
                    for s in meta.get("sessions") or []:
                        handle = s.get("handle")
                        if handle:
                            worker_sessions[handle] = s
            except Exception:
                logger.debug(
                    "list_subscriptions: worker registry read failed",
                    exc_info=True,
                )

        out: list[dict[str, Any]] = []
        for sub in self._persistence.list_subscriptions():
            sess = self._sessions.get(sub.unique_id)
            rid = sess.room_id if sess else None
            ws = worker_sessions.get(sub.unique_id)

            # State precedence: in-process state → worker heartbeat →
            # derive from `enabled` (DISABLED if off, DISCONNECTED if on).
            state = self._states.get(sub.unique_id)
            if state is None and ws is not None:
                state = ws.get("state")
            if state is None:
                state = (
                    SubscriptionState.DISABLED.value
                    if not sub.enabled
                    else SubscriptionState.DISCONNECTED.value
                )

            # room_id similarly: prefer in-process session, then worker.
            room_id = str(rid) if rid else (ws.get("room_id") if ws else None)
            is_connected = bool(sess and sess.is_connected)
            if not is_connected and ws is not None:
                is_connected = bool(ws.get("is_connected"))

            out.append(
                {
                    "unique_id": sub.unique_id,
                    "enabled": sub.enabled,
                    "is_public": bool(getattr(sub, "is_public", False)),
                    "state": state,
                    "room_id": room_id,
                    "is_connected": is_connected,
                    "created_at": sub.created_at.isoformat() if sub.created_at else None,
                    "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
                    # Profile cache.
                    "profile_user_id": str(sub.profile_user_id) if sub.profile_user_id else None,
                    "nickname": sub.nickname,
                    "avatar_url": sub.avatar_url,
                    "bio": sub.bio,
                    "verified": sub.verified,
                    "follower_count": sub.follower_count,
                    "following_count": sub.following_count,
                    "profile_refreshed_at": (
                        sub.profile_refreshed_at.isoformat()
                        if sub.profile_refreshed_at else None
                    ),
                    "profile_error": sub.profile_error,
                    "is_live": sub.is_live,
                    "live_checked_at": (
                        sub.live_checked_at.isoformat()
                        if sub.live_checked_at else None
                    ),
                    "current_room_id": (
                        str(sub.current_room_id) if sub.current_room_id else None
                    ),
                }
            )
        return out

    # ── DB-driven worker control + audit log ─────────────────────────

    def _log_worker(
        self,
        event: str,
        *,
        level: str = "info",
        handle: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Append a tiktok_worker_log row tagged with this worker's id.

        Submits the INSERT to the dedicated control executor as a
        fire-and-forget task. Callers DON'T await it — they're often
        on the asyncio loop's hot path (e.g., session lifecycle), and
        a synchronous DB INSERT under load could pile up and block
        the loop. The control executor's single thread serializes the
        writes; if it falls behind, we tolerate slight log latency
        rather than starving the loop.
        """
        # Every audit row is persisted to `tiktok_worker_log` (the source
        # of truth). The console mirror at INFO produced ~1 line per
        # session lifecycle event — pure duplicate noise. Keep WARNING+
        # at the original level so real issues still surface; downgrade
        # the routine INFO-level lifecycle events (session_start,
        # session_stop, etc.) to DEBUG.
        py_level = level if level in ("info", "warning", "error", "debug") else "info"
        if py_level == "info":
            py_level = "debug"
        getattr(logger, py_level)(
            "[worker_log] event=%s handle=%s detail=%s",
            event, handle or "-", detail or {},
        )
        if self._worker_id is None:
            return
        worker_id = self._worker_id
        persistence = self._persistence

        def _do_log() -> None:
            try:
                persistence.append_worker_log(
                    worker_id,
                    event=event,
                    level=level,
                    handle=handle,
                    detail=detail,
                )
            except Exception:
                logger.debug(
                    "append_worker_log failed for event=%s", event, exc_info=True,
                )

        try:
            self._control_executor.submit(_do_log)
        except RuntimeError:
            # Executor already shut down (during graceful exit). Drop.
            pass

    async def check_db_orders(self) -> dict[str, Any]:
        """Read this worker's row, act on `desired_status` + `command`.

        Called from the reconcile loop on every tick. Idempotent.

        Effects:
          - desired_status='paused'  → pause_all + remember.
          - desired_status='running' (and we're paused) → resume_all.
          - desired_status='stopped' → mark a flag the CLI loop watches
            so the worker exits cleanly.
          - command 'release_handle:<unique_id>' → release that one
            handle (stop session + clear assignment columns).
          - command 'kill' → desired_status='stopped' shortcut.
        """
        if self._passive or self._worker_id is None:
            return {"skipped": True}
        try:
            me = self._persistence.get_worker(self._worker_id)
        except Exception:
            logger.exception("check_db_orders: get_worker failed")
            return {"skipped": True, "error": "get_worker"}
        if me is None:
            return {"skipped": True, "error": "missing_row"}

        actions: list[str] = []

        # --- desired_status reconciliation ---
        if me.desired_status == "paused" and not self._paused:
            await self.pause_all()
            self._log_worker("command_pause_applied")
            actions.append("paused")
        elif me.desired_status == "running" and self._paused:
            await self.resume_all()
            self._log_worker("command_resume_applied")
            actions.append("resumed")
        elif me.desired_status == "stopped":
            self._stop_requested = True
            self._log_worker("command_stop_requested")
            actions.append("stop_requested")

        # --- one-shot commands ---
        cmd = (me.command or "").strip()
        if cmd:
            self._log_worker("command_received", detail={"command": cmd})
            try:
                if cmd == "kill":
                    self._stop_requested = True
                    actions.append("kill")
                elif cmd.startswith("release_handle:"):
                    target = cmd.split(":", 1)[1].strip().lstrip("@")
                    if target and target in self._sessions:
                        await self._stop_session(target)
                    if target:
                        try:
                            self._persistence.release_my_assignment(
                                self._worker_id, target,
                            )
                        except Exception:
                            logger.exception(
                                "release_my_assignment failed for @%s", target,
                            )
                        actions.append(f"released:{target}")
                else:
                    self._log_worker(
                        "command_unknown", level="warn",
                        detail={"command": cmd},
                    )
            finally:
                try:
                    self._persistence.ack_worker_command(self._worker_id)
                except Exception:
                    logger.exception("ack_worker_command failed")
        return {"actions": actions, "desired_status": me.desired_status}

    @property
    def stop_requested(self) -> bool:
        """Exposed for the CLI's main loop. When the admin sets
        `desired_status='stopped'` (or sends command='kill'), the
        worker observes it via `check_db_orders` and flips this flag.
        The CLI's outer loop checks every tick and exits cleanly."""
        return self._stop_requested

    def _spawn_bg(self, coro, *, name: str) -> asyncio.Task[Any] | None:
        """Track fire-and-forget tasks: pin the reference (so the GC won't
        drop them), log any exception, and discard from the registry on
        completion. Returns None when there's no running event loop.

        When called from a non-loop thread (e.g. the event-persist
        executor scheduling an opponent-profile fetch from inside
        `_handle_match_event`), dispatch via `run_coroutine_threadsafe`
        on the loop captured by `_on_event`. Without this branch
        `asyncio.create_task` raises RuntimeError, the coroutine is
        never awaited, and we get a `coroutine ... was never awaited`
        warning every time a battle starts."""
        try:
            task = asyncio.create_task(coro, name=name)
        except RuntimeError:
            loop = self._loop
            if loop is not None and loop.is_running():
                # Schedule on the captured loop. The returned
                # concurrent.futures.Future isn't tracked the same way
                # as an asyncio.Task — fire-and-forget is fine; failures
                # surface via the coroutine's own logging.
                asyncio.run_coroutine_threadsafe(coro, loop)
                return None
            # No loop available — close the orphaned coroutine to
            # suppress the unawaited-coroutine warning.
            try:
                coro.close()
            except Exception:
                pass
            return None
        self._bg_tasks.add(task)

        def _on_done(t: asyncio.Task[Any]) -> None:
            self._bg_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("Background task %s raised: %r", t.get_name(), exc, exc_info=exc)

        task.add_done_callback(_on_done)
        return task

    async def create_subscription(self, unique_id: str, *, enabled: bool = True) -> Subscription:
        unique_id = self._normalize(unique_id)
        sub = self._persistence.upsert_subscription(unique_id, enabled=enabled)
        # Fire-and-forget profile refresh so the Lives table shows
        # avatar/nickname immediately. Tracked so a crash actually surfaces.
        self._spawn_bg(
            self.refresh_profile(unique_id),
            name=f"refresh_profile:{unique_id}",
        )
        if sub.enabled:
            await self._start_session(sub.unique_id)
        return sub

    async def set_enabled(self, unique_id: str, enabled: bool) -> Optional[Subscription]:
        unique_id = self._normalize(unique_id)
        sub = self._persistence.set_subscription_enabled(unique_id, enabled)
        if sub is None:
            return None
        if enabled:
            await self._start_session(unique_id)
        else:
            await self._stop_session(unique_id)
        return sub

    async def delete_subscription(self, unique_id: str) -> bool:
        unique_id = self._normalize(unique_id)
        await self._stop_session(unique_id)
        return self._persistence.delete_subscription(unique_id)

    def set_subscription_public(self, unique_id: str, is_public: bool) -> dict[str, Any]:
        """Flip the public flag for `unique_id`. Returns the updated
        subscription as a dict (same shape one element of
        `list_subscriptions()` produces) or raises LookupError if the
        handle isn't tracked — the route translates that into a 404.

        Pass-through to persistence; no listener side-effects. Public-
        opt-in is purely a display setting, the listener pool doesn't
        care.
        """
        unique_id = self._normalize(unique_id)
        ok = self._persistence.set_subscription_public(unique_id, bool(is_public))
        if not ok:
            raise LookupError(unique_id)
        sub = self._persistence.get_subscription(unique_id)
        if sub is None:
            # Was deleted between the update and the readback — treat
            # like not-found.
            raise LookupError(unique_id)
        # Invalidate the public-lives summary cache so a freshly
        # disabled handle stops appearing immediately. Without this,
        # `/public/tiktok/lives` keeps serving the stale list for up
        # to the cache TTL (30s), which feels wrong on a privacy
        # action: operator clicks "off", expects "private NOW".
        # Drop the read-side response cache; the next public hit
        # rebuilds from `list_public_subscriptions()`.
        self._public_lives_summary_cache = None
        # Same reason for the public WS handle filter: when an
        # operator flips a host private, the public WS must stop
        # forwarding that host's events on the next received event,
        # not 30s later. Drop the cache; next event re-reads the set.
        self._public_handle_set_cache = None
        return {
            "unique_id": sub.unique_id,
            "is_public": bool(sub.is_public),
            "enabled":   bool(sub.enabled),
        }

    async def request_reconnect(self, unique_id: str) -> bool:
        """Force the listener for `unique_id` to teardown + start fresh,
        bypassing whatever backoff sleep its supervisor is parked on.

        In API (in-process listener) mode this is synchronous: stop +
        start the local session, which cancels the supervisor's
        `asyncio.sleep(backoff)` and starts a new connect attempt.

        In worker mode (passive=True) the API can't directly touch the
        worker's tasks — instead we drop a `reconnect_requested` row in
        `tiktok_worker_log`. The worker's reconcile loop scans for
        unprocessed requests on each cycle and handles teardown+start
        for the handles it owns. This is the same DB-only coordination
        pattern the rest of the worker control surface uses.

        Always also flips `is_live=False` and clears `current_room_id`
        so the UI's stale-LIVE pill drops immediately, even before the
        next live-status probe runs.
        """
        unique_id = self._normalize(unique_id)
        sub = self._persistence.get_subscription(unique_id)
        if sub is None:
            return False
        # Drop the cached live-status so the UI doesn't keep claiming
        # LIVE while the listener is bouncing. The probe will re-fill
        # this in the next cycle (or sooner — the new supervisor
        # triggers an `is_live` check on connect attempt).
        try:
            self._persistence.update_live_status(
                unique_id, is_live=False, room_id=None,
            )
        except Exception:
            logger.exception(
                "failed to clear is_live cache during reconnect for @%s",
                unique_id,
            )
        if self._passive:
            # Signal-via-worker_log: the worker reconcile loop drains
            # rows where event='reconnect_requested' and acts on them.
            self._log_worker("reconnect_requested", handle=unique_id)
            return True
        # In-process: tear down + restart immediately.
        await self._stop_session(unique_id)
        if sub.enabled:
            await self._start_session(unique_id)
        return True

    # ── WS listener registration ─────────────────────────────────────

    def add_listener(self, listener: EventListener) -> None:
        self._listeners.add(listener)

    def remove_listener(self, listener: EventListener) -> None:
        self._listeners.discard(listener)

    # ── reads (used by routes/stats) ────────────────────────────────

    def list_events(
        self,
        room_id: int,
        *,
        type: str | None = None,
        limit: int = 200,
        before_id: int | None = None,
    ):
        return self._persistence.list_events(
            room_id, type=type, limit=limit, before_id=before_id
        )

    def get_room(self, room_id: int):
        return self._persistence.get_room(room_id)

    def host_calendar(
        self,
        host_unique_id: str,
        *,
        weeks: int = 26,
        tz: str = "UTC",
    ) -> dict[str, Any]:
        """Returns daily broadcast counts for the heatmap on the live-
        detail page. Window ends today (UTC) and reaches `weeks` weeks
        back, snapped to the start of the calendar week (Monday) so the
        grid is rectangular. Day-bucketing happens in `tz`."""
        now = datetime.now(timezone.utc)
        # Snap end to end-of-day, start to weeks*7 days back at start-of-day,
        # then floor start to the previous Monday so the heatmap grid is
        # 7-row × N-column rectangular.
        end = now.replace(hour=23, minute=59, second=59, microsecond=999_999)
        start = (now - timedelta(days=weeks * 7)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        offset_to_monday = start.weekday()  # Monday=0
        if offset_to_monday > 0:
            start = start - timedelta(days=offset_to_monday)
        cells = self._persistence.host_calendar(
            host_unique_id, since=start, until=end, tz=tz,
        )
        return {
            "host": host_unique_id,
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "weeks": weeks,
            "tz": tz,
            "cells": cells,
        }

    def room_totals(
        self,
        room_ids: list[int],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[int, dict[str, int]]:
        """Pass-through to persistence — exposed on the service so the
        route doesn't reach into a private attribute. Used by the
        broadcast dropdown + day-picker modal to label each room with
        its diamonds / matches / likes; `since` + `until` clip those
        totals to a calendar-day window so a broadcast that crossed
        midnight only contributes the slice that landed on the picked
        day."""
        return self._persistence.room_totals(
            room_ids, since=since, until=until,
        )

    def list_rooms_for_host(self, host_unique_id: str, *, limit: int = 50):
        return self._persistence.list_rooms_for_host(host_unique_id, limit=limit)

    # Endpoint → kind mapping. Kept identical to the classification in
    # `adapters.tiktok_euler_call_sink._classify_url` so old rows and
    # new rows bucket the same way. Updates here must update there.
    @staticmethod
    def _kind_for_endpoint(endpoint: str) -> str:
        """Map a log row's endpoint label to a higher-level kind. Drives
        the per-chart split in the API History dashboard.

        Returns one of:
          'room-info'    — `webcast/room/info` + `webcast/room/info_by_user`.
                           These are the discovery probes (handle → room_id);
                           biggest quota burners in practice, so we surface
                           them as their own chart instead of letting them
                           swallow the rest of the stack.
          'webcast'      — other Euler-signed `webcast/*` calls (fetch,
                           check_alive, enter, …). Still Euler-billing.
          'tiktok-direct'— anonymous `www.tiktok.com/@…` HTML scrapes.
                           No quota cost.
          'other'        — fallback (eulerstream sign-API direct hits
                           with a non-`webcast/` path, etc.).
        """
        if endpoint.startswith("tiktok/"):
            return "tiktok-direct"
        if endpoint.startswith("webcast/room/info"):
            return "room-info"
        if endpoint.startswith("webcast/"):
            return "webcast"
        return "other"

    def get_euler_call_history(
        self,
        *,
        hours: int = 24,
        bucket_minutes: int = 15,
    ) -> dict[str, Any]:
        """Histogram of TikTok-bound HTTP calls captured in
        `tiktok_euler_call_log`, sliced two ways:

          * Euler-billing calls (`euler-sign` + `webcast`) — every one
            of these consumes 1 sign quota slot.
          * Direct calls (`tiktok-direct`) — anonymous HTML scrapes
            that don't consume Euler quota but DO hit TikTok's
            public-site WAF, so they're a separate troubleshooting
            channel.

        Returned shape:

            {
              "since": iso, "until": iso,
              "bucket_minutes": N,
              "bins":      [iso, ...]                # ascending
              "api_keys":  ["euler_OG…UxNjkx (len=78)", ...]

              # Euler-billing chart payload
              "euler": {
                "endpoints": [...],
                "series":    [{endpoint, api_key_fp, counts: int[N]}, ...]
                "totals":    {by_endpoint, by_key, all}
              },
              # Direct-scrape chart payload (no Euler quota cost)
              "direct": {
                "endpoints": [...],
                "series":    [{endpoint, api_key_fp, counts: int[N]}, ...]
                "totals":    {by_endpoint, by_key, all}
              },
              # Cross-cut: outcome breakdown (status_code class) per
              # bin — useful to spot 429-rate-limit storms next to the
              # endpoint chart.
              "outcomes": {
                "labels":   ["2xx", "3xx", "4xx", "5xx", "err"],
                "counts":   {"euler": int[N×5], "direct": int[N×5]}
              }
            }

        Postgres-only.
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text as _text

        until = datetime.now(timezone.utc).replace(microsecond=0)
        since = until - timedelta(hours=hours)
        with self._persistence._get_session() as s:
            rows = s.execute(_text("""
              SELECT
                date_trunc('minute', ts)
                  - MOD(EXTRACT(MINUTE FROM ts)::int, :bm) * INTERVAL '1 minute'
                  AS bin,
                endpoint,
                api_key_fp,
                status_code,
                COUNT(*) AS n
              FROM tiktok_euler_call_log
              WHERE ts >= :since AND ts < :until
              GROUP BY 1, 2, 3, 4
              ORDER BY 1
            """), {
                "bm": bucket_minutes, "since": since, "until": until,
            }).all()

        # Bin grid.
        first_bin = since.replace(
            minute=since.minute - (since.minute % bucket_minutes),
            second=0, microsecond=0,
        )
        bins: list[datetime] = []
        cur = first_bin
        step = timedelta(minutes=bucket_minutes)
        while cur < until:
            bins.append(cur)
            cur += step
        bin_index: dict[datetime, int] = {b: i for i, b in enumerate(bins)}
        N = len(bins)

        # Split rows into Euler-billing vs Direct based on endpoint kind.
        # Each bucket independently tracks per-(endpoint,key) series +
        # rolling totals.
        def _empty_bucket() -> dict[str, Any]:
            return {
                "cells": {},
                "endpoints": set(),
                "by_endpoint": {},
                "by_key": {},
                "total": 0,
            }
        # Three named buckets keyed by kind. `room-info` was peeled off
        # `webcast` because in practice it's by far the highest-volume
        # quota burner and was visually dominating the chart.
        buckets = {
            "room-info":   _empty_bucket(),
            "webcast":     _empty_bucket(),
            "tiktok-direct": _empty_bucket(),
        }

        # 5-class outcome counts per bin per bucket.
        OUTCOME_LABELS = ["2xx", "3xx", "4xx", "5xx", "err"]
        outcomes_by_kind: dict[str, list[list[int]]] = {
            k: [[0] * 5 for _ in range(N)] for k in buckets
        }
        api_keys: set[str] = set()

        def _outcome_idx(sc: int | None) -> int:
            if sc is None:
                return 4
            if 200 <= sc < 300:
                return 0
            if 300 <= sc < 400:
                return 1
            if 400 <= sc < 500:
                return 2
            if 500 <= sc < 600:
                return 3
            return 4

        for r in rows:
            kind = self._kind_for_endpoint(r.endpoint)
            # Anything that doesn't match a named bucket (the 'other'
            # bucket) falls through onto the catch-all 'webcast' bucket
            # so it still shows up rather than silently disappearing.
            bucket = buckets.get(kind) or buckets["webcast"]
            outcome_bin = outcomes_by_kind.get(kind) or outcomes_by_kind["webcast"]
            n = int(r.n or 0)
            api_keys.add(r.api_key_fp)
            bucket["endpoints"].add(r.endpoint)
            bucket["by_endpoint"][r.endpoint] = (
                bucket["by_endpoint"].get(r.endpoint, 0) + n
            )
            bucket["by_key"][r.api_key_fp] = (
                bucket["by_key"].get(r.api_key_fp, 0) + n
            )
            bucket["total"] += n
            key = (r.endpoint, r.api_key_fp)
            arr = bucket["cells"].setdefault(key, [0] * N)
            idx = bin_index.get(r.bin)
            if idx is not None:
                arr[idx] += n
                outcome_bin[idx][_outcome_idx(r.status_code)] += n

        def _serialize(bucket: dict[str, Any]) -> dict[str, Any]:
            return {
                "endpoints": sorted(bucket["endpoints"]),
                "series": [
                    {"endpoint": ep, "api_key_fp": fp, "counts": bucket["cells"][(ep, fp)]}
                    for (ep, fp) in sorted(bucket["cells"].keys())
                ],
                "totals": {
                    "by_endpoint": bucket["by_endpoint"],
                    "by_key": bucket["by_key"],
                    "all": bucket["total"],
                },
            }

        return {
            "since": since.isoformat(),
            "until": until.isoformat(),
            "bucket_minutes": bucket_minutes,
            "bins": [b.isoformat() for b in bins],
            "api_keys": sorted(api_keys),
            "room_info": _serialize(buckets["room-info"]),
            "euler":     _serialize(buckets["webcast"]),
            "direct":    _serialize(buckets["tiktok-direct"]),
            "outcomes": {
                "labels": OUTCOME_LABELS,
                "counts": {
                    "room_info": outcomes_by_kind["room-info"],
                    "euler":     outcomes_by_kind["webcast"],
                    "direct":    outcomes_by_kind["tiktok-direct"],
                },
            },
        }

    def list_gifts(self, *, limit: int = 200):
        return self._persistence.list_gifts(limit=limit)

    def list_matches(
        self,
        *,
        room_id: int | None = None,
        host_unique_id: str | None = None,
        limit: int = 50,
    ):
        return self._persistence.list_matches(
            room_id=room_id,
            host_unique_id=host_unique_id,
            limit=limit,
        )

    def get_active_match(self, room_id: int):
        return self._persistence.get_active_match(room_id)

    def match_diamonds_totals(self, match_ids: list[int]) -> dict[int, int]:
        return self._persistence.match_diamonds_totals(match_ids)

    def close_orphan_matches(self) -> int:
        return self._persistence.close_orphan_matches()

    def list_user_matches(
        self,
        *,
        user_id: int,
        room_ids: list[int] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self._persistence.list_user_matches(
            user_id=user_id,
            room_ids=room_ids,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

    # ── profile cache ────────────────────────────────────────────────

    async def refresh_profile(self, unique_id: str) -> None:
        """Fetch a creator's public profile and persist into the
        subscription row. Logs and stores any error but never raises."""
        from adapters.tiktok_profile_scraper import fetch_public_profile
        unique_id = self._normalize(unique_id)
        if not unique_id:
            return
        try:
            data = await fetch_public_profile(unique_id)
        except Exception as e:
            logger.warning("refresh_profile crash for @%s: %r", unique_id, e)
            self._persistence.update_subscription_profile(
                unique_id, profile={}, error=f"{type(e).__name__}: {e}"
            )
            return

        # Persist the structured probe trail to the audit log on EVERY
        # refresh that had any non-trivial probe outcome. This way an
        # admin viewing the live-detail page can see the technical
        # reasons across recent refreshes — including the cases where
        # one URL got WAF'd but a different URL succeeded (so error is
        # cleared but the WAF event is still recorded).
        probe_debug = data.get("probe_debug") or []
        bad_probes = [
            p for p in probe_debug
            if p.get("reason") not in ("no LiveRoom in SIGI_STATE", "no liveRoomUserInfo")
        ]
        if bad_probes:
            self._log_worker(
                "profile_probe_failed" if data.get("error") else "profile_probe_partial",
                level="warning" if data.get("error") else "info",
                handle=unique_id,
                detail={"probes": bad_probes},
            )

        if data.get("error"):
            self._persistence.update_subscription_profile(
                unique_id, profile={}, error=data["error"]
            )
            return

        # Map scraper output → DB field names. The scraper already shapes
        # most field names to match; just coerce IDs.
        profile_record: dict[str, Any] = {
            "profile_user_id": _safe_int(data.get("user_id")),
            "sec_uid": data.get("sec_uid"),
            "nickname": data.get("nickname"),
            "avatar_url": data.get("avatar_url"),
            "bio": data.get("bio"),
            "verified": data.get("verified"),
            "private": data.get("private"),
            "follower_count": data.get("follower_count"),
            "following_count": data.get("following_count"),
        }
        self._persistence.update_subscription_profile(
            unique_id, profile=profile_record, error=None
        )

    async def refresh_stale_profiles(
        self, *, stale_after_seconds: int | None = None, limit: int = 100
    ) -> int:
        """Refresh every subscription whose profile is stale. Returns the
        number of refresh attempts (regardless of success). Spaces calls
        out to avoid hammering TikTok.

        Euler-quota optimization: handles with an actively CONNECTED
        listener (events flowing right now) are skipped entirely —
        events arriving via the WebSocket are proof of liveness, so
        burning an Euler-signed probe to confirm what we already know
        is pure waste. Their `profile_refreshed_at` stays stale, but
        as soon as the WS drops the handle moves out of CONNECTED and
        becomes eligible again on the next pass.
        """
        if stale_after_seconds is None:
            stale_after_seconds = self.PROFILE_STALE_AFTER_SECONDS
        # Fetch at the SHORTER window; the offline-backoff predicate
        # below decides which rows to actually refresh. (Asking the DB
        # for the longer window would miss handles that just went from
        # live → offline.)
        stale = self._persistence.list_subscriptions_with_stale_profiles(
            stale_after_seconds=stale_after_seconds
        )[:limit]
        connected_now = {
            h for h, st in self._states.items()
            if st == SubscriptionState.CONNECTED.value
        }
        now = _utcnow()
        offline_cutoff = timedelta(
            seconds=self.PROFILE_STALE_AFTER_SECONDS_OFFLINE
        )
        skipped_connected = 0
        skipped_offline = 0
        count = 0
        for sub in stale:
            if sub.unique_id in connected_now:
                skipped_connected += 1
                continue
            # Offline backoff: if the probe says is_live=False, only
            # refresh every PROFILE_STALE_AFTER_SECONDS_OFFLINE
            # instead of …_SECONDS. The live-status scraper has its
            # own faster cadence (60s TTL) and will flip is_live=True
            # the moment the host starts streaming — at which point
            # this handle qualifies again on the next pass.
            if sub.is_live is False and sub.profile_refreshed_at is not None:
                age = now - sub.profile_refreshed_at
                if age < offline_cutoff:
                    skipped_offline += 1
                    continue
            await self.refresh_profile(sub.unique_id)
            count += 1
            await asyncio.sleep(self.PROFILE_REFRESH_PER_HANDLE_DELAY_SECONDS)
        if skipped_connected or skipped_offline:
            logger.info(
                "Profile refresh: skipped %d connected + %d offline-backoff "
                "= %d Euler call(s) saved (refreshed %d).",
                skipped_connected, skipped_offline,
                skipped_connected + skipped_offline, count,
            )
        return count

    # Live-status scraper config.
    # Per-handle cache TTL — how stale a handle's `is_live` can be
    # before the scraper is allowed to re-check.
    LIVE_STATUS_TTL_SECONDS = 60
    # Minimum pause between consecutive scrapes by THIS scraper. With
    # a single scraper per worker + this cadence, we cap outbound
    # requests to TikTok at ~1 every PAUSE seconds (~12 req/min) for
    # the entire worker, regardless of how many offline handles it owns.
    LIVE_SCRAPE_PAUSE_SECONDS = 5.0

    async def _live_scraper_loop(self) -> None:
        """One scraper task per worker. Walks claimed handles round-robin
        and refreshes their `is_live` cache via `fetch_public_profile`,
        with a built-in pause between requests so the per-IP rate stays
        under TikTok's anti-bot threshold.

        Supervisors don't poll TikTok themselves anymore — they read the
        DB cache via `peek_live_status`.
        """
        # Lazy import — avoids circular reference and keeps test surface
        # tight (the live-client adapter pulls in TikTokLive).
        from adapters.tiktok_live_client import fetch_public_profile_throttled

        # Initial pause: don't compete with the boot connect storm.
        try:
            await asyncio.sleep(15.0)
        except asyncio.CancelledError:
            raise

        while True:
            try:
                if self._worker_id is None:
                    await asyncio.sleep(5.0)
                    continue
                targets = self._persistence.list_live_status_targets(
                    self._worker_id,
                    max_age_seconds=self.LIVE_STATUS_TTL_SECONDS,
                    limit=50,
                )
                if not targets:
                    # Nothing to check — wait a bit and try again.
                    await asyncio.sleep(self.LIVE_SCRAPE_PAUSE_SECONDS)
                    continue
                for sub in targets:
                    if self._stopped_flag():
                        return
                    try:
                        profile = await fetch_public_profile_throttled(
                            sub.unique_id
                        )
                    except Exception:
                        logger.exception(
                            "Live-status scrape raised for @%s", sub.unique_id
                        )
                        profile = None
                    # Tri-state read: True / False / None. Don't coerce
                    # None → False — the scraper now returns None when
                    # it couldn't determine live status (TikTok 403'd,
                    # WAF'd, or the SIGI script tag was missing). The
                    # supervisor's recycle path uses None to mean
                    # "unknown — don't touch the slot." Coercing here
                    # would evict working sessions any time TikTok's
                    # CDN blocked our probe, which is exactly the cascade
                    # observed: 1 sec of 403s ➜ slot recycled ➜ 1 fewer
                    # session ➜ next sub falls off too.
                    raw_is_live = profile.get("is_live") if profile else None
                    if raw_is_live is None:
                        is_live = None
                        # Stage-2 stuck-slot defense (2026-05-14):
                        # track WHEN this host's probe started returning
                        # None continuously. Cleared the moment we get a
                        # definite True/False. The reconcile loop reads
                        # this + PROBE_UNKNOWN_RELEASE_S to release slots
                        # whose probe is permanently stuck.
                        self._probe_unknown_since.setdefault(
                            sub.unique_id, time.time(),
                        )
                    else:
                        is_live = bool(raw_is_live)
                        self._probe_unknown_since.pop(sub.unique_id, None)
                    room_id_raw = profile.get("room_id") if profile else None
                    try:
                        room_id = int(room_id_raw) if room_id_raw else None
                    except (TypeError, ValueError):
                        room_id = None
                    try:
                        self._persistence.update_live_status(
                            sub.unique_id,
                            is_live=is_live,
                            room_id=room_id,
                        )
                    except Exception:
                        logger.exception(
                            "update_live_status failed for @%s", sub.unique_id
                        )
                    # Pause between scrapes — the throttled fetcher
                    # already enforces a 5s gap, but we add an explicit
                    # await here so other tasks (heartbeat, reconcile)
                    # get scheduling time.
                    await asyncio.sleep(self.LIVE_SCRAPE_PAUSE_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Live scraper pass failed; retrying.")
                await asyncio.sleep(5.0)

    def _stopped_flag(self) -> bool:
        """Cooperative cancellation — internal tasks check this so they
        bail when the service is winding down (e.g., during
        reconcile-driven session swaps)."""
        return False  # placeholder; service-level stop is handled by task.cancel()

    def peek_live_status(self, unique_id: str) -> dict[str, Any] | None:
        """Read the cached live-status row from DB. Returns
        `{is_live, room_id, age_s}` or None if no row.

        Supervisors call this from `_wait_until_live` to decide whether
        to (re)connect, instead of doing their own HTTP scrape."""
        sub = self._persistence.get_subscription(unique_id)
        if sub is None:
            return None
        if sub.live_checked_at is None:
            return {"is_live": None, "room_id": None, "age_s": None}
        from datetime import datetime as _dt
        age = (_dt.now(timezone.utc) - sub.live_checked_at).total_seconds()
        return {
            "is_live": sub.is_live,
            "room_id": sub.current_room_id,
            "age_s": age,
        }

    async def _profile_refresher_loop(self) -> None:
        """Run forever, refreshing stale profiles on a fixed cadence."""
        # Initial pass on a short delay so a freshly-booted server fills
        # in any handles that have never been refreshed.
        try:
            await asyncio.sleep(15.0)
            n = await self.refresh_stale_profiles()
            if n:
                logger.info("Initial profile refresh: %d handle(s).", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Initial profile refresh failed; continuing on schedule.")

        while True:
            try:
                await asyncio.sleep(self.PROFILE_REFRESH_PERIOD_SECONDS)
                n = await self.refresh_stale_profiles()
                if n:
                    logger.info("Periodic profile refresh: %d handle(s) updated.", n)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Profile refresh pass failed; will retry next tick.")

    def _enrich_match_opponents(self, match) -> None:
        """For each opponent missing nickname/avatar/unique_id, fill from
        local caches. Mutates match.opponents in place.

        Three lookup tiers, applied in order:
          1. tiktok_viewers — populated from any comment/gift event the
             user has been part of. Often empty for the rival side of a
             PK because they don't comment in the host's own room.
          2. tiktok_subscriptions — when the opponent is one of our own
             monitored creators (they often PK with each other), this has
             full profile data including avatar from the periodic refresh.
          3. background live fetch — see schedule_opponent_profile_fetches;
             that one runs out-of-band and updates the match row directly,
             so subsequent reads will see the result.
        """
        if not match or not match.opponents:
            return
        missing_ids: list[int] = []
        missing_handles: list[str] = []
        for o in match.opponents:
            if not isinstance(o, dict):
                continue
            uid = o.get("user_id")
            handle = o.get("unique_id")
            needs = (
                not o.get("nickname")
                or not o.get("avatar_url")
                or not o.get("unique_id")
            )
            if not needs:
                continue
            if uid is not None:
                try:
                    missing_ids.append(int(uid))
                except (TypeError, ValueError):
                    pass
            if handle:
                missing_handles.append(handle.lstrip("@"))

        # Tier 1: viewers cache.
        viewers = (
            self._persistence.get_viewers_by_ids(missing_ids) if missing_ids else {}
        )

        # Tier 2: subscriptions cache (other monitored creators).
        # Targeted lookup by user_id + per-handle fallback — far cheaper
        # than scanning the whole subscriptions table on every poll.
        sub_by_uid: dict[int, Any] = (
            self._persistence.get_subscriptions_by_user_ids(missing_ids)
            if missing_ids else {}
        )
        sub_by_handle: dict[str, Any] = {}
        for handle in missing_handles:
            sub = self._persistence.get_subscription(handle)
            if sub is not None:
                sub_by_handle[handle] = sub

        for o in match.opponents:
            if not isinstance(o, dict):
                continue
            uid = o.get("user_id")
            uid_int: int | None = None
            if uid is not None:
                try:
                    uid_int = int(uid)
                except (TypeError, ValueError):
                    pass

            v = viewers.get(uid_int) if uid_int is not None else None
            sub = (
                sub_by_uid.get(uid_int)
                if uid_int is not None
                else None
            ) or sub_by_handle.get((o.get("unique_id") or "").lstrip("@"))

            if v is not None:
                if not o.get("nickname") and v.nickname:
                    o["nickname"] = v.nickname
                if not o.get("avatar_url") and v.avatar_url:
                    o["avatar_url"] = v.avatar_url
                if not o.get("unique_id") and v.unique_id:
                    o["unique_id"] = v.unique_id

            if sub is not None:
                if not o.get("nickname") and sub.nickname:
                    o["nickname"] = sub.nickname
                if not o.get("avatar_url") and sub.avatar_url:
                    o["avatar_url"] = sub.avatar_url
                if not o.get("unique_id") and sub.unique_id:
                    o["unique_id"] = sub.unique_id

    def schedule_opponent_profile_fetches(self, match_id: int) -> None:
        """Kick off a background task that fetches public profiles for
        any opponent missing avatar/nickname and writes them back to the
        match row. Safe to call multiple times — the task itself dedups
        by checking what's already filled."""
        self._spawn_bg(
            self._opponent_profile_fetch_task(match_id),
            name=f"opponent_profile_fetch:{match_id}",
        )

    async def _opponent_profile_fetch_task(self, match_id: int) -> None:
        from adapters.tiktok_profile_scraper import fetch_public_profile

        # Find the room this match belongs to via the in-memory map.
        target_room_id: int | None = None
        for room_id, info in self._active_match.items():
            if info.get("match_id") == match_id:
                target_room_id = room_id
                break
        if target_room_id is None:
            return  # match was closed before we got here

        match = self._persistence.get_active_match(target_room_id)
        if match is None or match.id != match_id or not match.opponents:
            return

        # Determine which opponents need a fetch (have a unique_id but no
        # avatar). Skip ones we already have nicknames + avatars for.
        targets: list[str] = []
        for o in match.opponents:
            if not isinstance(o, dict):
                continue
            handle = (o.get("unique_id") or "").lstrip("@")
            if not handle:
                continue
            if o.get("avatar_url") and o.get("nickname"):
                continue
            targets.append(handle)

        if not targets:
            return

        # Fetch sequentially with a short delay — TikTok's WAF is sensitive
        # to bursts. Two opponents per battle is the typical case.
        new_opponents = list(match.opponents)
        changed = False
        for handle in targets:
            try:
                profile = await fetch_public_profile(handle)
            except Exception:
                logger.exception("Opponent profile fetch crashed for @%s", handle)
                continue
            if not profile or profile.get("error"):
                continue
            for o in new_opponents:
                if not isinstance(o, dict):
                    continue
                if (o.get("unique_id") or "").lstrip("@") != handle:
                    continue
                if not o.get("nickname") and profile.get("nickname"):
                    o["nickname"] = profile["nickname"]
                    changed = True
                if not o.get("avatar_url") and profile.get("avatar_url"):
                    o["avatar_url"] = profile["avatar_url"]
                    changed = True
                if not o.get("user_id") and profile.get("user_id"):
                    o["user_id"] = profile["user_id"]
                    changed = True
            await asyncio.sleep(1.0)

        if changed:
            try:
                self._persistence.update_match(match_id, opponents=new_opponents)
                logger.info(
                    "Filled profile data for opponents in match %s.", match_id
                )
            except Exception:
                logger.exception("Persisting enriched opponents failed for match=%s", match_id)

    def search_events(
        self,
        *,
        host_unique_id: str | None = None,
        room_id: int | None = None,
        room_ids: list[int] | None = None,
        user_id: int | None = None,
        match_id: int | None = None,
        type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
        to_user_id: int | None = None,
        min_diamonds: int | None = None,
        limit: int = 200,
        before_id: int | None = None,
        offset: int = 0,
    ):
        return self._persistence.search_events(
            host_unique_id=host_unique_id,
            room_id=room_id,
            room_ids=room_ids,
            user_id=user_id,
            match_id=match_id,
            type=type,
            since=since,
            until=until,
            q=q,
            to_user_id=to_user_id,
            min_diamonds=min_diamonds,
            limit=limit,
            before_id=before_id,
            offset=offset,
        )

    def count_events(
        self,
        *,
        host_unique_id: str | None = None,
        room_id: int | None = None,
        room_ids: list[int] | None = None,
        user_id: int | None = None,
        match_id: int | None = None,
        type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
        to_user_id: int | None = None,
        min_diamonds: int | None = None,
    ) -> int:
        return self._persistence.count_events(
            host_unique_id=host_unique_id,
            room_id=room_id,
            room_ids=room_ids,
            user_id=user_id,
            match_id=match_id,
            type=type,
            since=since,
            until=until,
            q=q,
            to_user_id=to_user_id,
            min_diamonds=min_diamonds,
        )

    # ── Match detail (PK battle dashboard) ────────────────────────────

    def get_match_by_id(self, match_id: int):
        return self._persistence.get_match_by_id(int(match_id))

    def get_room_host_handle(self, room_id: int) -> str | None:
        return self._persistence.get_room_host_handle(int(room_id))

    def get_match_score_timeline(self, match_id: int) -> list[dict[str, Any]]:
        return self._persistence.get_match_score_timeline(int(match_id))

    def get_match_gifters_by_side(
        self, match_id: int, *, public_only: bool = False,
    ) -> dict[str, Any]:
        match = self._persistence.get_match_by_id(int(match_id))
        if match is None:
            return {"host": [], "opponent": [], "unknown": [], "totals": {}}
        host = self._persistence.get_room_host_handle(match.room_id)
        # Find sibling match rows: same TikTok PK observed from another
        # monitored host's WebSocket. Each sibling has its own `match_id`
        # but shares `battle_id` with us. Their events get merged into
        # the donor panel below so a 1v1 between two tracked hosts no
        # longer hides one side's gifters.
        #
        # The `public_only=True` flag (set by the public mirror route)
        # tells the persistence layer to drop any sibling whose host
        # is NOT opted into the public surface — without it we'd leak
        # both the private host's room_id (in `sibling_room_ids`) AND
        # their gift-event stream (merged into the donor list) to
        # anonymous viewers.
        sibling_match_ids: list[int] = []
        if match.battle_id is not None:
            try:
                sibling_match_ids = self._persistence.get_match_ids_by_battle_id(
                    int(match.battle_id), exclude_match_id=int(match_id),
                )
            except Exception:
                logger.exception(
                    "sibling-match lookup failed for battle_id=%s",
                    match.battle_id,
                )
        result = self._persistence.get_match_gifters_by_side(
            int(match_id),
            host_unique_id=host or "",
            opponents=match.opponents or [],
            sibling_match_ids=sibling_match_ids,
            public_only=public_only,
        )
        # Stringify user_id for JS BigInt safety.
        for side in ("host", "opponent", "unknown"):
            for r in result.get(side, []):
                if r.get("user_id") is not None:
                    r["user_id"] = str(r["user_id"])
        return result

    def get_match_head_to_head(
        self, match_id: int, *, limit: int = 50,
    ) -> list[dict[str, Any]]:
        match = self._persistence.get_match_by_id(int(match_id))
        if match is None:
            return []
        host = self._persistence.get_room_host_handle(match.room_id)
        return self._persistence.get_match_head_to_head(
            int(match_id),
            host_unique_id=host or "",
            opponents=match.opponents or [],
            limit=int(limit),
        )

    def get_h2h_common_gifters(
        self, match_id: int, *, min_battles: int = 2, limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Returns viewers who gifted in ≥`min_battles` of this
        match's head-to-head set — i.e. regulars who follow the
        rivalry. Resolves the H2H match set first, then aggregates."""
        match = self._persistence.get_match_by_id(int(match_id))
        if match is None:
            return []
        host = self._persistence.get_room_host_handle(match.room_id)
        h2h = self._persistence.get_match_head_to_head(
            int(match_id),
            host_unique_id=host or "",
            opponents=match.opponents or [],
            limit=200,  # pull a wide net for the gifter intersection
        )
        # Include the *current* match too — regulars showing up TODAY
        # are part of the story.
        ids = [int(match.id)] if match.id else []
        ids.extend(int(r["id"]) for r in h2h if r.get("id"))
        if not ids:
            return []
        return self._persistence.get_h2h_common_gifters(
            ids, min_battles=int(min_battles), limit=int(limit),
        )

    # ── stats / dashboard ────────────────────────────────────────────

    def get_aggregated_buckets(
        self,
        room_ids: list[int],
        *,
        since: datetime,
        until: datetime,
        bucket_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Bucketed event series summed across multiple rooms in a
        single SQL group-by. Replaces the previous "fan out N parallel
        getRoomStats and sum on the client" path used by the calendar
        day-view, cutting wall time from O(N × room_query_time) to
        one round-trip."""
        def _ensure_aware_utc(d: datetime) -> datetime:
            if d.tzinfo is None:
                return d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        s = _ensure_aware_utc(since)
        u = _ensure_aware_utc(until)
        range_seconds = max(1, int((u - s).total_seconds()))
        if bucket_seconds is None or bucket_seconds <= 0:
            bucket_seconds = _auto_bucket_seconds(range_seconds)
        elif range_seconds // bucket_seconds > 600:
            bucket_seconds = _auto_bucket_seconds(range_seconds)
        return self._persistence.room_event_buckets(
            [int(x) for x in room_ids],
            since=s,
            until=u,
            bucket_seconds=bucket_seconds,
        )

    def get_room_stats(
        self,
        room_id: int,
        *,
        window_minutes: int = 30,
        bucket_seconds: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        gifters_limit: int = 10,
    ) -> dict[str, Any]:
        """Per-room stats: counters, top gifters, time-bucketed series.

        Two modes:
          - Sliding window (default): pass `window_minutes` only.
          - Explicit range: pass `since` (and optionally `until`) — used
            by the frontend's "Entire last broadcast" / "All time" modes.

        bucket_seconds auto-scales to keep the bucket count manageable
        (~30–120 buckets) when not explicitly provided.
        """
        now = datetime.now(timezone.utc)
        # Storage is tz-aware (timestamptz). Inputs may arrive naive (older
        # callers) or aware. Normalize all to aware UTC so DB comparisons
        # don't raise "naive vs aware" errors.
        def _ensure_aware_utc(d: datetime | None) -> datetime | None:
            if d is None:
                return None
            if d.tzinfo is None:
                return d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        since = _ensure_aware_utc(since)
        until = _ensure_aware_utc(until)
        if since is None:
            since = now - timedelta(minutes=window_minutes)
        if until is None:
            until = now
        if since > until:
            since, until = until, since
        # Recompute window_minutes from the resolved range so downstream
        # response fields stay consistent.
        window_minutes = max(1, int((until - since).total_seconds() / 60))

        # Auto-pick a bucket size if the caller didn't (or asked for too
        # fine a bucket relative to the range).
        range_seconds = max(1, int((until - since).total_seconds()))
        if bucket_seconds is None or bucket_seconds <= 0:
            bucket_seconds = _auto_bucket_seconds(range_seconds)
        elif range_seconds // bucket_seconds > 600:
            # More than 600 buckets is a chart-too-dense problem; coerce up.
            bucket_seconds = _auto_bucket_seconds(range_seconds)

        room = self._persistence.get_room(room_id)
        counts_window = self._persistence.room_event_counts_by_type(
            room_id, since=since, until=until
        )
        counts_total = self._persistence.room_event_counts_by_type(room_id)
        # Top gifters honor the FULL window (since + until). For a past-match
        # modal, the modal sends until=match.ended_at; without that bound we'd
        # rank gifters from match start through "now", so every old match
        # would surface the room's all-time top gifter.
        top_gifters = self._persistence.room_top_gifters(
            room_id, since=since, until=until, limit=gifters_limit
        )

        # SQL-side bucketing — replaces the previous Python loop over
        # list_events(limit=10000). The 10k cap silently truncated long
        # broadcasts to roughly the latest 30 minutes of activity, so the
        # headline diamonds_total + per-type series both understated heavy
        # rooms (e.g. tonoabril__'s 40k-event broadcast: chart showed only
        # the most recent slice while top-gifters aggregated everything,
        # so the totals didn't match the leaderboard).
        buckets = self._persistence.room_event_buckets(
            room_id,
            since=since,
            until=until,
            bucket_seconds=bucket_seconds,
        )
        bucket_starts = buckets.get("starts", [])
        bucket_counts: dict[str, list[int]] = buckets.get("by_type", {})
        diamond_buckets: list[int] = buckets.get("diamonds", [])
        diamonds_total = int(buckets.get("diamonds_total", 0))

        # BigInt ids → strings on the wire (see tiktok.py response models).
        gifters_serialized = [
            {**g, "user_id": str(g["user_id"]) if g.get("user_id") is not None else None}
            for g in top_gifters
        ]
        active_match = self._persistence.get_active_match(room_id) if room else None
        active_match_serialized = None
        if active_match and active_match.id is not None:
            self._enrich_match_opponents(active_match)
            diamonds_for_match = self._persistence.match_diamonds_totals(
                [active_match.id]
            ).get(active_match.id, 0)
            active_match_serialized = _match_to_dict(
                active_match, diamonds_total=diamonds_for_match
            )
        return {
            "room": {
                "room_id": str(room.room_id),
                "host_unique_id": room.host_unique_id,
                "title": room.title,
                "started_at": room.started_at.isoformat() if room.started_at else None,
                "ended_at": room.ended_at.isoformat() if room.ended_at else None,
                "first_seen_at": room.first_seen_at.isoformat() if room.first_seen_at else None,
                "last_seen_at": room.last_seen_at.isoformat() if room.last_seen_at else None,
            }
            if room
            else None,
            "window_minutes": window_minutes,
            "bucket_seconds": bucket_seconds,
            "since": since.isoformat(),
            "now": now.isoformat(),
            "counts_window": counts_window,
            "counts_total": counts_total,
            "top_gifters": gifters_serialized,
            "diamonds_total": diamonds_total,
            "active_match": active_match_serialized,
            "buckets": {
                "starts": bucket_starts,
                "by_type": bucket_counts,
                "diamonds": diamond_buckets,
            },
        }

    def get_dashboard_stats(
        self,
        *,
        since_hours: int = 24,
        bucket_seconds: int = 3600,
        tz: str = "UTC",
    ) -> dict[str, Any]:
        """Cross-creator totals + time series for the dashboard.
        Bucket boundaries respect `tz` so a Lima viewer's "day" /
        "hour" labels line up with their wall clock."""
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=since_hours)

        per_host_counts = self._persistence.host_event_counts_by_type(since=since)
        buckets = self._persistence.host_event_buckets(
            since=since, bucket_seconds=bucket_seconds, tz=tz,
        )

        # Build a normalized "by_host" summary with totals + per-type counts.
        creators: list[dict[str, Any]] = []
        for host, by_type in per_host_counts.items():
            total = sum(by_type.values())
            creators.append(
                {
                    "host_unique_id": host,
                    "total": total,
                    "by_type": by_type,
                }
            )
        creators.sort(key=lambda c: c["total"], reverse=True)

        return {
            "since": since.isoformat(),
            "now": now.isoformat(),
            "since_hours": since_hours,
            "bucket_seconds": bucket_seconds,
            "creators": creators,
            "buckets": buckets,
        }

    def get_room_recipients(
        self,
        room_id: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Per-recipient gift totals for a room. Answers "of all gifts in
        this broadcast, who got how much?" — meaningful in multi-guest
        lives and PK battles. Pre-`to_user` rows return nothing."""
        def _ensure_aware_utc(d: datetime | None) -> datetime | None:
            if d is None:
                return None
            if d.tzinfo is None:
                return d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        items = self._persistence.room_top_recipients(
            room_id,
            since=_ensure_aware_utc(since),
            until=_ensure_aware_utc(until),
            limit=limit,
        )
        items_serialized = [
            {**g, "user_id": str(g["user_id"]) if g.get("user_id") is not None else None}
            for g in items
        ]
        total_diamonds = sum(g["diamonds"] for g in items)
        return {
            "items": items_serialized,
            "total_diamonds": int(total_diamonds),
            "limit": int(limit),
        }

    def get_room_gifters(
        self,
        room_id: int | list[int],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Paginated top gifters for a room. Same window/filter shape as
        get_room_stats; mirrors the dashboard's gifter card.

        Returns: {items, total, limit, offset}
        """
        def _ensure_aware_utc(d: datetime | None) -> datetime | None:
            if d is None:
                return None
            if d.tzinfo is None:
                return d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc)
        since_ = _ensure_aware_utc(since)
        until_ = _ensure_aware_utc(until)
        items = self._persistence.room_top_gifters(
            room_id,
            since=since_,
            until=until_,
            limit=limit,
            offset=offset,
            q=q,
        )
        total = self._persistence.count_room_gifters(
            room_id,
            since=since_,
            until=until_,
            q=q,
        )
        # BigInt user_ids → strings on the wire.
        items_serialized = [
            {**g, "user_id": str(g["user_id"]) if g.get("user_id") is not None else None}
            for g in items
        ]
        return {
            "items": items_serialized,
            "total": int(total),
            "limit": int(limit),
            "offset": int(offset),
        }

    def get_common_gifter_detail(
        self, user_id: int, *, public_only: bool = False,
    ) -> dict[str, Any]:
        return self._persistence.common_gifter_detail(
            int(user_id), public_only=public_only,
        )

    def get_user_host_daily_series(
        self, user_id: int, *, host_unique_id: str, days: int = 30,
    ) -> list[dict[str, Any]]:
        """Per-day diamond + gift totals for a single (user, host)
        pair. Powers the gifter modal's Timeline tab — a lighter
        query than the full cross-host detail."""
        return self._persistence.get_user_host_daily_series(
            int(user_id), host_unique_id=host_unique_id, days=int(days),
        )

    # ── Notifications history ────────────────────────────────────────

    # ── Lives-page row enrichment ───────────────────────────────────

    # Per-process TTL cache for the lives-summary endpoint. Frontend
    # polls every 30s and multiple admin tabs hit the same data — a
    # short TTL collapses concurrent fetches to one DB round-trip per
    # window, multiplying savings under N tabs/users. 10s is short
    # enough that operators don't notice staleness on viewer counts /
    # session diamonds; the cache key is the sorted handle tuple so
    # different filters get their own slot.
    # TTL = 35 s, intentionally longer than the frontend's 30 s poll
    # cadence. If TTL < poll, every poll catches an expired cache and
    # re-runs `get_lives_summary` (the ~22 SQL queries). With TTL > poll,
    # each poll's compute refreshes the cache for the NEXT poll window
    # — so steady-state polling hits the cache uninterrupted, and only
    # the first request after a backend restart (handled by the warm-up
    # task) or a >35 s gap pays the cold cost. Page freshness stays
    # within one poll period; the in-flight WebSocket stream provides
    # real-time events alongside this slower-cadence rollup. The
    # frontend Cache-Control: max-age=10 in the route layer is the
    # browser-side cap and is intentionally tighter than this TTL.
    # 60 s — doubles the headroom over the 30 s frontend poll cycle.
    # Was 35 s before; that was tight enough that a slightly late
    # poll (network jitter, browser scheduler skew) could miss the
    # cache. 60 s means two consecutive polls always hit warm cache
    # in steady state; cold miss only on (a) backend restart or (b)
    # the rare ≥60 s page idle. Trade-off: data staleness window
    # widens by ~25 s, which is acceptable for the rollup-style
    # numbers on the card (per-event freshness comes from the WS feed).
    _LIVES_SUMMARY_TTL_S = 60.0
    _lives_summary_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
    # Per-key singleflight locks. When N concurrent callers race for
    # the same cache key on a cold miss (warm-up + first user request,
    # or multiple admin tabs opening at once), only one runs the SQL;
    # the rest block on the lock, then read the now-populated cache.
    # Without this the warm-up I added on startup duplicates work with
    # whoever hits the route first. The meta-lock guards lock-creation
    # so two callers don't each instantiate a fresh per-key lock.
    _lives_summary_locks: dict[tuple[str, ...], threading.Lock] = {}
    _lives_summary_meta_lock = threading.Lock()

    # Phase 9C: fields the state cache provably maintains in lock-step
    # with `get_lives_summary` (per `test_state_cache_parity.py`). These
    # are the only fields we overlay from cache onto the SQL result —
    # everything else (historical broadcasts, time-bucketed aggregates,
    # 30-day rollups) stays SQL-driven because the event-driven cache
    # doesn't track them.
    #
    # Adding a field here means committing to: (a) the cache writes it
    # on every relevant event, and (b) the parity oracle test covers it.
    _CACHE_OVERLAY_FIELDS: frozenset[str] = frozenset({
        "active_room_id",
        "live_started_at",
        "diamonds_session",
        "session_stats",
        "top_gifters",
        "n_unique_gifters",
        "n_first_time_gifters",
        "viewer_count",
        "viewer_history",
        "n_envelopes_session",
        "envelope_diamonds_session",
        "n_pauses",
        "last_pause_age_s",
        "active_match",
        "active_poll",
        "last_gift_age_s",
        "last_comment_age_s",
        "last_event_age_s",
    })

    @property
    def _state_cache(self) -> Any:
        """The persistence adapter is the owner of the state-cache
        adapter (it's wired in `api_main._build_tiktok_state_cache`
        + passed via `TikTokPersistenceAdapter(state_cache=...)`).
        Surface it as a service-level property so the overlay logic
        in `get_lives_summary` doesn't need a separate constructor
        argument or DI step. Returns None when no cache is wired
        (`PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH=off`)."""
        return getattr(self._persistence, "_state_cache", None)

    def get_lives_summary(self, handles: list[str]) -> dict[str, Any]:
        """Returns the per-host summary dict.

        SQL fan-out runs with the existing 60s TTL + singleflight (the
        cache key is `tuple(sorted(handles))`). Phase 9C: when a state
        cache is wired, every returned slice is overlaid with the
        cache's session-incremental fields and tagged with a monotonic
        `version` integer. Without a state cache, behavior is
        identical to Phase 9A (no `version` field on slices).

        The overlay is a fresh dict per call — the TTL cache stores
        the raw SQL result so we don't poison it across calls. Overlay
        cost is sub-ms (in-process or Redis HGET)."""
        key = tuple(sorted(handles))
        now = time.monotonic()
        sql_result: dict[str, Any]
        hit = self._lives_summary_cache.get(key)
        if hit and (now - hit[0]) < self._LIVES_SUMMARY_TTL_S:
            sql_result = hit[1]
        else:
            # Cold miss — singleflight. Get or create the per-key lock.
            with self._lives_summary_meta_lock:
                lock = self._lives_summary_locks.get(key)
                if lock is None:
                    lock = threading.Lock()
                    self._lives_summary_locks[key] = lock

            with lock:
                # Double-checked: another caller may have populated the
                # cache while we were waiting on the lock.
                now2 = time.monotonic()
                hit2 = self._lives_summary_cache.get(key)
                if hit2 and (now2 - hit2[0]) < self._LIVES_SUMMARY_TTL_S:
                    sql_result = hit2[1]
                else:
                    sql_result = self._persistence.get_lives_summary(handles)
                    self._lives_summary_cache[key] = (now2, sql_result)

        # Phase 9C: state-cache overlay + per-host version.
        if self._state_cache is None:
            return sql_result
        return self._overlay_state_cache(sql_result, handles)

    def _overlay_state_cache(
        self,
        sql_result: dict[str, Any],
        handles: list[str],
    ) -> dict[str, Any]:
        """Build a fresh dict-of-dicts: for each handle, start from the
        SQL slice (shallow-copied so the TTL cache isn't poisoned),
        replace any field in `_CACHE_OVERLAY_FIELDS` with the cached
        value when present, and attach `version`.

        Handles not in the SQL result get a slice synthesized purely
        from cache (rare — happens when the SQL `list_subscriptions`
        upstream from us hasn't picked up a brand-new handle yet)."""
        out: dict[str, Any] = {h: dict(slice_) for h, slice_ in sql_result.items()}
        for handle in handles:
            norm = handle.lstrip("@").lower()
            slice_ = out.setdefault(norm, {})
            try:
                cached = self._state_cache.get(norm)
            except Exception:
                logger.exception(
                    "state-cache read failed for %s — falling back to SQL only",
                    norm,
                )
                cached = None
            if cached is None:
                # No cache entry yet — version 0 lets clients detect
                # that no events have flowed through this host yet, and
                # any subsequent delta (version >= 1) is a strict
                # advance from their viewpoint.
                slice_.setdefault("version", 0)
                continue
            version, cache_state = cached
            for k in self._CACHE_OVERLAY_FIELDS:
                if k in cache_state:
                    slice_[k] = cache_state[k]
            slice_["version"] = version
        return out

    # ── Public-lives sanitizer allowlists ────────────────────────────
    #
    # Two allowlists, one per object in each `items[]` entry. Anything
    # NOT in these tuples is operator-only and MUST NOT leak through
    # the unauthenticated endpoint. The shape is intentionally similar
    # to (subset of) the admin types `TikTokSubscription` + `TikTokLiveSummary`
    # so the public page can reuse the same card renderer as
    # /admin/tiktok with admin actions stripped.
    #
    # Build-by-copy semantics: `_pick(src, allow)` only ever COPIES
    # known-safe keys into a fresh dict. Never the inverse (drop known-
    # bad keys), which fails open the moment a new operator-only key
    # is added upstream.
    #
    # If you're adding a new key to `get_lives_summary` or the
    # `Subscription` dataclass, decide explicitly: is this already
    # visible on TikTok itself for the same creator? If yes, add it
    # here. If no (internal listener state, derived-from-our-history
    # numbers, operator-curated lists, internal identifiers), leave
    # it out. Default is private.

    # Subscription fields the public can see. These mirror what's on
    # the creator's TikTok profile page — nickname, avatar, bio,
    # follower count, etc. Excluded: sec_uid / profile_user_id (internal
    # ids), private (profile-is-private flag is internal), profile_error
    # / profile_refreshed_at / updated_at (operator-only),
    # enabled / state / is_connected / room_id / assigned_worker_id /
    # assignment_lease_until (listener internals).
    _PUBLIC_SUBSCRIPTION_FIELDS = (
        "unique_id",
        "nickname",
        "avatar_url",
        "bio",
        "verified",
        "follower_count",
        "following_count",
        "is_live",
        "current_room_id",
        "live_checked_at",
        "created_at",
    )

    # Summary fields the public can see. Everything here is either
    # visible on TikTok's live UI (viewer count, top gifters on the
    # leaderboard, active PK overlay, active poll, last gift age via
    # observation) or derivable from public data (heat ratio, hourly
    # diamonds buckets from the public gift feed). Excluded:
    # `last_caption` (speech transcript — err on PII), `favorites_in_room`
    # (operator-curated list, not on TikTok), `diamonds_vs_typical` /
    # `median_diamonds_30d` (derived from OUR internal 30d history,
    # surfaces a data point TikTok itself doesn't), `reconnects_1h`
    # (listener health, internal).
    _PUBLIC_SUMMARY_FIELDS = (
        "active_room_id",
        "live_started_at",
        "viewer_count",
        "viewer_history",
        "diamonds_session",
        "hourly_buckets",
        # Eight fields the React card never reads — removed in lockstep
        # with the admin bundle deny-list (see
        # `_BUNDLE_OMIT_SUMMARY_FIELDS` above). They were carried over
        # historically because the public sanitizer is a SAFE-by-default
        # allowlist, but allowlisting unused fields is just wire bloat:
        #   - daily_buckets         (rhythm strip — detail page only)
        #   - top_gifter            (single legacy, superseded by [])
        #   - comments_per_min_*    (no UI)
        #   - momentum_label        (no UI)
        #   - avg_*, n_rooms_30d    (30-day averages, not on the card)
        # Add any of them back here AND to the admin deny-list if a
        # public UI starts rendering them.
        "top_gifters",           # top 3, public on TikTok's gift leaderboard
        "n_unique_gifters",
        "n_first_time_gifters",
        "session_stats",         # all subkeys are session-level counters
        "last_gift_age_s",
        "last_comment_age_s",
        # `last_event_age_s` is intentionally omitted — TikTok shows
        # the live is on, but the internal "seconds since the last
        # webcast event we observed" signal is listener-health data
        # that the public has no business seeing.
        "n_envelopes_session",
        "envelope_diamonds_session",
        "n_pauses",
        "last_pause_age_s",
        "active_poll",
        "active_match",
        "last_broadcasts",
        "week_calendar",
    )

    # Public endpoint cache: 30s TTL per the contract. Distinct from the
    # 10s lives-summary cache — public viewers tolerate more staleness
    # than admin operators, and the page can fan out to N anonymous
    # tabs so the savings matter.
    _PUBLIC_LIVES_SUMMARY_TTL_S = 30.0
    _public_lives_summary_cache: tuple[float, dict[str, Any]] | None = None

    # Public-handle set: the lowercased `unique_id`s of every
    # subscription with `is_public=True`. Used by the public WS
    # endpoint to filter live events down to "things this anonymous
    # viewer is allowed to see". The set is cached for 30 s so an
    # operator flipping a host private takes effect within a poll
    # cycle without hammering the DB on every WS event (events can
    # fire 10s of times per second on a busy live).
    _PUBLIC_HANDLE_SET_TTL_S = 30.0
    _public_handle_set_cache: tuple[float, frozenset[str]] | None = None
    _public_handle_set_lock = threading.Lock()

    def get_public_handle_set(self) -> frozenset[str]:
        """Returns the set of lowercased handles flagged `is_public=True`.
        Cached 30 s + singleflight so heavy WS traffic doesn't fan
        out into per-event DB reads. Empty frozenset is a valid
        result (operator has no public subscriptions yet)."""
        now = time.monotonic()
        cached = self._public_handle_set_cache
        if cached is not None and (now - cached[0]) < self._PUBLIC_HANDLE_SET_TTL_S:
            return cached[1]
        with self._public_handle_set_lock:
            now2 = time.monotonic()
            cached2 = self._public_handle_set_cache
            if cached2 is not None and (now2 - cached2[0]) < self._PUBLIC_HANDLE_SET_TTL_S:
                return cached2[1]
            try:
                publics = self._persistence.list_public_subscriptions()
                handles = frozenset(
                    s.unique_id.lstrip("@").lower()
                    for s in publics
                    if s.unique_id
                )
            except Exception:
                logger.exception("get_public_handle_set: list_public_subscriptions failed")
                handles = frozenset()
            self._public_handle_set_cache = (now2, handles)
            return handles

    # BigInt-safe keys on the Subscription dataclass: room_id and
    # profile_user_id are 64-bit, exceed JS Number.MAX_SAFE_INTEGER —
    # stringify on the wire (the admin route does the same).
    _BIGINT_SUBSCRIPTION_KEYS = ("current_room_id",)

    def sanitize_public_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Phase 9B: filter a state-cache delta patch for publication
        on the public WS channel. Same allowlist + last_broadcasts
        slice the `/public/tiktok/lives` REST endpoint already
        applies, so subscribers and pollers see the same shape.

        Injected into the state-cache adapter at boot via
        `api_main._build_tiktok_state_cache`. The adapter applies
        this before publishing on `tiktok:lives:delta:public` —
        admin channel sees the raw delta. Operator-only fields never
        cross the public WS boundary."""
        allow = set(self._PUBLIC_SUMMARY_FIELDS)
        out: dict[str, Any] = {}
        for k, v in patch.items():
            if k in allow:
                if k == "last_broadcasts" and isinstance(v, list):
                    out[k] = v[:1]
                else:
                    out[k] = v
        return out

    @staticmethod
    def _pick(src: Any, allow: tuple[str, ...]) -> dict[str, Any]:
        """Return a fresh dict containing only allowlisted keys from
        `src` (a dict or a dataclass-like object). Build-by-copy on
        purpose: this fails CLOSED when upstream adds new fields, so
        we never accidentally leak a future operator-only column.

        Datetimes are isoformatted (dataclass fields are real datetime
        objects); 64-bit ids enumerated in `_BIGINT_SUBSCRIPTION_KEYS`
        are stringified so the JSON survives JS-side parsing.
        """
        if not src:
            return {}
        out: dict[str, Any] = {}
        is_mapping = isinstance(src, dict)
        for k in allow:
            v = src.get(k) if is_mapping else getattr(src, k, None)
            # iso-format datetimes (dataclass paths only — dict paths
            # come from get_lives_summary which already stringifies).
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            elif k in TikTokService._BIGINT_SUBSCRIPTION_KEYS and v is not None:
                v = str(v)
            out[k] = v
        return out

    def get_public_lives_summary(self) -> dict[str, Any]:
        """Sanitized public-lives payload for /public/tiktok/lives.

        Response shape:

            {"items": [
                {
                    "subscription": { ...allowlisted Subscription fields... },
                    "summary":      { ...allowlisted TikTokLiveSummary fields... },
                },
                ...
            ]}

        Mirrors the admin `(subscription, summary)` pair so the public
        home page can reuse the same card renderer as /admin/tiktok
        with admin actions stripped — same visual shape, sanitized
        payload. Build is by allowlist-copy, never drop-known-private:
        any new key upstream stays opaque by default until explicitly
        added to `_PUBLIC_SUBSCRIPTION_FIELDS` or `_PUBLIC_SUMMARY_FIELDS`.
        """
        now = time.monotonic()
        cached = self._public_lives_summary_cache
        if cached is not None and (now - cached[0]) < self._PUBLIC_LIVES_SUMMARY_TTL_S:
            return cached[1]

        # 1. Pull just the public-flagged subscriptions. Profile fields
        #    (nickname/avatar/follower_count/is_live/...) live on this
        #    row — get_lives_summary doesn't carry them.
        publics = self._persistence.list_public_subscriptions()
        handles = [s.unique_id for s in publics if s.unique_id]
        if not handles:
            result = {"items": []}
            self._public_lives_summary_cache = (now, result)
            return result

        # 2. Re-use the admin summary path — same SQL fan-out, shares
        #    the 10s TTL cache when admin + public callers overlap on
        #    the same handle set. Then sanitize each entry so nothing
        #    operator-only escapes.
        summary = self.get_lives_summary(handles)

        items: list[dict[str, Any]] = []
        for sub in publics:
            h = sub.unique_id
            if not h:
                continue
            row = summary.get(h.lstrip("@").lower(), {}) or {}
            summary_slice = self._pick(row, self._PUBLIC_SUMMARY_FIELDS)
            # Same trim as the admin bundle: `last_broadcasts` is a
            # 3-element history but the React card only reads index 0.
            # Slicing here mirrors the admin behaviour and shrinks the
            # public response symmetrically.
            if isinstance(summary_slice.get("last_broadcasts"), list):
                summary_slice["last_broadcasts"] = summary_slice["last_broadcasts"][:1]
            items.append(
                {
                    "subscription": self._pick(sub, self._PUBLIC_SUBSCRIPTION_FIELDS),
                    "summary":      summary_slice,
                }
            )

        result = {"items": items}
        self._public_lives_summary_cache = (now, result)
        return result

    # `get_lives_totals` is polled every 30 s by the /admin/tiktok
    # header strip. It's three unfiltered aggregates over
    # `tiktok_events` (24 h diamonds + 5 min events-per-min +
    # subscription count). Even with the `(type, ts)` index the
    # 24 h scan touches >100 k rows. A 15 s TTL cache cuts admin-tab
    # poll load roughly in half (each tab still sees fresh numbers
    # within a half-poll-cycle, and concurrent admin tabs collapse
    # to one DB round-trip per 15 s instead of one per tab per 30 s).
    # Same rationale as `_LIVES_SUMMARY_TTL_S` — 35 s buffer over the
    # 30 s frontend poll so steady-state polling always hits warm cache.
    _LIVES_TOTALS_TTL_S = 60.0  # see `_LIVES_SUMMARY_TTL_S` rationale
    _lives_totals_cache: tuple[float, dict[str, Any]] | None = None
    # Singleflight on cold miss — same rationale as `_lives_summary_cache`.
    # The cache has one slot (no per-key dimension), so one lock is enough.
    _lives_totals_lock = threading.Lock()

    def get_lives_totals(self) -> dict[str, Any]:
        now = time.monotonic()
        cached = self._lives_totals_cache
        if cached is not None and (now - cached[0]) < self._LIVES_TOTALS_TTL_S:
            return cached[1]

        with self._lives_totals_lock:
            now2 = time.monotonic()
            cached2 = self._lives_totals_cache
            if cached2 is not None and (now2 - cached2[0]) < self._LIVES_TOTALS_TTL_S:
                return cached2[1]
            result = self._persistence.get_lives_totals()
            self._lives_totals_cache = (now2, result)
            return result

    # Fields the `/admin/tiktok/lives/bundle` response intentionally
    # omits. Each is still computed inside `get_lives_summary` (cached
    # at the service layer, so dropping them saves no DB work) but
    # the React grid never reads them, so shipping them over the wire
    # is dead weight. On a 79-handle install this strips ~21 KB from
    # the 264 KB bundle payload (~8%).
    #
    # - daily_buckets:        24-int per-host hourly events; only the
    #                         rhythm strip in TikTokLiveDetail reads it.
    # - top_gifter:           single-gifter legacy field; superseded
    #                         by `top_gifters[]` everywhere.
    # - comments_per_min_*:   computed but no UI surfaces them.
    # - momentum_label:       heating/cooling label; not rendered on
    #                         the card.
    # - avg_*, n_rooms_30d:   30-day averages; not on the card grid.
    # - median_diamonds_30d:  only used server-side to compute
    #                         `diamonds_vs_typical`, which IS shipped.
    #
    # Don't add a field here without verifying the React grid doesn't
    # read it — `grep -rn summary?\.<name> frontend/src` is the check.
    _BUNDLE_OMIT_SUMMARY_FIELDS: tuple[str, ...] = (
        "daily_buckets",
        "top_gifter",
        "comments_per_min_recent",
        "comments_per_min_baseline",
        "momentum_label",
        "avg_duration_min",
        "avg_diamonds",
        "n_rooms_30d",
        "median_diamonds_30d",
    )

    async def get_lives_bundle(self) -> dict[str, Any]:
        """Single round-trip rollup for the /admin/tiktok Lives page.

        Returns `{"subs", "summary", "totals"}` — everything the page
        needs on first paint and on each 30 s poll. Consolidates what
        used to be three separate HTTP round-trips (and a duplicate
        `list_subscriptions()` call inside the old `/lives/summary`
        handler) into one.

        Wall-clock shape on a warm-cache hit (steady-state poll):
        `list_subscriptions` is a cheap single-query lookup (~5 ms);
        `get_lives_summary` + `get_lives_totals` race in `to_thread`
        and both hit warm 35 s TTL caches (~sub-ms). On a cold miss
        (first request after restart, or 35 s gap) the parallel
        `summary` query is the dominant cost.

        The handle list is computed ONCE here and threaded into
        `get_lives_summary`. The previous `/lives/summary` handler
        re-fetched the subscription list internally when called
        without `?handles=`, which doubled the DB work on every cold
        mount — that duplication is gone now.

        Each per-host summary slice is filtered through
        `_BUNDLE_OMIT_SUMMARY_FIELDS` so the wire payload doesn't carry
        fields the React grid never reads."""
        subs = await self.list_subscriptions()
        handles = [s["unique_id"] for s in subs if s.get("unique_id")]
        # Run the two heavy aggregations in parallel against the
        # connection pool. Each carries its own service-layer TTL +
        # singleflight lock so concurrent tabs / cold-miss races
        # collapse to one DB round-trip per cache window.
        summary, totals = await asyncio.gather(
            asyncio.to_thread(self.get_lives_summary, handles),
            asyncio.to_thread(self.get_lives_totals),
        )
        # Strip dead-weight fields from each per-host slice. Done as
        # a fresh dict so we don't mutate the cached summary (which
        # gets returned for 35 s by the singleflight cache).
        #
        # Plus: `last_broadcasts` is a list of up to 3 prior broadcasts
        # per host (~55 KB across 80 hosts), but the React card only
        # renders `last_broadcasts[0]` (the most recent). Slicing to
        # the first entry saves another ~35 KB per poll without changing
        # the wire shape — frontend code that does `last_broadcasts?.[0]`
        # still reads the same value.
        omit = self._BUNDLE_OMIT_SUMMARY_FIELDS
        trimmed: dict[str, dict[str, Any]] = {}
        for handle, slice_ in summary.items():
            entry: dict[str, Any] = {}
            for k, v in slice_.items():
                if k in omit:
                    continue
                if k == "last_broadcasts" and isinstance(v, list):
                    v = v[:1]
                entry[k] = v
            trimmed[handle] = entry
        return {"subs": subs, "summary": trimmed, "totals": totals}

    def insert_notification(
        self,
        *,
        type: str,
        title: str,
        body: str | None = None,
        host_unique_id: str | None = None,
        user_id: int | None = None,
        payload: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> int:
        return self._persistence.insert_notification(
            type=type, title=title, body=body,
            host_unique_id=host_unique_id, user_id=user_id,
            payload=payload, ts=ts,
        )

    def list_notifications(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        type: str | None = None,
        host_unique_id: str | None = None,
        unread_only: bool = False,
        include_cleared: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._persistence.list_notifications(
            since=since, until=until, type=type,
            host_unique_id=host_unique_id,
            unread_only=unread_only, include_cleared=include_cleared,
            limit=limit, offset=offset,
        )

    def count_unread_notifications(self) -> int:
        return self._persistence.count_unread_notifications()

    def mark_notification_read(self, notification_id: int, *, read: bool = True) -> bool:
        return self._persistence.mark_notification_read(int(notification_id), read=read)

    def mark_all_notifications_read(self) -> int:
        return self._persistence.mark_all_notifications_read()

    def clear_notification(self, notification_id: int) -> bool:
        return self._persistence.clear_notification(int(notification_id))

    def clear_all_notifications(self) -> int:
        return self._persistence.clear_all_notifications()

    # ── Favourite gifters ────────────────────────────────────────────
    #
    # In-memory cache of `user_id → notify-config` keeps the per-event
    # favourite check O(1) — typed dicts loaded once at boot, refreshed
    # whenever the favourites table mutates. Drives the always-on
    # notification persistence path: any time an event of an enabled
    # type hits a favourited gifter, we insert a `tiktok_notifications`
    # row so the operator sees it the next time they open the bell,
    # even if they were offline when it fired.

    def _hydrate_favorites_cache(self) -> None:
        rows = self._persistence.list_favorite_gifter_notify_config()
        cache: dict[int, dict[str, bool]] = {}
        for r in rows:
            try:
                uid = int(r["user_id"])
            except (TypeError, ValueError, KeyError):
                continue
            cache[uid] = {
                "gift":    bool(r.get("notify_gift",    True)),
                "comment": bool(r.get("notify_comment", False)),
                "join":    bool(r.get("notify_join",    False)),
            }
        self._favorites_cache = cache

    def _favorites_notify_for(self, user_id: int | None, type: str) -> bool:
        """Return True when `user_id` is a favourite AND they want to
        be notified for this event type. Cheap — single dict lookup."""
        if user_id is None:
            return False
        cfg = getattr(self, "_favorites_cache", None)
        if cfg is None:
            self._hydrate_favorites_cache()
            cfg = self._favorites_cache
        entry = cfg.get(int(user_id))
        if entry is None:
            return False
        return bool(entry.get(type, False))

    def add_favorite_gifter(
        self,
        user_id: int,
        note: str | None = None,
        *,
        notify_gift: bool | None = None,
        notify_comment: bool | None = None,
        notify_join: bool | None = None,
    ) -> None:
        self._persistence.add_favorite_gifter(
            int(user_id),
            note=note,
            notify_gift=notify_gift,
            notify_comment=notify_comment,
            notify_join=notify_join,
        )
        self._hydrate_favorites_cache()

    def remove_favorite_gifter(self, user_id: int) -> bool:
        ok = self._persistence.remove_favorite_gifter(int(user_id))
        self._hydrate_favorites_cache()
        return ok

    def is_favorite_gifter(self, user_id: int) -> bool:
        return self._persistence.is_favorite_gifter(int(user_id))

    def list_favorite_gifter_ids(self) -> list[str]:
        # Stringified for the wire — JS BigInt safety, same convention
        # as other user_id-bearing endpoints.
        return [str(uid) for uid in self._persistence.list_favorite_gifter_ids()]

    def list_favorite_gifter_notify_config(self) -> list[dict[str, Any]]:
        return [
            {**row, "user_id": str(row["user_id"])}
            for row in self._persistence.list_favorite_gifter_notify_config()
        ]

    def list_favorite_gifters(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        page = self._persistence.list_favorite_gifters_enriched(
            limit=limit, offset=offset, q=q,
        )
        items = [
            {**g, "user_id": str(g["user_id"]) if g.get("user_id") is not None else None}
            for g in page.get("items", [])
        ]
        return {
            "items": items,
            "total": int(page.get("total", 0)),
            "limit": int(limit),
            "offset": int(offset),
        }

    def get_common_gifters(
        self,
        *,
        min_hosts: int = 2,
        limit: int = 25,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        """Cross-creator gifter leaderboard. See persistence docstring."""
        items = self._persistence.common_gifters(
            min_hosts=min_hosts, limit=limit, offset=offset, q=q,
        )
        total = self._persistence.count_common_gifters(
            min_hosts=min_hosts, q=q,
        )
        # JS BigInt safety on the wire.
        items_serialized = [
            {**g, "user_id": str(g["user_id"]) if g.get("user_id") is not None else None}
            for g in items
        ]
        return {
            "items": items_serialized,
            "total": int(total),
            "limit": int(limit),
            "offset": int(offset),
            "min_hosts": int(min_hosts),
        }

    def get_cross_live_gifters_for_host(
        self,
        host_unique_id: str,
        *,
        min_other_hosts: int = 1,
        limit: int = 25,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        """Host-scoped variant of `get_common_gifters`: only viewers
        who gifted to this host AND to >= `min_other_hosts` other
        hosts. Same shape as `common_gifters` with extra here/elsewhere
        split. See persistence docstring."""
        items = self._persistence.cross_live_gifters_for_host(
            host_unique_id,
            min_other_hosts=min_other_hosts,
            limit=limit,
            offset=offset,
            q=q,
        )
        total = self._persistence.count_cross_live_gifters_for_host(
            host_unique_id,
            min_other_hosts=min_other_hosts,
            q=q,
        )
        items_serialized = [
            {**g, "user_id": str(g["user_id"]) if g.get("user_id") is not None else None}
            for g in items
        ]
        return {
            "items": items_serialized,
            "total": int(total),
            "limit": int(limit),
            "offset": int(offset),
            "min_other_hosts": int(min_other_hosts),
            "host": self._normalize(host_unique_id),
        }

    # ── internals ────────────────────────────────────────────────────

    @staticmethod
    def _normalize(handle: str) -> str:
        return handle.lstrip("@").strip()

    async def _start_session(self, unique_id: str) -> None:
        if self._passive:
            return  # worker handles session lifecycle
        async with self._lock:
            if unique_id in self._sessions:
                return  # already running
            session = self._session_factory.create(
                unique_id=unique_id,
                on_event=self._handle_event_for(unique_id),
                on_state_change=self._handle_state_change_for(unique_id),
                on_terminal_error=self._handle_terminal_error_for(unique_id),
            )
            self._sessions[unique_id] = session
        # Reset any stale terminal-error reason; a fresh session start
        # supersedes whatever the previous attempt failed with.
        self._handle_last_error.pop(unique_id, None)
        await session.start()
        self._log_worker("session_start", handle=unique_id)

    async def _stop_session(self, unique_id: str) -> None:
        if self._passive:
            return  # worker handles session lifecycle
        async with self._lock:
            session = self._sessions.pop(unique_id, None)
        if session is not None:
            # Close any active match the room was in — the connection drop
            # is an implicit battle end from our perspective.
            room_id = session.room_id
            if room_id is not None:
                info = self._active_match.pop(int(room_id), None)
                if info:
                    try:
                        self._persistence.close_match(info["match_id"])
                    except Exception:
                        logger.exception(
                            "close_match on stop failed for match=%s", info["match_id"]
                        )
            await session.stop()
            self._states[unique_id] = SubscriptionState.DISCONNECTED.value
            self._log_worker("session_stop", handle=unique_id)

    def _handle_event_for(self, unique_id: str):
        async def cb(*, type: str, payload: dict, room_id: int | None) -> None:
            await self._on_event(unique_id, type=type, payload=payload, room_id=room_id)
        return cb

    def _handle_state_change_for(self, unique_id: str):
        """State-change callback for the TikTokLive session.

        Beyond updating `_states`, this callback also tracks the local-
        offline timestamp used by Stage-1 of the stuck-slot defense
        (see `LOCAL_OFFLINE_RELEASE_S`). When state transitions INTO an
        offline-equivalent state (DISCONNECTED / LIVE_ENDED / ERROR /
        DISABLED), stamp `_local_offline_since[handle]` with the
        current epoch. When it transitions BACK to CONNECTED, clear
        the stamp — we don't release a slot that's reconnected. The
        reconcile loop reads this stamp + threshold to release slots
        whose WS is provably dead, regardless of probe state."""
        async def cb(state: str) -> None:
            prev = self._states.get(unique_id)
            self._states[unique_id] = state
            offline_states = {
                SubscriptionState.DISCONNECTED.value,
                SubscriptionState.LIVE_ENDED.value,
                SubscriptionState.ERROR.value,
                SubscriptionState.DISABLED.value,
            }
            if state in offline_states:
                # Only stamp on TRANSITION into offline — repeated
                # callbacks with the same offline state shouldn't reset
                # the clock (would let a flap delay the release forever).
                if prev not in offline_states:
                    self._local_offline_since[unique_id] = time.time()
            elif state == SubscriptionState.CONNECTED.value:
                self._local_offline_since.pop(unique_id, None)
        return cb

    def _handle_terminal_error_for(self, unique_id: str):
        """Stash the most recent terminal-connect error reason so the
        listener-status snapshot exposes it (UI shows "Age-restricted
        stream" instead of bare ERROR), and write a worker_log row for
        the audit trail."""
        async def cb(kind: str, message: str) -> None:
            self._handle_last_error[unique_id] = {
                "kind": kind,
                "message": message,
                "at": time.time(),
            }
            self._log_worker(
                "session_terminal",
                level="error",
                handle=unique_id,
                detail={"kind": kind, "message": message},
            )
        return cb

    async def _on_event(
        self,
        unique_id: str,
        *,
        type: str,
        payload: dict,
        room_id: int | None,
    ) -> None:
        # Per-handle counters (used by the listener-status snapshot for
        # "events_total" + "last event Xs ago" without hitting the DB).
        self._handle_event_count[unique_id] = self._handle_event_count.get(unique_id, 0) + 1
        self._handle_last_event_at[unique_id] = time.time()

        # 1. Persist via the dedicated event executor. The asyncio loop
        # stays free for periodic tasks (heartbeat, reconcile, etc.).
        # We use a private executor (not the default) so a saturated
        # event pool can't queue up behind / starve the control plane.
        try:
            loop = asyncio.get_running_loop()
            # Cache the loop the first time we see it so executor
            # threads (which run `_persist_event` → `schedule_opponent_
            # profile_fetches`) can dispatch background tasks back to
            # the loop via `run_coroutine_threadsafe` instead of
            # silently dropping coroutines.
            if self._loop is None:
                self._loop = loop
            await loop.run_in_executor(
                self._event_executor,
                self._persist_event_threadsafe,
                unique_id, type, payload, room_id,
            )
        except Exception as e:
            logger.exception(
                "Persist failed for @%s type=%s room=%r (%s: %s) — event broadcast still proceeds",
                unique_id, type, room_id, e.__class__.__name__, e,
            )

        # 2. Broadcast to listeners. room_id stringified for JS BigInt safety.
        # Pull `user_id` to the envelope's top level so WS consumers
        # (favourite-gifter watcher, recent-events tail, etc.) can
        # filter without digging through `payload.user`. The actor-id
        # convention matches `TikTokEventModel.user_id` — the gifter /
        # commenter / joiner — not the host.
        actor_user_id: int | None = None
        if isinstance(payload, dict):
            user_blob = payload.get("user")
            if isinstance(user_blob, dict):
                raw_uid = user_blob.get("user_id") or user_blob.get("id")
                if raw_uid is not None:
                    try:
                        actor_user_id = int(raw_uid)
                    except (TypeError, ValueError):
                        actor_user_id = None
        envelope = {
            "type": type,
            "unique_id": unique_id,
            "room_id": str(room_id) if room_id else None,
            "user_id": str(actor_user_id) if actor_user_id else None,
            "payload": payload,
        }
        if self._listeners:
            for listener in list(self._listeners):
                try:
                    await listener(envelope)
                except Exception:
                    logger.exception("WS listener raised for @%s type=%s", unique_id, type)

    def _should_push_seen(self, key: str) -> bool:
        """True at most once every LAST_SEEN_THROTTLE_SECONDS for a given key.
        First call for any key returns True."""
        import time as _time
        now = _time.monotonic()
        last = self._last_seen_pushed.get(key)
        if last is None or (now - last) >= self._LAST_SEEN_THROTTLE_SECONDS:
            self._last_seen_pushed[key] = now
            # Periodic eviction so the dict doesn't grow without bound.
            if len(self._last_seen_pushed) > 10_000:
                cutoff = now - self._LAST_SEEN_THROTTLE_SECONDS * 4
                self._last_seen_pushed = {
                    k: v for k, v in self._last_seen_pushed.items() if v >= cutoff
                }
            return True
        return False

    def _persist_event_threadsafe(
        self,
        unique_id: str,
        type_: str,
        payload: dict,
        room_id: int | None,
    ) -> None:
        """Positional-args adapter for `loop.run_in_executor` (which can't
        forward kwargs without functools.partial). Plain wrapper around
        `_persist_event`."""
        self._persist_event(
            unique_id, type=type_, payload=payload, room_id=room_id,
        )

    def _persist_event(
        self,
        unique_id: str,
        *,
        type: str,
        payload: dict,
        room_id: int | None,
    ) -> None:
        # Coerce room_id — TikTokLive may hand us strings on some
        # event paths. Skip pre-connect synthetic events with no room.
        if room_id in (None, 0, "", "0"):
            logger.debug("Skipping persist for @%s type=%s: no room_id", unique_id, type)
            return
        try:
            room_id_int = int(room_id)
        except (TypeError, ValueError):
            logger.warning(
                "Skipping persist for @%s type=%s: bad room_id %r",
                unique_id, type, room_id,
            )
            return

        # Build viewer record from payload.user when present.
        user_payload = payload.get("user") if isinstance(payload, dict) else None
        viewer: TikTokViewer | None = None
        if user_payload and isinstance(user_payload, dict):
            uid = user_payload.get("user_id")
            if uid:
                try:
                    viewer = TikTokViewer(
                        user_id=int(uid),
                        unique_id=user_payload.get("unique_id"),
                        nickname=user_payload.get("nickname"),
                        avatar_url=user_payload.get("avatar_url"),
                    )
                except (TypeError, ValueError):
                    viewer = None

        # Catalog upsert for gifts (separate session — runs rarely).
        if type == "gift":
            self._upsert_gift_from_payload(payload)

        # Match-state transitions: open / refresh / close per battle_id.
        if type in ("match_start", "match_update", "match_end"):
            self._handle_match_event(room_id_int, type, payload)
        elif type in ("live_end", "disconnected"):
            info = self._active_match.pop(room_id_int, None)
            if info:
                try:
                    self._persistence.close_match(info["match_id"])
                except Exception:
                    logger.exception(
                        "close_match on %s failed for match=%s", type, info["match_id"]
                    )

        match_id = self._current_match_id(room_id_int)

        # Throttle last_seen_at writes per (room) and per (viewer). The
        # canonical event row goes in regardless — it's the housekeeping
        # column updates we're avoiding per high-traffic event.
        push_room_seen = self._should_push_seen(f"room:{room_id_int}")
        push_viewer_seen = (
            self._should_push_seen(f"viewer:{viewer.user_id}") if viewer else False
        )

        # One transaction = one session checkout = 1× pool pressure.
        # Returns 0 when the row was deduplicated by the (room_id,
        # message_id) partial unique index — i.e. TikTok re-delivered an
        # event we already had (typical WS-reconnect cursor replay).
        # Surface the count per-handle so the listener-status snapshot
        # exposes a "dedup_dropped" metric the user can monitor.
        row_id = self._persistence.persist_event_full(
            room_id=room_id_int,
            host_unique_id=unique_id,
            viewer=viewer,
            type=type,
            payload=payload,
            match_id=match_id,
            push_room_seen=push_room_seen,
            push_viewer_seen=push_viewer_seen,
        )
        if row_id == 0:
            self._handle_dedup_dropped[unique_id] = (
                self._handle_dedup_dropped.get(unique_id, 0) + 1
            )
            # Skip notification persistence for dedup-dropped rows
            # (TikTok re-delivered an event we already persisted on a
            # prior WS reconnect — it'd be a duplicate notification).
            return

        # Favourite-gifter notification persistence. Always-on path:
        # the worker writes the notification row regardless of whether
        # any browser tab is currently watching the WebSocket. This is
        # what makes "history" honest — close the laptop for an hour,
        # come back, every favourite event during that hour is in the
        # bell drawer.
        if (
            type in ("gift", "comment", "join")
            and viewer is not None
            and self._favorites_notify_for(viewer.user_id, type)
        ):
            try:
                title, body = _favorite_notification_text(type, viewer, payload)
                self._persistence.insert_notification(
                    type=type,
                    title=title,
                    body=body,
                    host_unique_id=unique_id,
                    user_id=viewer.user_id,
                    payload=payload,
                )
            except Exception as e:
                logger.warning(
                    "Failed to persist favourite notification (@%s, type=%s, uid=%s): %s",
                    unique_id, type, viewer.user_id, e,
                )

    def _current_match_id(self, room_id: int) -> int | None:
        info = self._active_match.get(room_id)
        return info["match_id"] if info else None

    def _handle_match_event(self, room_id: int, type: str, payload: dict) -> None:
        battle_id = _safe_int(payload.get("battle_id")) if isinstance(payload, dict) else None
        settings = _settings_from_payload(payload)

        if type == "match_start":
            if not battle_id:
                return
            try:
                m = self._persistence.open_match(
                    room_id=room_id,
                    battle_id=battle_id,
                    opponents=payload.get("opponents") or [],
                    scores=payload.get("scores") or {},
                    settings=settings or None,
                )
                if m.id is not None:
                    # Close any prior active match for the room first
                    # (different battle_id arriving without an explicit end).
                    prev = self._active_match.get(room_id)
                    if prev and prev["match_id"] != m.id:
                        try:
                            self._persistence.close_match(prev["match_id"])
                        except Exception:
                            logger.exception("Closing stale match failed for room %s", room_id)
                    self._active_match[room_id] = {
                        "match_id": m.id,
                        "battle_id": battle_id,
                    }
                    # Fire a background task to fill in any missing
                    # opponent avatars/nicknames via the profile scraper.
                    self.schedule_opponent_profile_fetches(m.id)
            except Exception:
                logger.exception("open_match failed for room=%s battle=%s", room_id, battle_id)
            return

        if type == "match_update":
            info = self._active_match.get(room_id)
            if not info:
                # Battle started before we connected — open a synthetic row.
                if battle_id:
                    try:
                        m = self._persistence.open_match(
                            room_id=room_id,
                            battle_id=battle_id,
                            scores=payload.get("scores") or {},
                            settings=settings or None,
                        )
                        if m.id is not None:
                            self._active_match[room_id] = {
                                "match_id": m.id,
                                "battle_id": battle_id,
                            }
                            info = self._active_match[room_id]
                    except Exception:
                        logger.exception(
                            "open_match (mid-battle) failed for room=%s battle=%s",
                            room_id, battle_id,
                        )
                        return
                else:
                    return
            try:
                self._persistence.update_match(
                    info["match_id"],
                    scores=payload.get("scores") or None,
                    opponent_scores=payload.get("opponent_scores") or None,
                    settings=settings or None,
                )
            except Exception:
                logger.exception("update_match failed for match=%s", info.get("match_id"))
            return

        if type == "match_end":
            info = self._active_match.pop(room_id, None)
            if info:
                try:
                    self._persistence.close_match(info["match_id"])
                except Exception:
                    logger.exception("close_match failed for match=%s", info["match_id"])
            return

    def _upsert_gift_from_payload(self, payload: dict) -> None:
        gift_id = payload.get("gift_id") if isinstance(payload, dict) else None
        if not gift_id:
            return
        try:
            gid = int(gift_id)
        except (TypeError, ValueError):
            return
        try:
            self._persistence.upsert_gift(
                TikTokGift(
                    gift_id=gid,
                    name=payload.get("gift_name"),
                    diamond_count=_safe_int(payload.get("diamond_count")),
                    icon_url=payload.get("gift_icon_url"),
                    streakable=payload.get("streakable"),
                )
            )
        except Exception:
            logger.exception("Gift catalog upsert failed for gift_id=%s", gid)

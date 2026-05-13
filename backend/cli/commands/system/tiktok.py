"""TikTok-listener worker CLI.

When run, this process:
  1. Initializes Redis (for event fan-out) + the database engine.
  2. Builds the TikTokService with the persistence + live-client adapters
     and a Redis-publishing listener.
  3. Calls `start_all_enabled()` to spin up one supervisor task per
     enabled subscription.
  4. Polls the `tiktok_subscriptions` table every N seconds and
     reconciles its in-memory listener pool with DB state (handles
     creation / deletion / enable / disable).
  5. Runs until SIGINT/SIGTERM, then closes everything cleanly.

The API process should be configured with
  `PHOVEU_BACKEND_TIKTOK_LISTENER_MODE=worker`
so it skips its own in-process listener pool and instead subscribes to
the Redis fan-out for WebSocket clients.

Usage:
    python cli.py system tiktok run-listener
    python cli.py system tiktok run-listener --reconcile-seconds 10
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Optional

import click


logger = logging.getLogger(__name__)


@click.group(name="tiktok")
def tiktok_group():
    """TikTok-bot worker commands."""


@tiktok_group.command(name="run-listener")
@click.option(
    "--reconcile-seconds",
    type=int,
    default=10,
    show_default=True,
    help="How often to poll tiktok_subscriptions for new/removed handles.",
)
@click.option(
    "--reload",
    "reload",
    is_flag=True,
    default=False,
    help=(
        "Watch backend Python files and restart the worker on change. "
        "Wraps the actual worker in a supervisor process, so the listener "
        "always picks up new code without manual restarts."
    ),
)
def run_listener(reconcile_seconds: int, reload: bool) -> None:
    """Run the TikTokLive listener pool as a standalone worker."""
    if reload:
        _supervisor_main(reconcile_seconds=reconcile_seconds)
    else:
        asyncio.run(_main(reconcile_seconds=reconcile_seconds))


@tiktok_group.command(name="lookup")
@click.argument("handle")
def lookup_cmd(handle: str) -> None:
    """Probe a TikTok @handle (profile + live status) without subscribing.

    Prints the same data the "Add Live" modal shows: nickname, avatar,
    follower count, live state, etc.
    """
    asyncio.run(_lookup(handle))


@tiktok_group.command(name="list-lives")
def list_lives_cmd() -> None:
    """Print every subscription with cached profile data."""
    asyncio.run(_list_lives())


@tiktok_group.command(name="debug")
@click.argument("handle")
@click.option(
    "--seconds",
    "seconds",
    type=int,
    default=20,
    show_default=True,
    help="How long to listen on the WebSocket if it connects.",
)
@click.option(
    "--max-events",
    "max_events",
    type=int,
    default=30,
    show_default=True,
    help="Stop early after this many events.",
)
@click.option(
    "--no-ws",
    "no_ws",
    is_flag=True,
    default=False,
    help="Skip the WebSocket connect — only probe profile + DB state.",
)
def debug_cmd(handle: str, seconds: int, max_events: int, no_ws: bool) -> None:
    """End-to-end debug for one @handle: profile probe → DB state →
    WebSocket connect → live event capture. Surfaces every layer of the
    pipeline so we can see exactly where ingestion is breaking (e.g.
    AgeRestrictedError, WAF on the profile probe, stale subscription
    cache, etc.) without grepping logs.

    Examples:
        python cli.py system tiktok debug prismanova
        python cli.py system tiktok debug @luzy.pe --seconds 60 --max-events 100
        python cli.py system tiktok debug tonoabril__ --no-ws
    """
    # Capture stderr around the whole run. The TikTokLive lib spawns
    # several internal tasks (DNS resolves, ws receivers, sign client) —
    # at process teardown asyncio reports their cancellation as
    # "Task exception was never retrieved" tracebacks. They're cosmetic
    # noise (the cancellation IS expected: we asked the client to
    # disconnect). We swallow the noise but re-print only the lines
    # that aren't part of a CancelledError traceback so real failures
    # (sign errors, network errors, etc.) still reach the user.
    import io
    captured_stderr = io.StringIO()
    real_stderr = sys.stderr
    try:
        sys.stderr = _StderrFilter(captured_stderr, real_stderr)
        asyncio.run(_debug(handle, seconds=seconds, max_events=max_events, no_ws=no_ws))
    finally:
        sys.stderr = real_stderr


class _StderrFilter:
    """Pass stderr writes through to the real stderr unless they look
    like asyncio's "Task exception was never retrieved" CancelledError
    tracebacks from lib teardown — those we silently drop. Anything
    else (genuine errors, log lines) reaches the terminal as usual."""

    _DROP_TRIGGER = "Task exception was never retrieved"
    _DROP_END = "asyncio.exceptions.CancelledError"

    def __init__(self, _buf, real):
        self._real = real
        self._dropping = False

    def write(self, s: str) -> int:
        if self._dropping:
            if self._DROP_END in s:
                self._dropping = False
            return len(s)
        if self._DROP_TRIGGER in s:
            self._dropping = self._DROP_END not in s
            return len(s)
        return self._real.write(s)

    def flush(self) -> None:
        try:
            self._real.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._real, name)


@tiktok_group.command(name="refresh-profiles")
@click.option(
    "--handle",
    "-h",
    "handle",
    help="Refresh just this @handle (default: refresh everything stale).",
)
@click.option(
    "--all",
    "force_all",
    is_flag=True,
    help="Refresh every subscription regardless of staleness.",
)
def refresh_profiles_cmd(handle: str | None, force_all: bool) -> None:
    """Refresh cached public-profile data (avatar, nickname, follower count, …)."""
    asyncio.run(_refresh_profiles(handle=handle, force_all=force_all))


# ── implementation ──────────────────────────────────────────────────


def _supervisor_main(*, reconcile_seconds: int) -> None:
    """Watch backend `.py` files and restart the child worker on change.

    Architecture: this function is the *parent* (supervisor). It spawns
    the actual worker as a subprocess and polls file mtimes once per
    second. On change → SIGTERM the child, wait for graceful exit,
    respawn. On Ctrl-C → SIGTERM the child, return.

    No external deps (no `watchfiles`, no `watchdog`) — just stdlib
    polling. The latency is up to ~1 second between save and restart,
    which is fine for backend code.
    """
    import subprocess
    import sys
    import time as _time

    # Roots to watch. Anything `.py` under these directories triggers a
    # restart. We deliberately *don't* watch `frontend/` or test files.
    WATCH_ROOTS = ["domain", "adapters", "ports", "cli", "config.py", "api_main.py"]
    POLL_SECONDS = 1.0
    GRACEFUL_SHUTDOWN_TIMEOUT = 10.0

    def collect_mtimes() -> dict[str, float]:
        out: dict[str, float] = {}
        for root in WATCH_ROOTS:
            if os.path.isfile(root):
                try:
                    out[root] = os.path.getmtime(root)
                except OSError:
                    pass
                continue
            if not os.path.isdir(root):
                continue
            for dp, _dn, fn in os.walk(root):
                # Skip __pycache__ and .venv if present.
                if "__pycache__" in dp or "/.venv" in dp:
                    continue
                for f in fn:
                    if not f.endswith(".py"):
                        continue
                    p = os.path.join(dp, f)
                    try:
                        out[p] = os.path.getmtime(p)
                    except OSError:
                        pass
        return out

    # Strip `--reload` so the child runs the actual worker, not another
    # supervisor.
    child_argv = [sys.executable] + [a for a in sys.argv if a != "--reload"]

    print(f"[reload] Supervisor pid={os.getpid()} watching {len(WATCH_ROOTS)} roots.")
    print(f"[reload] Worker command: {' '.join(child_argv)}")

    proc: subprocess.Popen | None = None

    def kill_child(sig: int = 15) -> None:
        nonlocal proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.send_signal(sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=GRACEFUL_SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            print(
                f"[reload] Child pid={proc.pid} didn't exit in "
                f"{GRACEFUL_SHUTDOWN_TIMEOUT}s — SIGKILL."
            )
            proc.kill()
            proc.wait()

    try:
        while True:
            baseline = collect_mtimes()
            proc = subprocess.Popen(child_argv)
            print(f"[reload] Spawned worker pid={proc.pid}.")

            # Inner loop: poll for either exit or a file change.
            restart = False
            while True:
                ret = proc.poll()
                if ret is not None:
                    if ret == 0:
                        print("[reload] Worker exited cleanly. Supervisor stopping.")
                        return
                    print(f"[reload] Worker died with code {ret}. Restart in 2s.")
                    _time.sleep(2.0)
                    break  # respawn
                current = collect_mtimes()
                changed = [
                    p for p, m in current.items() if baseline.get(p) != m
                ]
                # Also flag *new* files (in baseline=missing, current=present)
                # and *deleted* files (vice versa).
                changed += [p for p in baseline if p not in current]
                if changed:
                    sample = changed[:3]
                    suffix = " …" if len(changed) > 3 else ""
                    print(f"[reload] {len(changed)} file(s) changed: {sample}{suffix}")
                    print(f"[reload] Restarting worker pid={proc.pid}…")
                    kill_child(15)
                    restart = True
                    break
                _time.sleep(POLL_SECONDS)
            if not restart:
                # Crash path — already slept 2s above.
                continue
    except KeyboardInterrupt:
        print("\n[reload] Ctrl-C — stopping worker.")
        kill_child(15)


async def _main(*, reconcile_seconds: int) -> None:
    # Set up logging before anything else so init failures are visible.
    _configure_logging()

    # The framework's structured logger drops asyncio's default
    # `exception` payload, so unhandled exceptions in pyee event
    # callbacks show up as a single "Exception in callback ..." line
    # with no traceback. Install our own handler that prints the full
    # traceback to stderr — essential for debugging silent breakage
    # (e.g., a TikTokLive proto field rename that makes one event
    # type's handler explode while every other event still flows).
    import traceback as _tb
    def _asyncio_exc_handler(loop, context: dict) -> None:
        exc = context.get("exception")
        if exc is not None:
            tb = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
            sys.stderr.write(f"[asyncio uncaught] {context.get('message','')}\n{tb}\n")
        else:
            sys.stderr.write(f"[asyncio uncaught] {context.get('message','')}\n")
    asyncio.get_running_loop().set_exception_handler(_asyncio_exc_handler)

    logger.info("Starting TikTok listener worker (reconcile=%ds)", reconcile_seconds)

    from adapters.persistence.tiktok_persistence import TikTokPersistenceAdapter
    from adapters.tiktok_event_bus import EventPublisher
    # HeartbeatWriter (file-based) removed — DB row is the only signal.
    from adapters.tiktok_live_client import TikTokLiveSessionFactory
    from domain.services.tiktok_service import TikTokService
    from utils.redis_client import init_redis, close_redis

    # 1. Redis for fan-out (optional but expected).
    await init_redis()

    # Phase 9B: state-cache wiring. When the WS state-push flag is on,
    # the worker is the sole writer to the per-host state cache —
    # `_apply_state_delta` runs inline in `record_event()` here, and the
    # API workers in worker mode are passive (no listener of their own,
    # no writes to the cache). Redis-backed for cross-process sharing.
    _ws_state_push = os.getenv(
        "PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH", "off",
    ).strip().lower()
    state_cache = None
    if _ws_state_push in ("shadow", "on"):
        try:
            import redis as _redis
            from adapters.tiktok_state_cache_redis import TikTokStateCacheRedis
            from utils.redis_client import get_redis
            from config import CONFIG
            url = CONFIG.get("REDIS_URL") or ""
            if not url:
                logger.warning(
                    "ws_state_push=%s but PHOVEU_REDIS_SERVER is empty — "
                    "state cache disabled in this worker. The API and "
                    "this worker won't share state. Set REDIS_URL or "
                    "set ws_state_push=off.", _ws_state_push,
                )
            else:
                state_cache = TikTokStateCacheRedis(
                    sync_client=_redis.from_url(url, decode_responses=False),
                    async_client_getter=get_redis,
                    public_sanitizer=None,  # wired post-service below
                )
                logger.info(
                    "✅ TikTok state cache (Redis) wired in worker (ws_state_push=%s)",
                    _ws_state_push,
                )
        except Exception:
            logger.exception(
                "Failed to wire state cache in worker — falling through "
                "with state cache disabled.",
            )

    # 2. Persistence + service.
    persistence = TikTokPersistenceAdapter(auto_init=True, state_cache=state_cache)
    factory = TikTokLiveSessionFactory()
    service = TikTokService(persistence=persistence, session_factory=factory)

    # Wire the public sanitizer now that the service exists.
    if state_cache is not None:
        state_cache._public_sanitizer = service.sanitize_public_patch

    # 3. Wire the Redis-publishing listener.
    publisher = EventPublisher()
    service.add_listener(publisher)

    # 4. Boot existing enabled subscriptions.
    try:
        await service.start_all_enabled()
    except Exception as e:
        # WorkerKeyConflictError = another live worker holds our
        # worker_key. Anything else here is also fatal — we can't
        # safely run the listener pool, and continuing would dual-
        # ingest. Exit cleanly so the supervisor respawns and keeps
        # failing until the conflict is resolved.
        cls = e.__class__.__name__
        logger.error("Worker cannot start the listener pool (%s): %s", cls, e)
        try:
            await close_redis()
        except Exception:
            pass
        sys.exit(2)

    # 5. Reconciler + signal handling. The control signals here let the
    # API trigger pause/resume/kill on this process without RPC plumbing.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_pause() -> None:
        # `pause_all` is async — schedule it. fire-and-forget; it's a
        # short coroutine and we'd rather drop the trailing exception
        # log than deadlock on the loop.
        asyncio.create_task(service.pause_all(), name="ctrl-pause")

    def _on_resume() -> None:
        asyncio.create_task(service.resume_all(), name="ctrl-resume")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows: signal handlers via asyncio aren't supported.
            pass
    # SIGUSR1 = pause, SIGUSR2 = resume. POSIX-only.
    for sig, handler in ((signal.SIGUSR1, _on_pause), (signal.SIGUSR2, _on_resume)):
        try:
            loop.add_signal_handler(sig, handler)
        except (NotImplementedError, AttributeError):
            pass

    # 6. Heartbeat: every 5s, stamp a status snapshot to Redis (TTL 15s)
    # DB heartbeat — periodic UPDATE on tiktok_workers. Runs on the
    # asyncio loop; the sync UPDATE is dispatched to a thread executor
    # so a slow DB roundtrip doesn't block other tasks.
    # File heartbeat is GONE — DB row is the single source of truth.
    db_heartbeat_task = asyncio.create_task(
        _db_heartbeat_loop(service, stop, period=5),
        name="tiktok-db-heartbeat",
    )

    # Watch for service.stop_requested (set by check_db_orders when the
    # admin sets desired_status='stopped' or command='kill') and trip
    # the outer stop event so the worker exits cleanly.
    stop_watcher_task = asyncio.create_task(
        _db_stop_watcher(service, stop),
        name="tiktok-db-stop-watcher",
    )

    reconcile_task = asyncio.create_task(_reconcile_loop(service, stop, reconcile_seconds))

    # Phase 9B: state-cache tick task. Only started when the worker
    # owns a state cache (ws_state_push=shadow|on). In in_process mode
    # this same loop runs from `api_main.py:lifespan` instead — the
    # boot logic ensures exactly one tick task per state-cache backing.
    tick_task: asyncio.Task | None = None
    if state_cache is not None:
        from adapters.tiktok_state_ticker import run_state_tick_loop
        tick_task = asyncio.create_task(
            run_state_tick_loop(state_cache, stop_event=stop),
            name="tiktok-state-tick",
        )

    logger.info("Worker ready (pid=%d). Waiting for events / SIGINT.", os.getpid())
    try:
        await stop.wait()
    finally:
        logger.info("Shutting down listener pool...")
        _tasks_to_cancel = [reconcile_task, db_heartbeat_task, stop_watcher_task]
        if tick_task is not None:
            _tasks_to_cancel.append(tick_task)
        for t in _tasks_to_cancel:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        await service.stop_all()
        await close_redis()
        logger.info("Worker stopped.")


async def _db_stop_watcher(service, stop: asyncio.Event, *, period: float = 1.0) -> None:
    """Watch `service.stop_requested` (flipped by check_db_orders when
    admin sets desired_status='stopped' / command='kill'). When set,
    trip the outer `stop` event so the worker exits cleanly."""
    while not stop.is_set():
        if service.stop_requested:
            logger.info("Stop requested via DB — exiting.")
            stop.set()
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=period)
        except asyncio.TimeoutError:
            continue


async def _db_heartbeat_loop(service, stop: asyncio.Event, *, period: int = 5) -> None:
    """Periodically write the worker's listener-status snapshot into
    `tiktok_workers` (DB registry).

    Snapshot is built on the asyncio LOOP (where `_states` / `_sessions`
    are mutated — safe) and only the DB UPDATE is dispatched to a thread
    executor (so a slow DB roundtrip doesn't block the loop). 10 s
    `wait_for` so one stuck call can't prevent the next tick.

    File heartbeat (in its own thread) handles the "is this worker
    alive on disk" question independently — both signals are written
    so the API status endpoint can fall back to the file when the DB
    is unreachable.
    """
    loop = asyncio.get_running_loop()
    tick = 0
    while not stop.is_set():
        tick += 1
        logger.info("[hb] tick %d: building snapshot", tick)
        try:
            snap = service.get_listener_status_local()
            logger.info(
                "[hb] tick %d: snapshot built (sessions=%d)",
                tick, snap.get("active_session_count", -1),
            )
        except Exception:
            logger.exception("[hb] tick %d: snapshot build failed", tick)
            snap = None
        if snap is not None:
            logger.info("[hb] tick %d: submitting UPDATE to control executor", tick)
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(
                        service._control_executor,  # type: ignore[attr-defined]
                        service.write_heartbeat_to_db,
                        snap,
                    ),
                    timeout=period * 2,
                )
                logger.info("[hb] tick %d: UPDATE done", tick)
            except asyncio.TimeoutError:
                logger.warning(
                    "[hb] tick %d: UPDATE timed out after %ds — control "
                    "executor likely backed up. Heartbeat row stale.",
                    tick, period * 2,
                )
            except Exception:
                logger.exception("[hb] tick %d: UPDATE raised", tick)
        try:
            await asyncio.wait_for(stop.wait(), timeout=period)
        except asyncio.TimeoutError:
            continue


async def _reconcile_loop(service, stop: asyncio.Event, period: int) -> None:
    """Reconcile loop for the multi-worker registry.

    Each tick:
      - Reap stale workers (their leases get released).
      - Extend leases on handles we hold; drop any we lost.
      - Stop sessions for disabled / deleted subscriptions.
      - Claim more handles up to capacity.

    All of this is delegated to `service.reconcile_assignments()` —
    this loop is just the timer + crash log.
    """
    while not stop.is_set():
        try:
            # Best-effort stale-reaper. Cheap (one DB query); fine to
            # run on every tick from every worker.
            try:
                service._persistence.reap_stale_workers(stale_after_seconds=30)
            except Exception:
                logger.exception("reap_stale_workers failed; continuing.")
            # Honor admin orders FIRST so a paused/stopped state is
            # visible before we extend leases or claim new handles.
            try:
                await service.check_db_orders()
            except Exception:
                logger.exception("check_db_orders failed; continuing.")
            result = await service.reconcile_assignments()
            if result.get("claimed") or result.get("lost"):
                logger.info(
                    "Reconcile: claimed=%s lost=%s held=%d",
                    result.get("claimed") or "[]",
                    result.get("lost") or "[]",
                    result.get("held") or 0,
                )
        except Exception:
            logger.exception("Reconcile pass failed; will retry.")
        try:
            await asyncio.wait_for(stop.wait(), timeout=period)
        except asyncio.TimeoutError:
            continue


async def _lookup(handle: str) -> None:
    """Print a single-handle preview (the same data the Add modal shows)."""
    _configure_logging()
    from adapters.persistence.tiktok_persistence import TikTokPersistenceAdapter
    from adapters.tiktok_live_client import TikTokLiveSessionFactory
    from domain.services.tiktok_service import TikTokService

    svc = TikTokService(
        persistence=TikTokPersistenceAdapter(auto_init=True),
        session_factory=TikTokLiveSessionFactory(),
    )
    data = await svc.lookup_handle(handle)
    _print_kv(data, title=f"@{data.get('handle') or handle}")


async def _debug(
    handle: str,
    *,
    seconds: int,
    max_events: int,
    no_ws: bool,
) -> None:
    """End-to-end pipeline debug. Five sections, each printed before the
    next runs so SIGINT mid-test still leaves you with the earlier
    layers' diagnostics."""
    _configure_logging()
    # Quiet down most lib logging — we want our own structured output.
    logging.getLogger().setLevel(logging.WARNING)

    # Silence asyncio's "Task exception was never retrieved" tracebacks
    # from TikTokLive's internal teardown (DNS resolves cancelled mid-
    # flight, etc.). These are cosmetic — we ASKED the client to
    # disconnect — but asyncio routes them through `logging.error` on
    # the `asyncio` logger, which our default handler dumps to stderr.
    # Filter them out by attaching a logging filter to that logger.
    class _DropCancelledTaskTraceback(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            if "Task exception was never retrieved" in msg:
                return False
            if record.exc_info and record.exc_info[0] is asyncio.CancelledError:
                return False
            return True
    logging.getLogger("asyncio").addFilter(_DropCancelledTaskTraceback())

    handle_norm = handle.lstrip("@").strip()
    if not handle_norm:
        click.echo(click.style("Empty handle.", fg="red"))
        sys.exit(2)

    from datetime import datetime, timezone
    from sqlalchemy import text
    from adapters.persistence.tiktok_persistence import TikTokPersistenceAdapter
    from adapters.tiktok_profile_scraper import fetch_public_profile

    persistence = TikTokPersistenceAdapter(auto_init=True)
    eng = persistence.engine

    # Header — make the source legend explicit before we print anything.
    click.echo()
    click.echo(click.style("=" * 78, fg="white"))
    click.echo(click.style(f" debug:@{handle_norm} ", fg="white", bg="blue", bold=True)
               + "  "
               + click.style(" REMOTE = live TikTok ", fg="white", bg="blue")
               + "  "
               + click.style(" LOCAL DB = our cache ", fg="black", bg="yellow"))
    click.echo(click.style("=" * 78, fg="white"))

    # ── 1. Profile probe (HTML scrape; bypasses the throttled cache) ────
    _section(f"@{handle_norm} — profile probe", source="REMOTE")
    try:
        probe = await fetch_public_profile(handle_norm)
    except Exception as e:
        click.echo(click.style(f"  scraper raised: {type(e).__name__}: {e}", fg="red"))
        probe = {}
    debug_records: list[dict] = list(probe.get("probe_debug") or []) if isinstance(probe, dict) else []
    if probe:
        for k in ("is_live", "nickname", "follower_count", "following_count",
                 "user_id", "current_room_id", "bio", "exists", "error"):
            if k in probe:
                v = probe.get(k)
                tone = "red" if k == "error" and v else None
                click.echo(f"  {k:18s} {click.style(str(v), fg=tone) if tone else v}")
    if debug_records:
        click.echo(click.style(f"  probe_debug ({len(debug_records)} attempt(s)):", fg="cyan"))
        for i, rec in enumerate(debug_records, 1):
            url = rec.get("url", "?")
            status = rec.get("status")
            blen = rec.get("body_len")
            reason = rec.get("reason")
            tone = "red" if reason == "waf" else "yellow" if reason and reason != "ok" else "green"
            click.echo(
                "  "
                + click.style(f"  [{i}] {url}", fg="white")
                + f"  status={status}  len={blen}  "
                + click.style(f"reason={reason}", fg=tone)
            )
            snip = (rec.get("snippet") or "").replace("\n", " ")[:160]
            if snip:
                click.echo(f"        snippet: {snip}")

    # ── 2. DB-side subscription / cache state ───────────────────────────
    _section("Subscription cache", source="LOCAL DB")
    with eng.connect() as c:
        sub = c.execute(text("""
            SELECT unique_id, enabled, assigned_worker_id, assignment_lease_until,
                   is_live, live_checked_at, current_room_id,
                   nickname, follower_count, profile_error,
                   profile_refreshed_at
            FROM tiktok_subscriptions WHERE unique_id=:h
        """), {"h": handle_norm}).mappings().first()
        if sub is None:
            click.echo(click.style("  no tiktok_subscriptions row for this handle.", fg="yellow"))
        else:
            for k, v in dict(sub).items():
                tone = "red" if k == "profile_error" and v else None
                click.echo(f"  {k:24s} {click.style(str(v), fg=tone) if tone else v}")

        # ── 3. Worker presence + recent worker_log ──────────────────────
        _section(
            "Worker_log (last 30 entries for this handle)",
            source="LOCAL DB",
        )
        rows = c.execute(text("""
            SELECT id, ts, level, event, detail FROM tiktok_worker_log
            WHERE handle=:h
              AND ts >= now() - interval '24 hours'
            ORDER BY id DESC LIMIT 30
        """), {"h": handle_norm}).all()
        if not rows:
            click.echo("  (no worker_log rows in the last 24h)")
        for r in rows:
            tone = "red" if r.level == "error" else "yellow" if r.level == "warning" else None
            line = f"  {r.ts}  [{r.level}]  {r.event}"
            click.echo(click.style(line, fg=tone) if tone else line)
            if r.detail:
                detail_s = str(r.detail)
                if len(detail_s) > 220:
                    detail_s = detail_s[:220] + "…"
                click.echo(f"      detail: {detail_s}")

        # Worker session-snapshot for this handle
        wrow = c.execute(text("""
            SELECT pid, host, status, last_heartbeat_at,
                   metadata->'sessions' AS sessions
            FROM tiktok_workers
        """)).mappings().all()
        if wrow:
            for w in wrow:
                hb = w["last_heartbeat_at"]
                hb_age = (datetime.now(timezone.utc) - hb).total_seconds() if hb else None
                stale = hb_age is not None and hb_age > 30
                line = (
                    f"  worker pid={w['pid']} host={w['host']} status={w['status']} "
                    f"hb_age={hb_age:.1f}s" + ("  STALE" if stale else "")
                )
                click.echo(click.style(line, fg="red" if stale else None))
                sess = [s for s in (w["sessions"] or [])
                        if isinstance(s, dict) and s.get("handle") == handle_norm]
                if sess:
                    s = sess[0]
                    click.echo(f"    session: state={s.get('state')} "
                               f"is_connected={s.get('is_connected')} "
                               f"events_total={s.get('events_total')} "
                               f"last_event_age_s={s.get('last_event_age_s')}")
                    if s.get("last_error_kind"):
                        click.echo(click.style(
                            f"    last_error: {s['last_error_kind']} — "
                            f"{(s.get('last_error_message') or '')[:200]}",
                            fg="red",
                        ))
                else:
                    click.echo(click.style("    (no session for this handle on this worker)", fg="yellow"))

        # ── 4. Recent rooms + events for this host ──────────────────────
        _section("Rooms (most recent 5)", source="LOCAL DB")
        rooms = c.execute(text("""
            SELECT room_id, first_seen_at, ended_at, last_seen_at,
              (SELECT COUNT(*) FROM tiktok_events e WHERE e.room_id=r.room_id) AS events,
              (SELECT SUM(COALESCE(NULLIF(payload->>'diamond_count','')::int,0) *
                          COALESCE(NULLIF(payload->>'repeat_count','')::int,1))
                 FROM tiktok_events e WHERE e.room_id=r.room_id AND e.type='gift') AS diamonds
            FROM tiktok_rooms r WHERE host_unique_id=:h
            ORDER BY first_seen_at DESC LIMIT 5
        """), {"h": handle_norm}).all()
        if not rooms:
            click.echo("  (no rooms ever recorded for this handle)")
        for r in rooms:
            click.echo(
                f"  rid={r.room_id}  first={r.first_seen_at}  "
                f"last={r.last_seen_at}  ended={r.ended_at}  "
                f"events={r.events}  diamonds={r.diamonds or 0}"
            )

    # ── 5. WebSocket connect probe ──────────────────────────────────────
    if no_ws:
        _section("WebSocket probe — skipped (--no-ws)", source="REMOTE")
        return

    _section(
        f"WebSocket connect — listen up to {seconds}s or {max_events} events",
        source="REMOTE",
    )
    from TikTokLive import TikTokLiveClient
    from TikTokLive.client.errors import (
        UserNotFoundError,
        UserOfflineError,
        AgeRestrictedError,
        InitialCursorMissingError,
        WebsocketURLMissingError,
    )
    # Mirror the worker's sign-provider bootstrap. Without this the raw
    # client falls back to TikTokLive's defaults (unauth + rate-limited),
    # which manifests as a `ReadTimeout` on `start()` even when the user
    # is happily broadcasting and the production worker is ingesting fine.
    from adapters.tiktok_live_client import (
        _apply_sign_globals, _apply_sign_client_state,
    )
    _apply_sign_globals()
    client = TikTokLiveClient(unique_id=f"@{handle_norm}")
    _apply_sign_client_state(client, handle=f"@{handle_norm}")
    captured: list[tuple[str, str]] = []  # (event_type, summary)
    deadline = asyncio.get_event_loop().time() + seconds

    # Per-type colours for the streaming output — easy to scan.
    _TYPE_COLOR = {
        "CommentEvent": "white",
        "GiftEvent": "yellow",
        "LikeEvent": "magenta",
        "JoinEvent": "green",
        "FollowEvent": "cyan",
        "ShareEvent": "cyan",
        "RoomUserSeqEvent": "blue",
        "ConnectEvent": "green",
        "DisconnectEvent": "red",
    }

    async def on_any(event):
        type_name = type(event).__name__
        # Build a compact one-line summary depending on event type.
        summary = ""
        try:
            if type_name == "CommentEvent":
                summary = f"{getattr(event.user,'unique_id','?')}: " + (event.comment or "")[:80]
            elif type_name == "GiftEvent":
                gift_name = getattr(getattr(event, "gift", None), "name", "?")
                d = getattr(getattr(event, "gift", None), "diamond_count", 0) or 0
                rep = getattr(event, "repeat_count", 1) or 1
                to = getattr(event, "to_user", None)
                to_s = (
                    f" → @{getattr(to,'unique_id','')}"
                    if to and getattr(to, "unique_id", "") else ""
                )
                summary = (f"{getattr(event.user,'unique_id','?')} sent "
                           f"{gift_name} ×{rep} ({d*rep}💎){to_s}")
            elif type_name == "LikeEvent":
                summary = f"{getattr(event.user,'unique_id','?')} ×{getattr(event,'count',1)}"
            elif type_name == "JoinEvent":
                summary = f"{getattr(event.user,'unique_id','?')} joined"
            elif type_name == "RoomUserSeqEvent":
                summary = f"viewers={getattr(event,'total','?')}"
        except Exception:
            summary = "(decode failed)"
        captured.append((type_name, summary))
        # Stream live — without this, a 260s run looks "frozen" because
        # we'd only print the recap at the end. Each line: a count
        # marker + the type tag (coloured) + the summary.
        idx = len(captured)
        tone = _TYPE_COLOR.get(type_name)
        click.echo(
            click.style(f"  [{idx:>3}] ", fg="white")
            + click.style(f"{type_name:18s}", fg=tone, bold=True)
            + " "
            + summary
        )
        if len(captured) >= max_events:
            await client.disconnect()

    # Subscribe to a broad set; the lib emits each one through a typed listener.
    from TikTokLive.events import (
        ConnectEvent, DisconnectEvent, CommentEvent, GiftEvent, LikeEvent,
        JoinEvent, RoomUserSeqEvent, ShareEvent, FollowEvent,
    )
    for ev in (ConnectEvent, DisconnectEvent, CommentEvent, GiftEvent, LikeEvent,
               JoinEvent, RoomUserSeqEvent, ShareEvent, FollowEvent):
        client.add_listener(ev, on_any)

    err_kind: str | None = None
    err_message: str | None = None
    err_source: str | None = None  # "start" | "heartbeat" | "?"
    connected = False
    heartbeat_task = None

    @client.on(ConnectEvent)
    async def _on_connect(_):
        nonlocal connected
        connected = True
        click.echo(click.style(
            f"  CONNECTED  room_id={client.room_id}", fg="green"
        ))

    try:
        # `start()` returns the heartbeat task once room-info is fetched +
        # the WS handshake is open. We must ALSO await heartbeat to catch
        # errors that surface ASYNCHRONOUSLY (e.g. the WS opens then drops
        # with WebcastBlocked200Error, UserOfflineError mid-stream). Without
        # this, the worker logs the error but our probe sees a clean return
        # → "no exception but never connected" which masks the real cause.
        heartbeat_task = await asyncio.wait_for(
            client.start(fetch_room_info=True),
            timeout=20,
        )
        # Print the post-start state so a "no connect" failure leaves
        # *something* visible even if no exception lands.
        click.echo(
            f"  post-start: client.connected={client.connected} "
            f"room_id={client.room_id} heartbeat_task={'yes' if heartbeat_task else 'no'}"
        )
    except UserOfflineError as e:
        err_kind, err_message, err_source = "UserOfflineError", str(e), "start"
    except UserNotFoundError as e:
        err_kind, err_message, err_source = "UserNotFoundError", str(e), "start"
    except AgeRestrictedError as e:
        err_kind, err_message, err_source = "AgeRestrictedError", str(e), "start"
    except (InitialCursorMissingError, WebsocketURLMissingError, asyncio.TimeoutError) as e:
        err_kind, err_message, err_source = type(e).__name__, str(e), "start"
    except Exception as e:
        err_kind, err_message, err_source = type(e).__name__, str(e), "start"

    # If start succeeded, drain events while ALSO watching the heartbeat
    # so any async failure surfaces. Critical: when the deadline / event
    # cap is reached, we tell the lib to `disconnect()` BEFORE awaiting
    # the heartbeat. That lets the lib tear down its internal tasks
    # cleanly — if we cancel the heartbeat task ourselves while it's
    # mid-handshake, asyncio prints noisy "Task exception was never
    # retrieved → CancelledError" tracebacks at GC.
    if err_kind is None and heartbeat_task is not None:
        async def _drain_events():
            # Use our local `connected` flag (set by ConnectEvent handler)
            # rather than `client.connected`, which the lib reports as None
            # before the handshake completes — that race could short-circuit
            # the drain loop before any events arrive.
            while asyncio.get_event_loop().time() < deadline:
                if len(captured) >= max_events:
                    break
                await asyncio.sleep(0.5)
        drain = asyncio.create_task(_drain_events())
        hb = asyncio.ensure_future(heartbeat_task)
        done, _pending = await asyncio.wait(
            {drain, hb}, return_when=asyncio.FIRST_COMPLETED,
        )
        # Heartbeat finished first → an error or the WS closed. Capture.
        if hb in done:
            try:
                hb.result()
            except (UserOfflineError, UserNotFoundError, AgeRestrictedError,
                    InitialCursorMissingError, WebsocketURLMissingError) as e:
                err_kind, err_message, err_source = type(e).__name__, str(e), "heartbeat"
            except Exception as e:
                err_kind, err_message, err_source = type(e).__name__, str(e), "heartbeat"
        # Polite disconnect first — tells the lib to close its receiver
        # task and websocket cleanly. THEN wait for the heartbeat to
        # exit (with a short bound so a wedged lib doesn't hang us).
        try:
            await client.disconnect()
        except Exception:
            pass
        if not hb.done():
            try:
                await asyncio.wait_for(hb, timeout=3)
            except asyncio.TimeoutError:
                # Lib didn't close in 3s — last resort cancel. Suppress
                # the resulting CancelledError from the awaited task.
                hb.cancel()
                try:
                    await hb
                except BaseException:
                    pass
        if not drain.done():
            drain.cancel()
            try:
                await drain
            except BaseException:
                pass

    if err_kind:
        src_tag = f" (raised in {err_source})" if err_source else ""
        click.echo(click.style(
            f"  WS terminal: {err_kind}: {err_message}{src_tag}",
            fg="red",
        ))
    elif not connected:
        # `start()` returned clean and heartbeat didn't error, yet
        # ConnectEvent never fired. In TikTokLive 6.6.x this is the
        # signature of "the room is no longer broadcasting" — the lib
        # fetches room info, gets back an offline status, and exits the
        # async heartbeat without raising. Tells you the public-profile
        # cache (is_live=true) is staler than the WS sees.
        click.echo(click.style(
            "  WS returned cleanly with no ConnectEvent — most likely the user "
            "is no longer live (lib returned silently on offline room info). "
            "Compare: subscription cache `is_live` vs the WS truth here.",
            fg="yellow",
        ))

    click.echo()
    click.echo(click.style(
        f"  total: {len(captured)} event(s) captured", fg="cyan",
    ))
    type_counts: dict[str, int] = {}
    for t, _s in captured:
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, n in sorted(type_counts.items(), key=lambda x: -x[1]):
        click.echo(f"    {t}: {n}")


def _section(title: str, *, source: str | None = None) -> None:
    """Section header with explicit data-source tag.

    `source="REMOTE"` = data fetched live from TikTok (HTML scrape or WS).
    `source="LOCAL DB"` = data read from our Postgres (cached / historical).
    Tag colours are blue (remote) vs yellow (local) so it's unambiguous
    at a glance which numbers are TikTok truth and which are our cache."""
    click.echo()
    if source == "REMOTE":
        tag = click.style(" [REMOTE — live TikTok] ", fg="white", bg="blue", bold=True)
    elif source == "LOCAL DB":
        tag = click.style(" [LOCAL DB — our cache] ", fg="black", bg="yellow", bold=True)
    else:
        tag = ""
    click.echo(click.style(f"── {title} ──", bold=True) + (f"  {tag}" if tag else ""))


async def _list_lives() -> None:
    """Pretty-print every subscription with cached profile + state."""
    _configure_logging()
    from adapters.persistence.tiktok_persistence import TikTokPersistenceAdapter
    from adapters.tiktok_live_client import TikTokLiveSessionFactory
    from domain.services.tiktok_service import TikTokService

    svc = TikTokService(
        persistence=TikTokPersistenceAdapter(auto_init=True),
        session_factory=TikTokLiveSessionFactory(),
        passive=True,  # we only need read-side; never want to start sessions here
    )
    rows = await svc.list_subscriptions()
    if not rows:
        click.echo("No subscriptions yet. Add one via /admin/tiktok or POST /admin/tiktok/lives.")
        return
    # Compact tabular output.
    headers = ("HANDLE", "NICKNAME", "FOLLOWERS", "STATE", "ENABLED", "REFRESHED")
    widths = [max(len(h), 10) for h in headers]
    table: list[tuple[str, ...]] = [headers]
    for s in rows:
        refreshed = s.get("profile_refreshed_at") or "-"
        if refreshed and refreshed != "-":
            refreshed = refreshed.split(".")[0].replace("T", " ")
        followers = s.get("follower_count")
        followers_s = _fmt_count(followers) if followers is not None else "-"
        table.append((
            f"@{s['unique_id']}",
            (s.get("nickname") or "-")[:24],
            followers_s,
            s.get("state") or "-",
            "yes" if s.get("enabled") else "no",
            refreshed,
        ))
    for r in table:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    for i, r in enumerate(table):
        line = "  ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(r))
        click.echo(line)
        if i == 0:
            click.echo("  ".join("-" * w for w in widths))


async def _refresh_profiles(*, handle: str | None, force_all: bool) -> None:
    """Refresh cached profile fields. Either one handle, every stale row,
    or every row regardless of staleness."""
    _configure_logging()
    from adapters.persistence.tiktok_persistence import TikTokPersistenceAdapter
    from adapters.tiktok_live_client import TikTokLiveSessionFactory
    from domain.services.tiktok_service import TikTokService

    persistence = TikTokPersistenceAdapter(auto_init=True)
    svc = TikTokService(
        persistence=persistence,
        session_factory=TikTokLiveSessionFactory(),
        passive=True,
    )

    if handle:
        h = handle.lstrip("@").strip()
        click.echo(f"Refreshing @{h} …")
        await svc.refresh_profile(h)
        # Print the resulting row.
        sub = persistence.get_subscription(h)
        if sub is None:
            click.echo("(no subscription found for that handle)")
            return
        _print_kv({
            "handle": sub.unique_id,
            "nickname": sub.nickname,
            "user_id": sub.profile_user_id,
            "follower_count": sub.follower_count,
            "verified": sub.verified,
            "profile_refreshed_at": sub.profile_refreshed_at,
            "profile_error": sub.profile_error,
        }, title=f"@{sub.unique_id}")
        return

    if force_all:
        # Pretend everything is stale by passing a 0-second cutoff.
        click.echo("Refreshing every subscription …")
        n = await svc.refresh_stale_profiles(stale_after_seconds=0, limit=10_000)
    else:
        click.echo("Refreshing stale subscriptions (>1h since last fetch) …")
        n = await svc.refresh_stale_profiles()
    click.echo(f"Done. Refreshed {n} handle(s).")


def _print_kv(data: dict, *, title: str) -> None:
    """Tabular print for a flat dict; skips Falsy/None unless explicitly bool False."""
    click.echo(click.style(title, bold=True))
    click.echo("-" * max(20, len(title)))
    for k, v in data.items():
        if v is None or v == "":
            continue
        if isinstance(v, str) and len(v) > 100:
            v = v[:97] + "…"
        click.echo(f"  {k:>22} : {v}")


def _fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k" if n < 10_000 else f"{n / 1_000:.0f}k"
    return str(n)


def _configure_logging() -> None:
    """Stream INFO-and-above to stdout. The framework's main app uses a
    structured logger; this worker keeps it simple — one process, one log."""
    if logging.getLogger().handlers:
        # Already configured (e.g. when invoked via cli.py main).
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# Also expose the top-level command names that __init__.py re-exports.
run_listener_cmd = run_listener

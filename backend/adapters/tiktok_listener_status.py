"""Listener-pool heartbeat + status snapshot.

The worker process periodically stamps a heartbeat — both to Redis
(short TTL) and to a sentinel file (mtime is the heartbeat). The API
process reads the freshest of the two to decide whether the worker is
alive, what its PID is, and how long it's been running.

Two writes (Redis + file) so the admin status card works whether or
not Redis is available. Redis is the canonical source when present;
file is the fallback for Redis-less dev setups.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any

from utils.redis_client import get_redis

logger = logging.getLogger(__name__)

REDIS_KEY = "tiktok:listener:heartbeat"
LOCKFILE_PATH = "/tmp/phoveus-tiktok-listener.lock"
HEARTBEAT_FILE = "/tmp/phoveus-tiktok-listener.heartbeat"
DEFAULT_INTERVAL = 5.0   # seconds between writes
DEFAULT_TTL = 15         # seconds — heartbeat is "stale" past this


def _file_atomic_write(path: str, payload: bytes) -> None:
    """Write-then-rename so a partial read never sees half a JSON blob."""
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    os.replace(tmp, path)


class HeartbeatWriter:
    """Background **thread** that snapshots worker state every `interval`
    seconds and writes it to a sentinel file (and Redis when configured).

    Why a thread instead of an asyncio task: the worker's asyncio loop
    runs 10–20 supervisor tasks doing concurrent HTTP, brush/event
    handlers, and persistence I/O. A heartbeat task sharing that loop
    can be starved when the loop is busy, leading to a stale heartbeat
    file and a "Worker offline" UI even though the worker is healthy.
    Running heartbeat in its own thread isolates it: file writes, snapshot
    reads, and timer waits are independent of the async event loop.

    `snapshot_fn` is called each tick from the heartbeat thread. It must
    be SYNC. Reading from regular Python dicts (the service's _states /
    _sessions / counter dicts) from a thread is safe under the GIL — at
    worst we read a momentarily-inconsistent snapshot, never crash.
    """

    def __init__(
        self,
        snapshot_fn,
        *,
        interval: float = DEFAULT_INTERVAL,
        ttl: int = DEFAULT_TTL,
        loop: "asyncio.AbstractEventLoop | None" = None,
    ) -> None:
        self._snapshot_fn = snapshot_fn
        self._interval = interval
        self._ttl = ttl
        # Cache the asyncio loop so we can schedule Redis writes back into
        # it from our thread (Redis client uses async I/O on the loop).
        self._loop = loop
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = None
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="tiktok-heartbeat", daemon=True,
        )
        self._thread.start()

    async def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            # Don't block the asyncio loop — join from a thread executor.
            await asyncio.get_running_loop().run_in_executor(
                None, self._thread.join, 5.0,
            )
        # Best-effort: remove the heartbeat file on clean shutdown so
        # the API doesn't briefly think the worker is "alive but stale".
        try:
            os.unlink(HEARTBEAT_FILE)
        except OSError:
            pass
        # And the Redis key.
        try:
            r = get_redis()
            if r is not None:
                await r.delete(REDIS_KEY)
        except Exception:
            pass

    def _run(self) -> None:
        """Thread main: snapshot + write every `interval` seconds until
        stop event is set. Catches all exceptions so a single bad tick
        doesn't kill the heartbeat permanently."""
        while not self._stop.is_set():
            try:
                snap = self._snapshot_fn()
                snap.setdefault("written_at", time.time())
                payload = json.dumps(snap, default=str).encode()
                self._write_file(payload)
                self._write_redis_async(payload)
            except Exception:
                logger.exception("Heartbeat tick failed")
            # threading.Event.wait returns True if set during the wait,
            # False on timeout. Either way, the next loop check exits.
            self._stop.wait(self._interval)

    def _write_file(self, payload: bytes) -> None:
        try:
            _file_atomic_write(HEARTBEAT_FILE, payload)
        except OSError:
            logger.exception("Heartbeat file write failed (%s)", HEARTBEAT_FILE)

    def _write_redis_async(self, payload: bytes) -> None:
        """Schedule a Redis SET on the asyncio loop without blocking this
        thread. If Redis isn't configured or the loop isn't available,
        no-op — the file heartbeat is the canonical fallback."""
        if self._loop is None:
            return
        try:
            r = get_redis()
            if r is None:
                return
            asyncio.run_coroutine_threadsafe(
                r.set(REDIS_KEY, payload, ex=self._ttl),
                self._loop,
            )
        except Exception:
            logger.debug("Heartbeat Redis schedule failed", exc_info=True)


async def read_heartbeat() -> dict[str, Any] | None:
    """Read the freshest heartbeat. Redis wins when present; file fallback
    when Redis is unavailable. Returns None when neither has anything."""
    # 1. Redis first (TTL means presence == fresh).
    try:
        r = get_redis()
        if r is not None:
            raw = await r.get(REDIS_KEY)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                return _parse_heartbeat(raw, source="redis")
    except Exception:
        logger.exception("Heartbeat Redis read failed")

    # 2. File fallback. Use mtime as the freshness signal — the worker
    # rewrites the file every `interval` seconds.
    try:
        st = os.stat(HEARTBEAT_FILE)
        with open(HEARTBEAT_FILE, "rb") as f:
            raw = f.read().decode()
        snap = _parse_heartbeat(raw, source="file")
        # Override the written_at with the file's mtime — that's
        # what the API actually trusts for staleness.
        if snap is not None:
            snap["written_at"] = st.st_mtime
        return snap
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Heartbeat file read failed")
        return None


def _parse_heartbeat(raw: str, *, source: str) -> dict[str, Any] | None:
    try:
        snap = json.loads(raw)
        if not isinstance(snap, dict):
            return None
        snap["_source"] = source
        return snap
    except (TypeError, ValueError):
        return None


def read_lockfile_pid() -> int | None:
    """Read the PID stamped into the listener lockfile, if present.

    Used by the API process to send signals to whichever worker is
    currently holding the listener-pool lock.
    """
    try:
        with open(LOCKFILE_PATH, "r") as f:
            raw = (f.read() or "").strip()
        if not raw:
            return None
        return int(raw.splitlines()[0])
    except (FileNotFoundError, ValueError):
        return None
    except Exception:
        logger.exception("Lockfile PID read failed")
        return None


def is_pid_alive(pid: int) -> bool:
    """POSIX-only liveness check via `kill -0`."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours; treat as alive
    except OSError:
        return False
    return True

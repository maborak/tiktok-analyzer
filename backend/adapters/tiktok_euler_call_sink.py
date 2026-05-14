"""Capture every Euler-signed HTTP call into `tiktok_euler_call_log`.

We attach `httpx` `event_hooks` (request + response) to the TikTokLive
client's `web.httpx_client` after construction. The hooks see every
outbound HTTP call the lib makes; we filter for the signing service
(`tiktok.eulerstream.com`) and the Euler-signed `webcast.*.tiktok.com`
endpoints (`room/info`, `room/check_alive`, etc.) which all consume
the same per-call signing quota.

Each hit gets buffered in a process-local queue; a background asyncio
task flushes batches to the DB every `FLUSH_INTERVAL_S` seconds (or
sooner when the buffer hits `FLUSH_BATCH_SIZE`). The hot path stays
zero-DB-IO so a probe storm can't make the listener loop crawl.

Public API:
  attach_to_client(client, api_key_fp)
      Install request+response hooks on `client.web.httpx_client`.
      Idempotent — re-attaching during a reconnect re-installs the
      same hooks but doesn't double-log.
  start_flusher_task()
      Spawns the background flush task. Returns the task handle.
      Call once per worker boot.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, parse_qs

from sqlalchemy import text

from database.core.connection import create_database_engine

logger = logging.getLogger(__name__)

# Tunables. The defaults trade ~1 DB roundtrip per minute for very
# little memory (~100 KB at peak burst). Override via env if a future
# install starts logging a lot more than today's ~1 call / second.
FLUSH_INTERVAL_S = 5.0
FLUSH_BATCH_SIZE = 200
QUEUE_MAX = 5000  # drop-oldest when exceeded so OOM isn't possible


@dataclass
class _Sample:
    ts_iso: str         # ISO timestamp at request start (UTC, naive db-compatible string)
    api_key_fp: str     # short fingerprint of the Euler API key in effect at call time
    endpoint: str       # "webcast/fetch", "room/info", ...
    handle: str | None  # `unique_id` query param if extractable
    status_code: int | None
    latency_ms: int | None
    error_kind: str | None


_BUFFER: list[_Sample] = []
_BUFFER_LOCK = asyncio.Lock()


def _fingerprint_api_key(raw: str | None) -> str:
    """Same shape as the worker boot banner — `prefix…suffix (len=N)`.
    Empty / missing key collapses to "(none)" so anonymous calls are
    visually distinct in the dashboard."""
    if not raw:
        return "(none)"
    s = raw.strip()
    if len(s) > 16:
        return f"{s[:12]}…{s[-8:]} (len={len(s)})"
    return f"len={len(s)}"


def _classify_url(url: str) -> tuple[str, str] | None:
    """Classify an outbound HTTP URL into `(endpoint, kind)`. Returns
    None for URLs we don't care about so the hook short-circuits.

    `endpoint` is a stable short label used as the series key in the
    dashboard. `kind` is the higher-level bucket:

      * `euler-sign`         — direct calls to EulerStream's sign API
                               (each consumes 1 sign quota slot).
      * `webcast`            — Euler-signed `webcast.*.tiktok.com/webcast/*`
                               calls. Each consumes 1 Euler sign slot
                               (the sign happens upstream of the GET).
      * `tiktok-direct`      — anonymous unsigned `www.tiktok.com/@…`
                               and `m.tiktok.com/@…` scrapes used by the
                               profile / live-page probe. DON'T consume
                               Euler quota but DO hit the public-site WAF
                               so they're worth showing in the dashboard
                               for separate troubleshooting.
    """
    try:
        p = urlparse(url)
    except Exception:
        return None
    host = (p.hostname or "").lower()
    path = p.path or ""
    if "eulerstream.com" in host:
        ep = path.strip("/").rstrip("/") or "eulerstream"
        return (ep, "euler-sign")
    if host.endswith("tiktok.com") and "/webcast/" in path:
        ep = path.strip("/").rstrip("/") or "webcast"
        return (ep, "webcast")
    # Direct anonymous tiktok.com pages (profile scraper + live URL
    # probe). We care about /@<handle>… and /@<handle>/live… — the
    # profile and live-page scrapes — but NOT the asset CDN
    # (p16-…, sf16-…, *.akamaized.net etc.) which would flood the log.
    if (
        host == "www.tiktok.com" or host == "m.tiktok.com"
    ) and path.startswith("/@"):
        # "/@user"          → "tiktok/profile"
        # "/@user/live"     → "tiktok/live"
        # "/@user/video/12" → "tiktok/video"
        tail = path.split("/")
        if len(tail) >= 3 and tail[2]:
            return (f"tiktok/{tail[2]}", "tiktok-direct")
        return ("tiktok/profile", "tiktok-direct")
    return None


# Backward-compat alias for code that still calls the old name. New
# callers should use `_classify_url` directly.
def _endpoint_from_url(url: str) -> str | None:
    hit = _classify_url(url)
    return hit[0] if hit else None


def _handle_from_url(url: str) -> str | None:
    """Extract `unique_id=…` from the query string when present so the
    log row is tied to a handle. Falls back to None for endpoints that
    only carry `room_id`."""
    try:
        p = urlparse(url)
    except Exception:
        return None
    q = parse_qs(p.query)
    if "unique_id" in q and q["unique_id"]:
        v = q["unique_id"][0]
        return v.lstrip("@")[:64] if v else None
    if "uniqueId" in q and q["uniqueId"]:
        v = q["uniqueId"][0]
        return v.lstrip("@")[:64] if v else None
    return None


def _now_iso_z() -> str:
    # Naive UTC string — Postgres parses it as TIMESTAMPTZ given the
    # column type. We append 'Z' so the parser knows it's UTC.
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def _enqueue(sample: _Sample) -> None:
    async with _BUFFER_LOCK:
        if len(_BUFFER) >= QUEUE_MAX:
            # Drop oldest. Logging the drop would itself cost — just
            # silently shed load. A loud warning every 1000 drops:
            if (len(_BUFFER) - QUEUE_MAX) % 1000 == 0:
                logger.warning(
                    "euler-call-log buffer at cap %d — shedding oldest. "
                    "If this is steady-state the flusher can't keep up.",
                    QUEUE_MAX,
                )
            _BUFFER.pop(0)
        _BUFFER.append(sample)


def attach_to_client(client: Any, api_key_fp: str) -> None:
    """Install request + response event hooks on the TikTokLive client.

    Idempotent: re-attaching during a reconnect replaces our hooks
    with fresh ones (the lib's other hooks are preserved). The
    `api_key_fp` closure is captured per-attach so subsequent rotations
    are reflected in subsequent calls without needing to re-attach.
    """
    httpx_client = getattr(client.web, "httpx_client", None)
    if httpx_client is None:
        return

    # Per-request timing — request hook stamps start time on the
    # request extensions dict; response hook reads it and computes
    # latency. httpx exposes `request.extensions` for free-form use.
    async def on_request(req):  # type: ignore[no-untyped-def]
        hit = _classify_url(str(req.url))
        if not hit:
            return  # not a TikTok / Euler URL — skip (CDN assets, etc.)
        ep, kind = hit
        req.extensions["_call_t0"] = time.monotonic()
        req.extensions["_call_ep"] = ep
        req.extensions["_call_kind"] = kind
        req.extensions["_call_handle"] = _handle_from_url(str(req.url))

    async def on_response(resp):  # type: ignore[no-untyped-def]
        ep = resp.request.extensions.get("_call_ep")
        if not ep:
            return
        t0 = resp.request.extensions.get("_call_t0")
        latency_ms = int((time.monotonic() - t0) * 1000) if t0 else None
        # The `_call_kind` is carried in the endpoint string via a
        # prefix convention so the DB schema doesn't need a new column;
        # the service layer parses it back out at query time. Format:
        # the bare endpoint label (no prefix). Kind is reconstructed
        # from the endpoint at query time using the same rules.
        await _enqueue(_Sample(
            ts_iso=_now_iso_z(),
            api_key_fp=api_key_fp,
            endpoint=ep,
            handle=resp.request.extensions.get("_call_handle"),
            status_code=int(resp.status_code) if resp.status_code else None,
            latency_ms=latency_ms,
            error_kind=None,
        ))

    # `event_hooks` is `dict[str, list[callable]]`. Preserve any
    # existing hooks (curl_cffi sometimes installs its own).
    hooks = dict(getattr(httpx_client, "event_hooks", {}) or {})
    req_hooks = list(hooks.get("request") or [])
    resp_hooks = list(hooks.get("response") or [])
    # De-dup our own hook by name on re-attach.
    req_hooks = [h for h in req_hooks if getattr(h, "__name__", "") != "on_request"]
    resp_hooks = [h for h in resp_hooks if getattr(h, "__name__", "") != "on_response"]
    req_hooks.append(on_request)
    resp_hooks.append(on_response)
    hooks["request"] = req_hooks
    hooks["response"] = resp_hooks
    httpx_client.event_hooks = hooks


# ── batch flusher ────────────────────────────────────────────────────


async def _flush_once() -> int:
    async with _BUFFER_LOCK:
        if not _BUFFER:
            return 0
        batch = _BUFFER[:]
        _BUFFER.clear()
    if not batch:
        return 0
    # Synchronous bulk insert — runs in the default thread executor
    # via `to_thread` so the asyncio loop stays free.
    def _insert() -> None:
        engine = create_database_engine()
        with engine.begin() as c:
            # Postgres-only multi-VALUES insert. SQLite would silently
            # fall back to one-at-a-time, but the worker doesn't run
            # under SQLite in practice.
            c.execute(
                text("""
                    INSERT INTO tiktok_euler_call_log
                        (ts, api_key_fp, endpoint, handle,
                         status_code, latency_ms, error_kind)
                    VALUES
                        (CAST(:ts AS timestamptz), :fp, :ep, :h,
                         :sc, :lm, :ek)
                """),
                [
                    {
                        "ts": s.ts_iso, "fp": s.api_key_fp,
                        "ep": s.endpoint, "h": s.handle,
                        "sc": s.status_code, "lm": s.latency_ms,
                        "ek": s.error_kind,
                    }
                    for s in batch
                ],
            )
    try:
        await asyncio.to_thread(_insert)
        return len(batch)
    except Exception:
        logger.exception("euler-call-log flush failed; %d sample(s) lost.", len(batch))
        return 0


async def _flusher_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=FLUSH_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass
        try:
            n = await _flush_once()
            if n > 0:
                logger.debug("euler-call-log: flushed %d sample(s).", n)
        except Exception:
            logger.exception("euler-call-log flusher iter raised; continuing.")
    # Final flush on shutdown so we don't lose in-flight samples.
    try:
        n = await _flush_once()
        if n:
            logger.info("euler-call-log: drained %d sample(s) on shutdown.", n)
    except Exception:
        logger.exception("euler-call-log final flush failed.")


def start_flusher_task(stop: asyncio.Event) -> asyncio.Task:
    """Spawn the background flusher. Cancel via `stop.set()` for clean
    shutdown — final drain runs once on stop."""
    return asyncio.create_task(_flusher_loop(stop), name="euler-call-log-flusher")

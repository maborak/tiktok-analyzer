"""HTTP middleware: per-request perf tracer.

Lifecycle per request:
  1. On entry, instantiate a `PerfTracer`, bind it to the request
     context via `bind_tracer`, and stamp the trace_id onto the
     request state.
  2. Pass through to the rest of the stack. Service / persistence
     code opens spans via `utils.perf_tracer.span(...)`.
  3. On exit, read the tracer state, attach `X-Trace-Id` to the
     response, and fire-and-forget a DB write of the trace.

Tracing is gated to a small allowlist of route prefixes so we don't
flood the table with auth / static / health-check requests. The list
covers the slow surfaces we actually want to optimise:

  - `/admin/tiktok/`   (admin TikTok HTTP routes)
  - `/public/tiktok/`  (public mirror)
  - `/admin/`          (other admin pages — small volume, useful)

Persistence is best-effort and never blocks the response. If the
write fails (Postgres down, table missing on SQLite dev, etc.), we
log at WARNING and move on; the user still gets their response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from utils.perf_tracer import PerfTracer, bind_tracer, reset_tracer

logger = logging.getLogger(__name__)


# Prefix allow-list for trace capture. Other routes still get the
# header on response (cheap) but aren't persisted.
_TRACED_PREFIXES: tuple[str, ...] = (
    "/admin/tiktok/",
    "/public/tiktok/",
    "/admin/",  # broader admin pages — small volume, valuable signal
)

# Skip the chatty hooks that already poll on a fixed cadence; their
# perf is well-understood and they'd flood the table.
_SKIP_PREFIXES: tuple[str, ...] = (
    "/admin/tiktok/ws",          # websocket upgrade
    "/admin/tiktok/listener/log",  # 5s polled, low-value
)


def _should_persist(path: str, method: str) -> bool:
    # CORS preflights are 0-ms and high-volume — skipping them keeps
    # the trace table actionable (every persisted row has spans).
    if method == "OPTIONS":
        return False
    if path.startswith(_SKIP_PREFIXES):
        return False
    return path.startswith(_TRACED_PREFIXES)


def _extract_handle(path: str) -> Optional[str]:
    """Pull the TikTok handle out of admin/tiktok paths. Two URL
    shapes carry a handle:

      /admin/tiktok/{handle}            (direct deep-link)
      /admin/tiktok/{handle}/...        (host-scoped sub-routes)
      /admin/tiktok/lives/{handle}      (cache + admin alias)
      /admin/tiktok/lives/{handle}/...  (calendar, rooms, cross-live-gifters, refresh)

    Returns None for routes that don't carry a handle anywhere in
    the path (`/rooms/{room_id}/...`, `/matches/...`, `/perf/...`).
    """
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[0] not in ("admin", "public") or parts[1] != "tiktok":
        return None

    # Reserved second-segments that AREN'T handles themselves but
    # MAY carry a handle in the next slot (`lives/{handle}/...`).
    HANDLE_AT_3 = {"lives"}
    # Reserved second-segments that never carry a handle anywhere.
    HANDLE_NEVER = {
        "cache", "matches", "users", "common-gifters",
        "favorite-gifters", "notifications", "listener", "events",
        "gifts", "worker", "euler", "dashboard", "ws", "runtime-config",
        "sign", "perf", "rooms", "enigmas",
    }
    third = parts[2]
    if third in HANDLE_AT_3:
        return parts[3] if len(parts) >= 4 else None
    if third in HANDLE_NEVER:
        return None
    return third


def _extract_room_id(path: str) -> Optional[int]:
    """Pull `{room_id}` out of `/admin/tiktok/rooms/{room_id}/…`
    paths. The read endpoint joins this to `tiktok_rooms` to resolve
    the host handle, so traces for room-scoped routes still show
    "whose live was this?" in the UI."""
    parts = path.strip("/").split("/")
    if (
        len(parts) >= 4
        and parts[0] in ("admin", "public")
        and parts[1] == "tiktok"
        and parts[2] == "rooms"
    ):
        try:
            return int(parts[3])
        except (TypeError, ValueError):
            return None
    return None


def _route_template(request: Request) -> str:
    """Prefer the FastAPI route template (with `{handle}` placeholders)
    over the raw URL path so grouping by endpoint works even when
    each call has a different handle."""
    try:
        route = request.scope.get("route")
        if route is not None and hasattr(route, "path"):
            return str(route.path)
    except Exception:
        pass
    return request.url.path


class PerfTracerMiddleware(BaseHTTPMiddleware):
    """Captures one trace per request inside the allowed prefixes.
    Persists asynchronously; never blocks the response."""

    def __init__(self, app, persister: Optional[Callable] = None) -> None:
        """`persister` is an injected dependency:
            (trace_row: dict) -> Awaitable[None] | None
        Wired by `api_main.py` to the actual DB write function. When
        None (e.g. early-boot, tests), traces are still captured but
        the persist step is skipped."""
        super().__init__(app)
        self._persister = persister

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        method = request.method
        # Fast-path: skip pure pass-through for excluded surfaces.
        # We still set the header on responses, just don't persist.
        capture = _should_persist(path, method)

        tracer = PerfTracer() if capture else None
        token = bind_tracer(tracer) if tracer else None
        request.state.perf_tracer = tracer

        response: Response
        try:
            response = await call_next(request)
        finally:
            if token is not None:
                reset_tracer(token)

        if tracer is None:
            return response

        # Header for the operator + Playwright correlation.
        response.headers["X-Trace-Id"] = tracer.trace_id

        # Persist asynchronously — never block the response on the
        # write. The persister handles its own errors.
        try:
            data = tracer.finalize()
            handle = _extract_handle(path)
            room_id = _extract_room_id(path)
            meta = dict(data["meta"])
            if room_id is not None:
                meta["room_id"] = room_id
            row = {
                "trace_id": tracer.trace_id,
                "endpoint": _route_template(request),
                "method": method,
                "status": response.status_code,
                "total_ms": data["total_ms"],
                "query_count": data["query_count"],
                "handle": handle,
                "spans": data["spans"],
                "meta": meta,
            }
            if self._persister is not None:
                # Fire-and-forget; ignore the returned task.
                asyncio.create_task(_safe_persist(self._persister, row))
        except Exception:
            logger.exception("perf-tracer: failed to finalize trace")

        return response


async def _safe_persist(persister: Callable, row: dict) -> None:
    """Wrap the persist call so the background task never raises
    into the event loop."""
    try:
        result = persister(row)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        logger.warning("perf-tracer: persist failed", exc_info=True)

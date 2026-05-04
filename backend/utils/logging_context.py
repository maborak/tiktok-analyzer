"""
Request-scoped logging context for structured per-request fields.

Provides:
- ContextFilter   — injects trace_id, request_id, user_id, http_method, http_path onto every LogRecord
- LogContextMiddleware — populates the context for each HTTP request and logs outcomes
- set_trace_id / get_trace_id — helpers for CLI and background processes
"""

import base64
import contextvars
import json
import logging
import time
import uuid
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

# Per-request context variable; default is an empty dict so ContextFilter always has a safe fallback
_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("log_ctx", default={})


# ---------------------------------------------------------------------------
# Public helpers — use these from CLI commands, background tasks, hook handlers
# ---------------------------------------------------------------------------

def set_trace_id(trace_id: Optional[str] = None) -> str:
    """Set (or generate) a trace_id in the current logging context.

    Returns the trace_id that was set.  Safe to call from any context —
    HTTP requests, CLI commands, asyncio tasks, hook handlers.
    """
    if trace_id is None:
        trace_id = uuid.uuid4().hex
    ctx = dict(_ctx.get({}))          # shallow copy so we don't mutate the original
    ctx["trace_id"] = trace_id
    _ctx.set(ctx)
    return trace_id


def get_trace_id() -> Optional[str]:
    """Return the current trace_id, or None if not set."""
    return _ctx.get({}).get("trace_id")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_user_id(request: Request) -> str:
    """Extract user_id from JWT Authorization header without full validation."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return "-"
    try:
        token = auth.split(" ", 1)[1]
        parts = token.split(".")
        if len(parts) != 3:
            return "-"
        payload_b64 = parts[1]
        # Add padding so base64 decoding doesn't fail
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
        return str(payload.get("sub", "-"))
    except Exception:
        return "-"


class ContextFilter(logging.Filter):
    """Injects per-request fields into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _ctx.get({})
        record.trace_id = ctx.get("trace_id", "-")
        record.request_id = ctx.get("request_id", "-")
        record.user_id = ctx.get("user_id", "-")
        record.http_method = ctx.get("http_method", "-")
        record.http_path = ctx.get("http_path", "-")
        return True


class LogContextMiddleware(BaseHTTPMiddleware):
    """Middleware that sets per-request log context and logs request outcomes."""

    def __init__(self, app, excluded_paths: Optional[set] = None):
        super().__init__(app)
        if excluded_paths is None:
            from config import CONFIG
            excluded_paths = CONFIG.get("LOG_EXCLUDED_PATHS", {"/health"})
        self._excluded = excluded_paths

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        skip_log = path in self._excluded

        # Accept trace_id from inbound header (for cross-service tracing) or generate one
        inbound_trace = request.headers.get("X-Trace-Id")
        trace_id = inbound_trace or uuid.uuid4().hex

        token = _ctx.set({
            "trace_id": trace_id,
            "request_id": str(uuid.uuid4()),
            "user_id": _extract_user_id(request),
            "http_method": request.method,
            "http_path": path,
        })
        t0 = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            _ctx.reset(token)
            raise

        # Propagate trace_id back to caller
        response.headers["X-Trace-Id"] = trace_id

        if not skip_log:
            status_code = response.status_code
            duration_ms = round((time.monotonic() - t0) * 1000)
            log_extra = {"duration_ms": duration_ms, "http.status_code": status_code}

            if status_code >= 500:
                logger.error("%s %s → %d (%dms)", request.method, path, status_code, duration_ms, extra=log_extra)
            elif status_code >= 400:
                logger.warning("%s %s → %d (%dms)", request.method, path, status_code, duration_ms, extra=log_extra)
            else:
                logger.info("%s %s → %d (%dms)", request.method, path, status_code, duration_ms, extra=log_extra)

        _ctx.reset(token)
        return response

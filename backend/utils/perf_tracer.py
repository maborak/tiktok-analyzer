"""Per-request performance tracer.

A lightweight in-process profiler. Each HTTP request that enters
through `PerfTracerMiddleware` gets a `PerfTracer` bound to a
`contextvars.ContextVar`. Service / persistence code can then open
named spans without threading the tracer through every function
signature:

    from utils.perf_tracer import span

    with span("svc.get_room_stats"):
        ...

When the request ends, the middleware reads the tracer's accumulated
data and writes one row to `tiktok_perf_traces`.

Design notes
------------
- contextvars: ContextVar binds the tracer to the asyncio task that's
  handling the request. Spans opened inside `asyncio.to_thread` worker
  threads INHERIT the parent context (contextvars are copied to the
  thread on `to_thread` dispatch), so SQL spans recorded from the
  thread-pool show up in the right trace.
- No-op when off: when no tracer is bound (middleware didn't run, or
  request is excluded from tracing), `span()` returns a cheap no-op
  context manager. Hot paths pay only a single `ContextVar.get()`.
- Wall-clock only: we record `time.perf_counter()` deltas. No
  thread-time decomposition (would need OS hooks); for I/O-heavy
  code like ours, wall-clock IS the metric.
- Bounded: each trace is capped at `MAX_SPANS_PER_TRACE` so a
  pathological recursive call site can't blow up memory or the JSONB
  payload. Excess spans are dropped after a warning.
"""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)


# Soft cap on spans per trace. Real cold-load on the detail page
# expects ~25-50 spans; 1000 is a defensive cap.
MAX_SPANS_PER_TRACE = 1000


class _Span:
    __slots__ = ("name", "start_ms", "dur_ms", "meta")

    def __init__(self, name: str, start_ms: float) -> None:
        self.name = name
        self.start_ms = start_ms
        # Filled when the span closes; -1 sentinel until then.
        self.dur_ms: float = -1.0
        self.meta: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "start_ms": round(self.start_ms, 2),
            "dur_ms": round(self.dur_ms, 2),
        }
        if self.meta:
            out["meta"] = self.meta
        return out


class PerfTracer:
    """One tracer per request. Holds the list of spans, counters,
    and the request-start timestamp. Thread-safe via GIL: span
    open/close from the threadpool only appends to the list."""

    __slots__ = (
        "trace_id", "request_started_at", "_spans",
        "_query_count", "_cache_hits", "_cache_misses",
        "_meta", "_overflow_warned",
    )

    def __init__(self, trace_id: str | None = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.request_started_at = time.perf_counter()
        self._spans: list[_Span] = []
        self._query_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._meta: dict[str, Any] = {}
        self._overflow_warned = False

    @contextlib.contextmanager
    def span(self, name: str, **meta: Any) -> Iterator[_Span]:
        """Open a named span. The `with` block's duration is recorded
        and appended to the trace on exit. `meta` is merged into the
        span's `meta` dict and serialised to JSONB."""
        if len(self._spans) >= MAX_SPANS_PER_TRACE:
            if not self._overflow_warned:
                logger.warning(
                    "perf-tracer: span cap (%d) hit on trace %s — dropping further spans",
                    MAX_SPANS_PER_TRACE, self.trace_id,
                )
                self._overflow_warned = True
            yield _Span(name, -1.0)
            return
        now = time.perf_counter()
        s = _Span(name, (now - self.request_started_at) * 1000.0)
        if meta:
            s.meta.update(meta)
        self._spans.append(s)
        t0 = now
        try:
            yield s
        finally:
            s.dur_ms = (time.perf_counter() - t0) * 1000.0

    def bump_query(self, n: int = 1) -> None:
        self._query_count += n

    def cache_hit(self, name: str = "") -> None:
        self._cache_hits += 1
        # Light-weight per-cache breakdown if a name is given.
        if name:
            by = self._meta.setdefault("cache_by_name", {})
            slot = by.setdefault(name, [0, 0])  # [hits, misses]
            slot[0] += 1

    def cache_miss(self, name: str = "") -> None:
        self._cache_misses += 1
        if name:
            by = self._meta.setdefault("cache_by_name", {})
            slot = by.setdefault(name, [0, 0])
            slot[1] += 1

    def set_meta(self, key: str, value: Any) -> None:
        self._meta[key] = value

    def finalize(self) -> dict[str, Any]:
        """Return the JSON-ready trace payload. Call once at request
        exit. Idempotent — safe to call multiple times."""
        return {
            "trace_id": self.trace_id,
            "total_ms": int((time.perf_counter() - self.request_started_at) * 1000),
            "spans": [s.to_dict() for s in self._spans],
            "query_count": self._query_count,
            "meta": {
                **self._meta,
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
            },
        }


# Module-level ContextVar — bound by the middleware on request entry,
# read by `span()` everywhere. ContextVar handles asyncio + threadpool
# correctly (each task / dispatched thread gets its own snapshot).
_active_tracer: ContextVar[PerfTracer | None] = ContextVar(
    "perf_tracer", default=None,
)


def current_tracer() -> Optional[PerfTracer]:
    """Return the tracer for the current request, or None when
    tracing is off (e.g. request not under the middleware)."""
    return _active_tracer.get()


@contextlib.contextmanager
def span(name: str, **meta: Any) -> Iterator[Optional[_Span]]:
    """No-op when no tracer is bound; otherwise delegates to the
    request's tracer. Use this from any code path — hot paths pay
    one ContextVar.get() lookup when tracing is off."""
    t = _active_tracer.get()
    if t is None:
        yield None
        return
    with t.span(name, **meta) as s:
        yield s


def cache_hit(name: str = "", n: int = 1) -> None:
    """Record `n` cache hit(s) on the active tracer. No-op when no
    tracer is bound, so call sites stay agnostic to whether they're
    running inside a traced request. `name` populates the per-cache
    breakdown in `meta.cache_by_name`."""
    t = _active_tracer.get()
    if t is None:
        return
    for _ in range(max(1, n)):
        t.cache_hit(name)


def cache_miss(name: str = "", n: int = 1) -> None:
    """Record `n` cache miss(es) on the active tracer. See
    `cache_hit` for the no-op-when-untraced contract."""
    t = _active_tracer.get()
    if t is None:
        return
    for _ in range(max(1, n)):
        t.cache_miss(name)


def bind_tracer(t: PerfTracer | None) -> Any:
    """Bind the tracer to the current context. Returns a token that
    the middleware MUST reset on exit to avoid leaking the binding
    across requests."""
    return _active_tracer.set(t)


def reset_tracer(token: Any) -> None:
    _active_tracer.reset(token)


# ── SQLAlchemy query counter hook ──────────────────────────────────
#
# Auto-increments the active tracer's `query_count` on every SQL
# execution. Registered once at module import, fires globally on
# every Engine. When no tracer is bound (most non-request code),
# the lookup is a single `ContextVar.get()` and returns immediately —
# no measurable overhead in untraced paths.
#
# We register on the `Engine` class (not on a specific engine
# instance) so brand-new engines created later — e.g. the
# adapter's read/write split — are covered without extra wiring.
def _register_sqlalchemy_query_counter() -> None:
    try:
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
    except Exception:
        return  # SQLAlchemy not installed for some test path; nothing to do.

    # Idempotent — re-importing this module (test runners, hot
    # reload) shouldn't double-register the listener.
    flag = "__tiktok_perf_query_counter_registered"
    if getattr(Engine, flag, False):
        return
    setattr(Engine, flag, True)

    @event.listens_for(Engine, "before_cursor_execute")
    def _bump_query_on_execute(
        _conn, _cursor, _statement, _parameters, _context, _executemany,
    ):
        t = _active_tracer.get()
        if t is not None:
            t.bump_query()


_register_sqlalchemy_query_counter()

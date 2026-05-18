"""Phase 9D tests — WS delta fan-out + request-snapshot.

These tests exercise the WS endpoint integrations via FastAPI's
`TestClient.websocket_connect()`. They wire a real `TikTokService` +
in-process state cache + persistence adapter (DB optional — the
WS plumbing itself doesn't need Postgres).

What's verified:
- A state-cache `apply_patch` triggers a `{type:"summary-delta", ...}`
  frame on connected admin WS clients within 1 s.
- The same patch on the public channel ships with operator-only
  fields stripped (admin sees them, public doesn't).
- `{type:"request-snapshot", handles:[...]}` triggers one
  `{type:"snapshot", host, version, data}` reply per handle.
- Hosts not in the public-handle set produce empty snapshots
  (`version=0, data={}`) on the public WS even when the cache has
  full state — no operator-only leak.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Iterator

import pytest

from adapters.tiktok_state_cache_inproc import TikTokStateCacheInProc


# A read timeout that's long enough for the cache → WS hop in the
# test runner, short enough that a regression fails fast.
WS_RECV_TIMEOUT_S = 3.0


def _recv_with_timeout(ws, timeout: float = WS_RECV_TIMEOUT_S) -> str:
    """Bounded `ws.receive_text()`. Starlette's `WebSocketTestSession.receive_text`
    blocks indefinitely with no timeout kwarg; we wrap the call in a
    daemon thread + `join(timeout=...)`. If the receive hangs past the
    deadline, raise — the daemon thread dies with the process.

    Risk: each timed-out call leaks one daemon thread. Acceptable for
    a test suite where a hang is a regression we want to surface
    loudly, not absorb silently."""
    result: list[Any] = [None]
    err: list[BaseException] = []

    def _r() -> None:
        try:
            result[0] = ws.receive_text()
        except BaseException as e:
            err.append(e)

    t = threading.Thread(target=_r, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise TimeoutError(
            f"WS receive_text timed out after {timeout}s — likely a regression"
        )
    if err:
        raise err[0]
    return result[0]


# ── service test doubles ────────────────────────────────────────────


class _FakePersistence:
    """Minimal persistence stand-in. The WS endpoint reads
    `_state_cache` off persistence and (after the 2026-05-16 phantom-
    live fix) calls `get_hosts_with_active_room` to gate snapshot
    replies against SQL authority. The test default is "every queried
    host is active" — tests that exercise the phantom-live path
    override `_active_hosts` to drive specific scenarios."""

    def __init__(
        self,
        state_cache: TikTokStateCacheInProc,
        *,
        active_hosts: set[str] | None = None,
    ) -> None:
        self._state_cache = state_cache
        # `None` means "everything passed in is active" — see method.
        self._active_hosts = active_hosts

    def get_hosts_with_active_room(self, handles: list[str]) -> set[str]:
        if self._active_hosts is None:
            return set(handles)
        return {h for h in handles if h in self._active_hosts}


class _FakeTikTokService:
    """Mimics the surface `routes/admin/tiktok.py` and
    `routes/public_tiktok.py` touch on the WS path."""

    def __init__(
        self,
        state_cache: TikTokStateCacheInProc,
        *,
        public_handles: frozenset[str] | None = None,
    ) -> None:
        self._persistence = _FakePersistence(state_cache)
        self._public_handles = public_handles or frozenset()

    def get_public_handle_set(self) -> frozenset[str]:
        return self._public_handles

    def sanitize_public_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Drop any key NOT in a small allowlist. Used by the public
        snapshot reply path. Mirrors `TikTokService.sanitize_public_patch`'s
        shape but with a tiny test allowlist."""
        allow = {"diamonds_session", "viewer_count", "top_gifters"}
        return {k: v for k, v in patch.items() if k in allow}

    # Subset of `_CACHE_OVERLAY_FIELDS` from the real service. The
    # fake doesn't need to enumerate every field — just enough to
    # let tests assert that "host without active room gets these
    # fields stripped" actually happens through the fake.
    _SESSION_FIELDS: frozenset[str] = frozenset({
        "diamonds_session",
        "viewer_count",
        "top_gifters",
        "active_room_id",
        "session_stats",
    })

    def sanitize_cached_snapshot(
        self,
        host: str,
        data: dict[str, Any],
        *,
        active_hosts: set[str] | None = None,
    ) -> dict[str, Any]:
        """Mirror the real service's SQL-authority gate: if the host
        is NOT in `active_hosts` (i.e. no SQL-confirmed live room),
        strip session-scoped fields and any `_*` aux key. With the
        pass-through original, no test could catch a regression where
        the strip step was accidentally bypassed."""
        norm = host.lstrip("@").strip().lower()
        if active_hosts is None:
            active_hosts = self._persistence.get_hosts_with_active_room([norm])
        if norm in active_hosts:
            return data
        return {
            k: v
            for k, v in data.items()
            if k not in self._SESSION_FIELDS and not k.startswith("_")
        }

    # The admin event-pump helpers from `routes.admin.tiktok` get
    # called with this service — they expect `add_listener` /
    # `remove_listener`. No events flow in these tests; provide no-ops.
    def add_listener(self, _l: Any) -> None:
        pass

    def remove_listener(self, _l: Any) -> None:
        pass


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def state_cache() -> TikTokStateCacheInProc:
    return TikTokStateCacheInProc(public_sanitizer=None)


@pytest.fixture
def admin_app(state_cache, monkeypatch):
    """FastAPI app with the admin WS endpoint mounted + the fake
    service patched in. The auth gate is also patched out so the
    test doesn't need a real JWT.

    Forces `in_process` listener mode so the WS handler uses
    `_ws_pump_from_service` (which awaits on a queue and stays open)
    instead of `_ws_pump_from_redis` (which returns empty when Redis
    isn't reachable, collapsing the WS immediately)."""
    monkeypatch.setenv("PHOVEU_BACKEND_TIKTOK_LISTENER_MODE", "in_process")

    from fastapi import FastAPI
    from routes.admin import tiktok as admin_tiktok_module

    fake_service = _FakeTikTokService(state_cache)

    # Patch the module-global. The WS handler reads `tiktok_service`
    # via module scope at call time (it's set by `set_dependencies`
    # in normal boot).
    monkeypatch.setattr(admin_tiktok_module, "tiktok_service", fake_service)

    # Patch the auth gate. The WS validates the token before accept;
    # bypass that with a stub auth_context that grants admin:write.
    class _StubAuthContext:
        class user:
            username = "test"
        permissions = ["admin:write"]
        def has_permission(self, p):
            return p == "admin:write"

    class _StubAuthService:
        def get_auth_context(self, _token):
            return _StubAuthContext()

    monkeypatch.setattr(
        "utils.auth_provider.get_auth_service",
        lambda: _StubAuthService(),
    )

    app = FastAPI()
    app.include_router(admin_tiktok_module.router, prefix="/admin/tiktok")
    return app


@pytest.fixture
def public_app(state_cache, monkeypatch):
    """FastAPI app with the public WS endpoint mounted + fake service."""
    monkeypatch.setenv("PHOVEU_BACKEND_TIKTOK_LISTENER_MODE", "in_process")

    from fastapi import FastAPI
    from routes import public_tiktok as public_tiktok_module
    from routes.admin import tiktok as admin_tiktok_module

    fake_service = _FakeTikTokService(
        state_cache,
        public_handles=frozenset({"public_host"}),
    )

    # Patch in the same fake service on both modules — the public
    # route imports `_ws_pump_*` from admin.tiktok, which also reads
    # the module-global service.
    monkeypatch.setattr(public_tiktok_module, "tiktok_service", fake_service)
    monkeypatch.setattr(admin_tiktok_module, "tiktok_service", fake_service)

    app = FastAPI()
    app.include_router(public_tiktok_module.router, prefix="/public")
    return app


# ── admin: summary-delta fan-out ────────────────────────────────────


def test_admin_ws_forwards_state_cache_delta(admin_app, state_cache):
    """A patch applied to the state cache lands on the admin WS as
    a `summary-delta` frame within `WS_RECV_TIMEOUT_S`."""
    from fastapi.testclient import TestClient

    client = TestClient(admin_app)
    with client.websocket_connect("/admin/tiktok/ws?token=fake") as ws:
        # Apply patch from a background thread so the WS server thread
        # can deliver. TestClient's WS is synchronous — the receive
        # call blocks the calling thread, so the patch must come from
        # somewhere else.
        threading.Timer(
            0.05,
            lambda: state_cache.apply_patch("alice", {"diamonds_session": 100}),
        ).start()
        # The WS may forward unrelated messages from the underlying
        # event pump (none in this test since no listener) — but it
        # WILL emit our summary-delta. Drain a few frames if needed.
        deadline_frames = 5
        for _ in range(deadline_frames):
            raw = _recv_with_timeout(ws)
            msg = json.loads(raw)
            if msg.get("type") == "summary-delta":
                assert msg["host"] == "alice"
                assert msg["version"] == 1
                assert msg["patch"] == {"diamonds_session": 100}
                return
        pytest.fail("no summary-delta frame received in time")


def test_admin_ws_filters_summary_delta_by_subscribed_handles(
    admin_app, state_cache,
):
    """Client narrows to `["bob"]` → deltas for `alice` are silently
    dropped, deltas for `bob` arrive."""
    from fastapi.testclient import TestClient

    client = TestClient(admin_app)
    with client.websocket_connect("/admin/tiktok/ws?token=fake") as ws:
        ws.send_json({"type": "subscribe", "handles": ["bob"]})
        # Give the server a beat to process the subscribe.
        import time
        time.sleep(0.1)

        threading.Timer(
            0.05,
            lambda: (
                state_cache.apply_patch("alice", {"x": 1}),
                state_cache.apply_patch("bob",   {"y": 2}),
            ),
        ).start()
        # The first matching frame must be the bob delta.
        for _ in range(10):
            raw = _recv_with_timeout(ws)
            msg = json.loads(raw)
            if msg.get("type") != "summary-delta":
                continue
            assert msg["host"] == "bob", (
                f"unexpected delta for host={msg.get('host')!r} "
                f"when subscribed to ['bob']"
            )
            assert msg["patch"] == {"y": 2}
            return
        pytest.fail("no matching summary-delta for bob")


# ── admin: request-snapshot ─────────────────────────────────────────


def test_admin_ws_request_snapshot_replies_per_handle(admin_app, state_cache):
    """Client sends `request-snapshot` for two handles, one populated
    and one absent. Two `snapshot` replies arrive, one with cached
    data + version, one with empty data + version=0."""
    from fastapi.testclient import TestClient

    state_cache.set("alice", version=42, data={
        "diamonds_session": 500,
        "_gifter_totals": {"1": 500},  # aux, should be stripped on snapshot
    })

    client = TestClient(admin_app)
    with client.websocket_connect("/admin/tiktok/ws?token=fake") as ws:
        ws.send_json({"type": "request-snapshot", "handles": ["alice", "bob"]})
        # Collect 2 snapshots (may be interleaved with other frames).
        replies: dict[str, dict] = {}
        for _ in range(8):
            raw = _recv_with_timeout(ws)
            msg = json.loads(raw)
            if msg.get("type") == "snapshot":
                replies[msg["host"]] = msg
                if len(replies) >= 2:
                    break

        assert "alice" in replies and "bob" in replies, (
            f"got: {list(replies)}"
        )
        # Alice: populated, aux stripped.
        assert replies["alice"]["version"] == 42
        assert replies["alice"]["data"] == {"diamonds_session": 500}
        # Bob: not in cache → version=0, empty data.
        assert replies["bob"]["version"] == 0
        assert replies["bob"]["data"] == {}


# ── public: sanitized snapshot + public-set gating ──────────────────


def test_public_ws_snapshot_omits_operator_only_fields(public_app, state_cache):
    """Public WS snapshot reply MUST go through `sanitize_public_patch`.
    Fields outside the allowlist (e.g. `reconnects_1h`) must not appear."""
    from fastapi.testclient import TestClient

    # Pre-seed the cache with both public-safe and operator-only fields.
    state_cache.set("public_host", version=10, data={
        "diamonds_session": 100,       # public — allowed
        "viewer_count": 50,            # public — allowed
        "top_gifters": [{"x": 1}],     # public — allowed
        "reconnects_1h": 7,            # operator-only — must be stripped
        "_gifter_totals": {"1": 100},  # aux — stripped first
    })

    client = TestClient(public_app)
    with client.websocket_connect("/public/tiktok/ws") as ws:
        ws.send_json({"type": "request-snapshot", "handles": ["public_host"]})
        for _ in range(5):
            raw = _recv_with_timeout(ws)
            msg = json.loads(raw)
            if msg.get("type") == "snapshot":
                assert msg["version"] == 10
                # Sanitizer allowlist: only the 3 public-allowlisted keys
                # may appear. Operator-only `reconnects_1h` MUST be gone.
                assert "reconnects_1h" not in msg["data"]
                assert "_gifter_totals" not in msg["data"]
                assert set(msg["data"]) <= {
                    "diamonds_session", "viewer_count", "top_gifters",
                }
                assert msg["data"]["diamonds_session"] == 100
                return
        pytest.fail("no snapshot reply received on public WS")


def test_public_ws_snapshot_hides_private_hosts(public_app, state_cache):
    """A handle NOT in the public-handle set gets an empty snapshot —
    we don't reveal whether private hosts exist or have data. The
    cache contents stay opaque to anonymous viewers."""
    from fastapi.testclient import TestClient

    # `private_host` is NOT in `public_handles` from the fixture, but
    # IS in the state cache.
    state_cache.set("private_host", version=99, data={
        "diamonds_session": 9999,
    })

    client = TestClient(public_app)
    with client.websocket_connect("/public/tiktok/ws") as ws:
        ws.send_json({"type": "request-snapshot", "handles": ["private_host"]})
        for _ in range(5):
            raw = _recv_with_timeout(ws)
            msg = json.loads(raw)
            if msg.get("type") == "snapshot":
                assert msg["host"] == "private_host"
                # MUST look identical to a "doesn't exist" response —
                # version=0, empty data. The frontend treats this
                # same way it treats a cache-miss reply.
                assert msg["version"] == 0
                assert msg["data"] == {}
                return
        pytest.fail("no snapshot reply for private host")

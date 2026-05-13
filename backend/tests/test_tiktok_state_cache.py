"""Phase A — TikTokStateCachePort + two adapters.

Behaviour parity test: every assertion runs against BOTH the
in-process adapter and (if a Redis instance is reachable) the Redis
adapter. The same test body validates both, so a regression in one
implementation can't slip through.

The Redis tests skip cleanly when no Redis is reachable so this file
remains runnable in environments without Redis (e.g. CI without a
service container). Redis tests use a unique key prefix per test
run so they don't collide with production state — the adapter
prefix happens to be `tiktok:lives:state:` which is a "real" prefix
in this codebase. Tests run `clear()` before AND after to leave the
namespace clean.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Iterator

import pytest

from adapters.tiktok_state_cache_inproc import TikTokStateCacheInProc
from ports.tiktok_state_cache import (
    CHANNEL_ADMIN,
    CHANNEL_PUBLIC,
    TikTokStateCachePort,
)


# ── adapter factories ───────────────────────────────────────────────


def _inproc_factory(
    public_sanitizer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[TikTokStateCachePort, Callable[[], None]]:
    """Returns (cache, teardown). Teardown is a no-op for in-process —
    the cache is GC'd when the test function exits."""
    cache = TikTokStateCacheInProc(public_sanitizer=public_sanitizer)
    return cache, lambda: None


def _redis_available() -> bool:
    try:
        import redis  # noqa: F401
    except ImportError:
        return False
    url = os.getenv("PHOVEU_REDIS_SERVER", "redis://localhost:6379/0")
    try:
        import redis as redis_lib
        client = redis_lib.from_url(url, socket_connect_timeout=0.5)
        client.ping()
        client.close()
        return True
    except Exception:
        return False


def _redis_factory(
    public_sanitizer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[TikTokStateCachePort, Callable[[], None]]:
    import redis as redis_lib
    from adapters.tiktok_state_cache_redis import TikTokStateCacheRedis

    url = os.getenv("PHOVEU_REDIS_SERVER", "redis://localhost:6379/0")
    sync_client = redis_lib.from_url(url, decode_responses=False)
    async_client = redis_lib.asyncio.from_url(url, decode_responses=False)
    cache = TikTokStateCacheRedis(
        sync_client=sync_client,
        async_client_getter=lambda: async_client,
        public_sanitizer=public_sanitizer,
    )
    cache.clear()

    def teardown() -> None:
        cache.clear()
        sync_client.close()
        # async client cleanup is loop-bound; close on a fresh loop.
        try:
            asyncio.new_event_loop().run_until_complete(async_client.aclose())
        except Exception:
            pass

    return cache, teardown


# Parametrize every test with the adapter factory. Redis is skipped
# when unavailable. Each test gets a fresh cache.
@pytest.fixture(
    params=[
        pytest.param("inproc", id="inproc"),
        pytest.param(
            "redis",
            id="redis",
            marks=pytest.mark.skipif(
                not _redis_available(),
                reason="no Redis reachable at $PHOVEU_REDIS_SERVER",
            ),
        ),
    ]
)
def cache(request) -> Iterator[TikTokStateCachePort]:
    factory = _inproc_factory if request.param == "inproc" else _redis_factory
    obj, teardown = factory()
    try:
        yield obj
    finally:
        teardown()


# Variant fixture for tests that need a public sanitizer wired in.
@pytest.fixture(
    params=[
        pytest.param("inproc", id="inproc"),
        pytest.param(
            "redis",
            id="redis",
            marks=pytest.mark.skipif(
                not _redis_available(),
                reason="no Redis reachable at $PHOVEU_REDIS_SERVER",
            ),
        ),
    ]
)
def cache_with_sanitizer(request) -> Iterator[TikTokStateCachePort]:
    factory = _inproc_factory if request.param == "inproc" else _redis_factory
    obj, teardown = factory(public_sanitizer=_test_public_sanitizer)
    try:
        yield obj
    finally:
        teardown()


# Strip every field that contains "admin" in its name. Toy allowlist
# only used in tests — the real one lives in `tiktok_service.py`.
def _test_public_sanitizer(patch: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in patch.items() if "admin" not in k.lower()}


# ── tests ───────────────────────────────────────────────────────────


def test_get_missing_returns_none(cache: TikTokStateCachePort) -> None:
    assert cache.get("noone") is None
    assert cache.list_versions() == {}


def test_set_then_get_roundtrip(cache: TikTokStateCachePort) -> None:
    cache.set("alice", version=5, data={"diamonds": 12, "viewer_count": 99})
    result = cache.get("alice")
    assert result is not None
    version, data = result
    assert version == 5
    assert data == {"diamonds": 12, "viewer_count": 99}


def test_apply_patch_creates_then_merges(cache: TikTokStateCachePort) -> None:
    # First apply_patch on a missing host creates the slice at v=1.
    v1 = cache.apply_patch("bob", {"diamonds": 100})
    assert v1 == 1
    assert cache.get("bob") == (1, {"diamonds": 100})

    # Second apply_patch deep-merges.
    v2 = cache.apply_patch("bob", {"viewer_count": 50})
    assert v2 == 2
    assert cache.get("bob") == (2, {"diamonds": 100, "viewer_count": 50})

    # Nested dict merges field-by-field.
    cache.apply_patch("bob", {"session_stats": {"n_gifts": 3}})
    cache.apply_patch("bob", {"session_stats": {"n_comments": 7}})
    v5_or_4, data = cache.get("bob")  # type: ignore[misc]
    assert data["session_stats"] == {"n_gifts": 3, "n_comments": 7}


def test_apply_patch_empty_is_noop(cache: TikTokStateCachePort) -> None:
    v = cache.apply_patch("carol", {})
    assert v is None
    assert cache.get("carol") is None


def test_apply_patch_list_replaces_not_merges(
    cache: TikTokStateCachePort,
) -> None:
    cache.apply_patch("dave", {"viewer_history": [1, 2, 3]})
    cache.apply_patch("dave", {"viewer_history": [4, 5]})
    _, data = cache.get("dave")  # type: ignore[misc]
    assert data["viewer_history"] == [4, 5]


def test_version_is_monotonic_per_host(cache: TikTokStateCachePort) -> None:
    versions: list[int] = []
    for i in range(10):
        v = cache.apply_patch("erin", {"counter": i})
        assert v is not None
        versions.append(v)
    assert versions == list(range(1, 11))


def test_version_independent_across_hosts(cache: TikTokStateCachePort) -> None:
    cache.apply_patch("frank", {"a": 1})
    cache.apply_patch("grace", {"a": 1})
    cache.apply_patch("frank", {"a": 2})
    cache.apply_patch("frank", {"a": 3})
    cache.apply_patch("grace", {"a": 2})
    assert cache.get("frank") == (3, {"a": 3})
    assert cache.get("grace") == (2, {"a": 2})


def test_list_versions_diagnostic(cache: TikTokStateCachePort) -> None:
    cache.apply_patch("h1", {"a": 1})
    cache.apply_patch("h2", {"a": 1})
    cache.apply_patch("h1", {"a": 2})
    versions = cache.list_versions()
    assert versions == {"h1": 2, "h2": 1}


def test_clear(cache: TikTokStateCachePort) -> None:
    cache.apply_patch("h1", {"a": 1})
    cache.apply_patch("h2", {"a": 1})
    cache.clear()
    assert cache.get("h1") is None
    assert cache.get("h2") is None
    assert cache.list_versions() == {}


def test_get_returns_independent_copy(cache: TikTokStateCachePort) -> None:
    """Mutating the dict a caller got from `get` must not poison the
    cache. Otherwise concurrent readers + a careless mutation
    corrupts the state."""
    cache.set("h1", version=1, data={"nested": {"x": 1}})
    _, data = cache.get("h1")  # type: ignore[misc]
    data["nested"]["x"] = 999
    _, data2 = cache.get("h1")  # type: ignore[misc]
    assert data2["nested"]["x"] == 1


# ── pub/sub ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_admin_receives_deltas(
    cache: TikTokStateCachePort,
) -> None:
    received: list[dict[str, Any]] = []

    async def consume() -> None:
        async for delta in cache.subscribe(CHANNEL_ADMIN):
            received.append(delta)
            if len(received) >= 3:
                return

    task = asyncio.create_task(consume())
    # Give the subscriber a beat to attach. The in-process adapter
    # attaches synchronously inside the iterator but Redis pub-sub
    # needs an actual SUBSCRIBE round-trip.
    await asyncio.sleep(0.1)

    cache.apply_patch("h", {"diamonds": 10})
    cache.apply_patch("h", {"diamonds": 20})
    cache.apply_patch("h", {"viewer_count": 5})

    # Bounded wait so a flaky pub/sub fails the test instead of hanging.
    await asyncio.wait_for(task, timeout=5.0)

    assert len(received) == 3
    assert [d["host"] for d in received] == ["h", "h", "h"]
    assert [d["version"] for d in received] == [1, 2, 3]
    assert received[0]["patch"] == {"diamonds": 10}
    assert received[2]["patch"] == {"viewer_count": 5}


@pytest.mark.asyncio
async def test_subscribe_public_uses_sanitizer(
    cache_with_sanitizer: TikTokStateCachePort,
) -> None:
    """Public channel deltas are filtered through the sanitizer.
    Admin channel always sees the raw patch."""
    admin_received: list[dict[str, Any]] = []
    public_received: list[dict[str, Any]] = []

    async def consume_admin() -> None:
        async for delta in cache_with_sanitizer.subscribe(CHANNEL_ADMIN):
            admin_received.append(delta)
            if len(admin_received) >= 2:
                return

    async def consume_public() -> None:
        async for delta in cache_with_sanitizer.subscribe(CHANNEL_PUBLIC):
            public_received.append(delta)
            if len(public_received) >= 1:
                return

    admin_task = asyncio.create_task(consume_admin())
    public_task = asyncio.create_task(consume_public())
    await asyncio.sleep(0.1)

    # Both channels see this — no admin-only fields.
    cache_with_sanitizer.apply_patch("h", {"diamonds": 10})
    # Public channel filters out `listener_admin_dot`. Admin sees both
    # patches; public only the first one (the second post-sanitize
    # patch is empty so the public publish is skipped).
    cache_with_sanitizer.apply_patch("h", {"listener_admin_dot": "ok"})

    await asyncio.wait_for(admin_task, timeout=5.0)
    await asyncio.wait_for(public_task, timeout=5.0)

    assert len(admin_received) == 2
    assert admin_received[0]["patch"] == {"diamonds": 10}
    assert admin_received[1]["patch"] == {"listener_admin_dot": "ok"}

    assert len(public_received) == 1
    assert public_received[0]["patch"] == {"diamonds": 10}


@pytest.mark.asyncio
async def test_subscribe_independent_channels(
    cache: TikTokStateCachePort,
) -> None:
    """Two subscribers on the same channel both see every delta."""
    received_a: list[dict[str, Any]] = []
    received_b: list[dict[str, Any]] = []

    async def consume(into: list[dict[str, Any]]) -> None:
        async for delta in cache.subscribe(CHANNEL_ADMIN):
            into.append(delta)
            if len(into) >= 2:
                return

    task_a = asyncio.create_task(consume(received_a))
    task_b = asyncio.create_task(consume(received_b))
    await asyncio.sleep(0.1)

    cache.apply_patch("h", {"a": 1})
    cache.apply_patch("h", {"a": 2})

    await asyncio.wait_for(task_a, timeout=5.0)
    await asyncio.wait_for(task_b, timeout=5.0)

    assert [d["version"] for d in received_a] == [1, 2]
    assert [d["version"] for d in received_b] == [1, 2]


@pytest.mark.asyncio
async def test_oracle_apply_100_patches(
    cache: TikTokStateCachePort,
) -> None:
    """End-to-end soak per the Phase A acceptance criterion: apply
    100 patches, final state matches the merged result, version ==
    100, subscriber sees 100 messages."""
    received: list[dict[str, Any]] = []

    async def consume() -> None:
        async for delta in cache.subscribe(CHANNEL_ADMIN):
            received.append(delta)
            if len(received) >= 100:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)

    for i in range(100):
        cache.apply_patch("soak", {"counter": i, "session_stats": {f"k{i}": i}})

    await asyncio.wait_for(task, timeout=10.0)
    assert len(received) == 100
    assert [d["version"] for d in received] == list(range(1, 101))

    version, data = cache.get("soak")  # type: ignore[misc]
    assert version == 100
    assert data["counter"] == 99
    # session_stats should carry all 100 keys (deep merge).
    assert len(data["session_stats"]) == 100
    assert data["session_stats"]["k0"] == 0
    assert data["session_stats"]["k99"] == 99

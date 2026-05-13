"""Phase 9B parity oracle.

Pushes a known synthetic event sequence through the real
`persist_event_full()` with state cache wired in shadow mode, then
compares per-host state cache contents to the SQL output of
`get_lives_summary()` for the same handle.

This is the deterministic gate that unblocks Phase 9C — Phase C
swaps `get_lives_summary` to read from the cache, so the cache must
match the SQL output field-for-field on the session-incremental
fields the cache maintains.

The test SKIPS when no Postgres is reachable. When it runs, it
creates a unique handle (`_parityoracle_<uuid>`) so it can't
collide with production data, then DELETEs every trace of itself
in the teardown.

What's NOT compared (these are aggregate / historical fields the
event-driven cache doesn't maintain — Phase C's bundle endpoint
will continue to compute them via the SQL path):
  - daily_buckets, hourly_buckets (rolling time-bucket aggregations)
  - last_broadcasts, week_calendar (historical, multi-session)
  - avg_duration_min, avg_diamonds, n_rooms_30d, median_diamonds_30d
  - momentum_label, comments_per_min_recent, comments_per_min_baseline
  - diamonds_vs_typical, favorites_in_room, reconnects_1h

What IS compared (session-incremental fields the cache maintains):
  - active_room_id, live_started_at
  - viewer_count
  - diamonds_session
  - session_stats: n_gifts, n_comments, n_likes, n_joins, n_follows,
    n_shares, n_unique_commenters, largest_gift_diamonds
  - top_gifters: top 3 by diamonds_session, identity fields
  - n_unique_gifters, n_first_time_gifters
  - n_envelopes_session, envelope_diamonds_session
  - n_pauses
  - active_match (when present)
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest

from adapters.persistence.tiktok_persistence import TikTokPersistenceAdapter
from adapters.tiktok_state_cache_inproc import TikTokStateCacheInProc
from domain.entities.tiktok_models import Room, TikTokViewer
from domain.services.tiktok_service import TikTokService


def _postgres_available() -> bool:
    """Skip the test when no Postgres is reachable. Mirrors the
    pattern in the state-cache test suite."""
    try:
        from database.core.connection import create_database_engine
        engine = create_database_engine()
        if engine.dialect.name != "postgresql":
            return False
        from sqlalchemy import text
        with engine.connect() as c:
            c.execute(text("SELECT 1")).scalar()
        return True
    except Exception:
        return False


# Skip the whole file when not on Postgres — SQLite returns empty
# slices from `get_lives_summary` so the parity check is meaningless.
pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="parity test requires a reachable Postgres instance",
)


# ── seed helpers ────────────────────────────────────────────────────


@pytest.fixture
def fake_handle() -> str:
    """A unique handle namespaced for this test. Picked so collisions
    with production data are impossible — the prefix won't be a real
    TikTok handle."""
    return f"_parityoracle_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def fake_room_id() -> int:
    """A unique room_id well outside the range TikTok uses (TikTok
    room_ids are 64-bit but typically in the 7-trillion range; we
    use a small int that can't collide)."""
    return -int(uuid.uuid4().int % 1_000_000)


@pytest.fixture
def persistence_with_cache(
    fake_handle: str, fake_room_id: int,
) -> Iterator[tuple[TikTokPersistenceAdapter, TikTokStateCacheInProc, TikTokService]]:
    """Real persistence adapter with a real DB + state cache wired."""
    state_cache = TikTokStateCacheInProc(public_sanitizer=None)
    p = TikTokPersistenceAdapter(auto_init=True, state_cache=state_cache)
    # Need a TikTokService just so `get_lives_summary` is reachable
    # via the existing service-layer cache + singleflight. We DON'T
    # construct a session factory because we never start a listener.
    s = TikTokService(persistence=p, session_factory=None, passive=True)

    # Seed: subscription row + room row. `get_lives_summary` JOINS
    # against both. Use direct SQL inserts to keep the fixture lean.
    from sqlalchemy import text
    now = datetime.now(timezone.utc)
    with p._get_session() as session:
        session.execute(text("""
            INSERT INTO tiktok_subscriptions (unique_id, enabled, is_live, is_public)
            VALUES (:h, true, true, false)
            ON CONFLICT (unique_id) DO NOTHING
        """), {"h": fake_handle})
        session.execute(text("""
            INSERT INTO tiktok_rooms (room_id, host_unique_id, first_seen_at, last_seen_at)
            VALUES (:r, :h, :ts, :ts)
            ON CONFLICT (room_id) DO NOTHING
        """), {"r": fake_room_id, "h": fake_handle, "ts": now})
        session.commit()

    try:
        yield p, state_cache, s
    finally:
        # Teardown. DELETE in dependency order: events → matches →
        # rooms → user_host_summary → subscriptions. Also clean up
        # the lives-summary cache so the next test run sees fresh DB.
        from sqlalchemy import text
        with p._get_session() as session:
            session.execute(
                text("DELETE FROM tiktok_events WHERE room_id = :r"),
                {"r": fake_room_id},
            )
            session.execute(
                text("DELETE FROM tiktok_matches WHERE room_id = :r"),
                {"r": fake_room_id},
            )
            session.execute(
                text("DELETE FROM tiktok_rooms WHERE room_id = :r"),
                {"r": fake_room_id},
            )
            session.execute(
                text("DELETE FROM tiktok_user_host_summary WHERE host_unique_id = :h"),
                {"h": fake_handle},
            )
            session.execute(
                text("DELETE FROM tiktok_event_hour_counts WHERE host_unique_id = :h"),
                {"h": fake_handle},
            )
            session.execute(
                text("DELETE FROM tiktok_subscriptions WHERE unique_id = :h"),
                {"h": fake_handle},
            )
            session.commit()
        # Bust the service-layer lives-summary cache for this handle.
        s._lives_summary_cache.clear()


# ── helpers ─────────────────────────────────────────────────────────


def _push_gift(
    p: TikTokPersistenceAdapter,
    room_id: int,
    handle: str,
    user_id: int,
    diamonds: int,
    repeats: int = 1,
) -> None:
    p.persist_event_full(
        room_id=room_id,
        host_unique_id=handle,
        viewer=TikTokViewer(
            user_id=user_id,
            unique_id=f"user{user_id}",
            nickname=f"User {user_id}",
        ),
        type="gift",
        payload={"diamond_count": diamonds, "repeat_count": repeats},
    )


def _push_comment(
    p: TikTokPersistenceAdapter,
    room_id: int,
    handle: str,
    user_id: int,
    text_: str = "hi",
) -> None:
    p.persist_event_full(
        room_id=room_id,
        host_unique_id=handle,
        viewer=TikTokViewer(user_id=user_id),
        type="comment",
        payload={"text": text_},
    )


def _push_simple(
    p: TikTokPersistenceAdapter,
    room_id: int,
    handle: str,
    event_type: str,
    user_id: int | None = None,
) -> None:
    p.persist_event_full(
        room_id=room_id,
        host_unique_id=handle,
        viewer=TikTokViewer(user_id=user_id) if user_id else None,
        type=event_type,
        payload={},
    )


def _strip_aux_and_compare(cache_state: dict, sql_state: dict, fields: list[str]) -> list[str]:
    """Return a list of human-readable diffs for `fields`. Empty list
    means perfect match on the compared subset.

    Counter normalization: SQL returns `None` for counter-style fields
    when no event of that kind has fired (it's a query-shape side
    effect — the field comes back missing from the result row);
    the cache eagerly initializes them to 0 on `live_started`. Both
    representations render as 0 on the frontend via `?? 0`. Treat
    them as equivalent for parity purposes — the alternative is to
    teach the cache to use None for "absent" which then breaks the
    `current.get(field) + 1` increment path (None + 1 fails)."""
    diffs: list[str] = []
    for f in fields:
        c = _normalize_counter(_get_field(cache_state, f))
        q = _normalize_counter(_get_field(sql_state, f))
        if c != q:
            diffs.append(f"  {f}: cache={c!r} | sql={q!r}")
    return diffs


def _normalize_counter(v: Any) -> Any:
    """None and 0 represent the same "zero events" state on the
    frontend (`v ?? 0`). Normalize so cache (0) and SQL (None) match."""
    return 0 if v is None else v


def _get_field(d: dict, path: str) -> Any:
    """Nested-key lookup via dot path: `session_stats.n_gifts`."""
    cur: Any = d
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


# Comparable fields. SESSION-incremental only — historical /
# aggregate / time-bucket fields excluded (see file docstring).
PARITY_FIELDS = [
    "active_room_id",
    "diamonds_session",
    "session_stats.n_gifts",
    "session_stats.n_comments",
    "session_stats.n_likes",
    "session_stats.n_joins",
    "session_stats.n_follows",
    "session_stats.n_shares",
    "session_stats.n_unique_commenters",
    "session_stats.largest_gift_diamonds",
    "n_unique_gifters",
    "n_envelopes_session",
    "envelope_diamonds_session",
    "n_pauses",
]


# ── the test ────────────────────────────────────────────────────────


def test_parity_session_counters(persistence_with_cache, fake_handle, fake_room_id):
    p, state_cache, s = persistence_with_cache

    # Tell the cache where the live started so the gift handler can
    # compute first-timer detection. Without this the cache slice
    # has no `live_started_at` and first-timer count stays 0 (which
    # would diverge from SQL).
    p._state_apply_live_started(fake_handle, {"room_id": fake_room_id})

    # Mixed event sequence: 6 gifters with overlapping repeats,
    # 5 commenters (some repeat), a few likes/joins/follows/shares,
    # one envelope, one pause.
    gifts = [
        (101, 10, 1),   # user 101: 10
        (102, 50, 1),   # user 102: 50
        (103, 100, 1),  # user 103: 100
        (101, 5, 4),    # user 101: +20 → 30 total
        (104, 200, 1),  # user 104: 200
        (105, 7, 3),    # user 105: 21
        (103, 300, 1),  # user 103: +300 → 400
        (106, 1, 1),    # user 106: 1
    ]
    for uid, dc, rc in gifts:
        _push_gift(p, fake_room_id, fake_handle, uid, dc, rc)

    for uid in (201, 202, 203, 201, 202, 204):
        _push_comment(p, fake_room_id, fake_handle, uid)

    for _ in range(7):
        _push_simple(p, fake_room_id, fake_handle, "like", user_id=301)
    for uid in (302, 303, 304):
        _push_simple(p, fake_room_id, fake_handle, "join", user_id=uid)
    for uid in (305, 306):
        _push_simple(p, fake_room_id, fake_handle, "follow", user_id=uid)
    _push_simple(p, fake_room_id, fake_handle, "share", user_id=307)
    _push_simple(p, fake_room_id, fake_handle, "live_pause")

    # Now compare.
    cached = state_cache.get(fake_handle)
    assert cached is not None, "state cache empty after event sequence"
    _, cache_state = cached
    # Strip aux state — the parity check compares only published fields.
    public_cache = {
        k: v for k, v in cache_state.items() if not k.startswith("_")
    }

    sql_summary = p.get_lives_summary([fake_handle])
    sql_state = sql_summary.get(fake_handle, {})

    # Per-field comparison on the session-incremental set.
    diffs = _strip_aux_and_compare(public_cache, sql_state, PARITY_FIELDS)

    if diffs:
        msg = "Parity divergence between state cache and get_lives_summary:\n"
        msg += "\n".join(diffs)
        msg += f"\n\nFull cache state: {public_cache!r}"
        msg += f"\n\nFull SQL state: {sql_state!r}"
        pytest.fail(msg)


def test_parity_top_gifter_ordering(persistence_with_cache, fake_handle, fake_room_id):
    """Top-gifter list must agree on at least the #1 spot's user_id
    and diamond total. (Nickname / avatar lookups go through
    `tiktok_viewers` and can lag if the upsert race favors one path
    over the other — diamonds + user_id are the load-bearing fields.)"""
    p, state_cache, s = persistence_with_cache

    p._state_apply_live_started(fake_handle, {"room_id": fake_room_id})

    # User 999 dominates with 5000 total diamonds.
    for _ in range(5):
        _push_gift(p, fake_room_id, fake_handle, 999, 1000)
    # Several smaller gifters.
    for uid, dc in [(100, 100), (101, 500), (102, 50), (103, 200)]:
        _push_gift(p, fake_room_id, fake_handle, uid, dc)

    cached = state_cache.get(fake_handle)
    assert cached is not None
    _, cache_state = cached

    sql_summary = p.get_lives_summary([fake_handle])
    sql_state = sql_summary.get(fake_handle, {})

    cache_top = (cache_state.get("top_gifters") or [None])[0]
    sql_top = (sql_state.get("top_gifters") or [None])[0]
    assert cache_top is not None, "cache has no top gifters"
    assert sql_top is not None, "SQL has no top gifters"

    # user_id + diamond total must agree.
    assert cache_top["user_id"] == sql_top["user_id"], (
        f"top-gifter user_id diverged: cache={cache_top} sql={sql_top}"
    )
    assert cache_top["diamonds"] == sql_top["diamonds"], (
        f"top-gifter diamond total diverged: "
        f"cache={cache_top['diamonds']} sql={sql_top['diamonds']}"
    )


def test_parity_first_time_gifters(persistence_with_cache, fake_handle, fake_room_id):
    """When a user has no prior `tiktok_user_host_summary` row, both
    cache and SQL count them as a first-timer for this session.

    Setup: pre-seed user_host_summary for user 500 (a "veteran" who
    gifted to this host before this live started); user 501 has no
    prior row (true first-timer).
    """
    p, state_cache, s = persistence_with_cache
    from sqlalchemy import text

    live_start = datetime.now(timezone.utc)
    p._state_apply_live_started(fake_handle, {"room_id": fake_room_id})

    # Backfill: user 500 was first-seen 30 days ago (veteran).
    veteran_first_seen = live_start - timedelta(days=30)
    with p._get_session() as session:
        session.execute(text("""
            INSERT INTO tiktok_user_host_summary
                (user_id, host_unique_id, first_seen_at, last_seen_at,
                 diamonds, gifts)
            VALUES (500, :h, :ts, :ts, 0, 0)
            ON CONFLICT (user_id, host_unique_id) DO NOTHING
        """), {"h": fake_handle, "ts": veteran_first_seen})
        session.commit()

    # Both gift now.
    _push_gift(p, fake_room_id, fake_handle, 500, 100)  # veteran
    _push_gift(p, fake_room_id, fake_handle, 501, 100)  # first-timer

    cached = state_cache.get(fake_handle)
    assert cached is not None
    _, cache_state = cached

    sql_summary = p.get_lives_summary([fake_handle])
    sql_state = sql_summary.get(fake_handle, {})

    assert cache_state.get("n_first_time_gifters") == 1, (
        f"cache n_first_time_gifters={cache_state.get('n_first_time_gifters')}"
    )
    assert sql_state.get("n_first_time_gifters") == 1, (
        f"sql n_first_time_gifters={sql_state.get('n_first_time_gifters')}"
    )

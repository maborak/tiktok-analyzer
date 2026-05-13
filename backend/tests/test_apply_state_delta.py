"""Phase 9B unit tests — per-event-type field mapping in
`TikTokPersistenceAdapter._apply_state_delta`.

Strategy: directly drive the individual `_state_apply_*` helpers with
synthetic events against an in-process state cache, then assert the
resulting cache state matches the expected shape. We don't go through
`record_event()` here — that would require a full DB session and the
upserts. The dispatch logic is exercised separately via a small
parametrized smoke test.

The first-timer detection logic that calls into `tiktok_user_host_summary`
is exercised via a mock session; the parity oracle test
(`test_state_cache_vs_sql_parity.py`) hits the real DB.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from adapters.persistence.tiktok_persistence import TikTokPersistenceAdapter
from adapters.tiktok_state_cache_inproc import TikTokStateCacheInProc


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def state_cache() -> TikTokStateCacheInProc:
    """Bare in-process state cache without a sanitizer — admin-side
    fields land in the cache untouched. Public sanitization is
    covered by the Phase 9A test suite."""
    return TikTokStateCacheInProc(public_sanitizer=None)


@pytest.fixture
def persistence(state_cache):
    """A persistence adapter with `state_cache` wired but **no DB**
    initialized — we never call methods that touch the DB in these
    unit tests, just the state-cache helpers. `auto_init=False`
    skips the engine bootstrap."""
    return TikTokPersistenceAdapter(auto_init=False, state_cache=state_cache)


class _NoopSession:
    """Stand-in for the SQLAlchemy session passed into
    `_apply_state_delta`. The simple event handlers don't read the
    session; only the gift handler does (for the first-timer lookup),
    and that's covered by a separate session-mock fixture."""

    def execute(self, *args, **kwargs):
        raise AssertionError(
            "this test path should not hit the session — the simple "
            "events under test don't query the DB"
        )


@pytest.fixture
def s_noop() -> _NoopSession:
    return _NoopSession()


# ── simple counter events ───────────────────────────────────────────


@pytest.mark.parametrize(
    "event_type,counter_key",
    [
        ("like", "n_likes"),
        ("join", "n_joins"),
        ("follow", "n_follows"),
        ("share", "n_shares"),
    ],
)
def test_simple_counter_increments(
    persistence, state_cache, event_type, counter_key,
):
    persistence._state_apply_simple_counter("alice", event_type)
    persistence._state_apply_simple_counter("alice", event_type)
    persistence._state_apply_simple_counter("alice", event_type)
    _, data = state_cache.get("alice")
    assert data["session_stats"][counter_key] == 3
    # _last_event_at recorded
    assert "_last_event_at" in data


def test_simple_counter_isolates_per_host(persistence, state_cache):
    persistence._state_apply_simple_counter("alice", "like")
    persistence._state_apply_simple_counter("alice", "like")
    persistence._state_apply_simple_counter("bob", "like")
    assert state_cache.get("alice")[1]["session_stats"]["n_likes"] == 2
    assert state_cache.get("bob")[1]["session_stats"]["n_likes"] == 1


def test_simple_counter_does_not_clobber_other_counters(
    persistence, state_cache,
):
    persistence._state_apply_simple_counter("alice", "like")
    persistence._state_apply_simple_counter("alice", "join")
    stats = state_cache.get("alice")[1]["session_stats"]
    assert stats["n_likes"] == 1
    assert stats["n_joins"] == 1


# ── envelope ────────────────────────────────────────────────────────


def test_envelope_accumulates(persistence, state_cache):
    persistence._state_apply_envelope("alice", {"diamonds": 50})
    persistence._state_apply_envelope("alice", {"diamonds": 75})
    persistence._state_apply_envelope("alice", {})  # free-promo envelope
    _, data = state_cache.get("alice")
    assert data["n_envelopes_session"] == 3
    assert data["envelope_diamonds_session"] == 125


def test_envelope_reads_diamond_count_alias(persistence, state_cache):
    """Envelope payloads sometimes use `diamond_count` instead of
    `diamonds`. The handler should accept either."""
    persistence._state_apply_envelope("alice", {"diamond_count": 20})
    _, data = state_cache.get("alice")
    assert data["envelope_diamonds_session"] == 20


# ── pause ───────────────────────────────────────────────────────────


def test_pause_increments_and_resets_age(persistence, state_cache):
    persistence._state_apply_pause("alice")
    _, data = state_cache.get("alice")
    assert data["n_pauses"] == 1
    assert data["last_pause_age_s"] == 0
    assert "_last_pause_at" in data
    persistence._state_apply_pause("alice")
    assert state_cache.get("alice")[1]["n_pauses"] == 2


# ── poll ────────────────────────────────────────────────────────────


def test_poll_sets_active_poll(persistence, state_cache):
    persistence._state_apply_poll("alice", {
        "title": "Best gift?",
        "poll_id": "p-12345",
    })
    _, data = state_cache.get("alice")
    assert data["active_poll"] == {
        "title": "Best gift?",
        "poll_id": "p-12345",
        "fresh_age_s": 0,
    }
    assert "_active_poll_at" in data


# ── battle_* ────────────────────────────────────────────────────────


def test_battle_begin_sets_active_match(persistence, state_cache):
    persistence._state_apply_battle_begin("alice", {
        "match_id": 42,
        "battle_id": "b-abc",
        "opponents": [
            {"user_id": "1", "score": 0},
            {"user_id": "2", "score": 0},
        ],
    })
    _, data = state_cache.get("alice")
    assert data["active_match"]["match_id"] == 42
    assert len(data["active_match"]["opponents"]) == 2


def test_battle_progress_replaces_opponents_wholesale(
    persistence, state_cache,
):
    """`opponents` is a list, deep-merge replaces lists wholesale.
    A 3-opponent update doesn't accidentally keep stale 4th-opponent."""
    persistence._state_apply_battle_begin("alice", {
        "match_id": 1,
        "battle_id": "b",
        "opponents": [
            {"user_id": "a", "score": 0},
            {"user_id": "b", "score": 0},
            {"user_id": "c", "score": 0},
        ],
    })
    persistence._state_apply_battle_progress("alice", {
        "opponents": [
            {"user_id": "a", "score": 100},
            {"user_id": "b", "score": 250},
        ],
    })
    opps = state_cache.get("alice")[1]["active_match"]["opponents"]
    assert len(opps) == 2
    assert opps[0]["score"] == 100
    assert opps[1]["score"] == 250


def test_battle_progress_preserves_match_id(persistence, state_cache):
    """Deep merge: `opponents` replaces, `match_id` / `battle_id` keep."""
    persistence._state_apply_battle_begin("alice", {
        "match_id": 99,
        "battle_id": "b-99",
        "opponents": [{"user_id": "x", "score": 0}],
    })
    persistence._state_apply_battle_progress("alice", {
        "opponents": [{"user_id": "x", "score": 500}],
    })
    am = state_cache.get("alice")[1]["active_match"]
    assert am["match_id"] == 99
    assert am["battle_id"] == "b-99"
    assert am["opponents"][0]["score"] == 500


def test_battle_end_clears_match(persistence, state_cache):
    persistence._state_apply_battle_begin("alice", {
        "match_id": 1, "battle_id": "b", "opponents": [],
    })
    persistence._state_apply_battle_end("alice")
    assert state_cache.get("alice")[1]["active_match"] is None


# ── viewer_count ────────────────────────────────────────────────────


def test_viewer_count_appends_history(persistence, state_cache):
    for n in [10, 12, 15, 11]:
        persistence._state_apply_viewer_count("alice", {"viewer_count": n})
    _, data = state_cache.get("alice")
    assert data["viewer_count"] == 11
    assert data["viewer_history"] == [10, 12, 15, 11]


def test_viewer_count_caps_history_at_30(persistence, state_cache):
    for n in range(40):
        persistence._state_apply_viewer_count("alice", {"viewer_count": n})
    history = state_cache.get("alice")[1]["viewer_history"]
    assert len(history) == 30
    # Oldest dropped, newest preserved.
    assert history[0] == 10
    assert history[-1] == 39


def test_viewer_count_missing_payload_is_noop(persistence, state_cache):
    persistence._state_apply_viewer_count("alice", {})
    # Nothing was written — cache stays empty for this host.
    assert state_cache.get("alice") is None


# ── comment ─────────────────────────────────────────────────────────


def test_comment_tracks_unique_commenters(persistence, state_cache):
    persistence._state_apply_comment(
        "alice", {}, SimpleNamespace(user_id=1),
    )
    persistence._state_apply_comment(
        "alice", {}, SimpleNamespace(user_id=2),
    )
    persistence._state_apply_comment(
        "alice", {}, SimpleNamespace(user_id=1),  # same user again
    )
    _, data = state_cache.get("alice")
    assert data["session_stats"]["n_comments"] == 3
    assert data["session_stats"]["n_unique_commenters"] == 2


def test_comment_anonymous_still_increments_count(persistence, state_cache):
    """Comments without a resolvable user_id still bump `n_comments`
    but do not contribute to `n_unique_commenters`."""
    persistence._state_apply_comment("alice", {}, None)
    persistence._state_apply_comment("alice", {}, None)
    _, data = state_cache.get("alice")
    assert data["session_stats"]["n_comments"] == 2
    assert data["session_stats"]["n_unique_commenters"] == 0


# ── live_started / live_ended ───────────────────────────────────────


def test_live_started_resets_session_state(persistence, state_cache):
    """Start a session, accumulate some gift counters, restart —
    counters reset; aux state cleared. Dict-valued aux fields read
    back as `None` after reset (deep-merge limitation; downstream
    readers treat None == {} via `or {}`)."""
    # Pre-existing dirty state from a prior session.
    state_cache.set("alice", version=10, data={
        "diamonds_session": 999,
        "session_stats": {"n_gifts": 50},
        "_gifter_totals": {"1": 100, "2": 200},
    })
    persistence._state_apply_live_started("alice", {
        "room_id": 12345,
    })
    _, data = state_cache.get("alice")
    assert data["active_room_id"] == "12345"
    assert data["diamonds_session"] == 0
    assert data["session_stats"]["n_gifts"] == 0
    assert data["top_gifters"] == []
    assert data["_gifter_totals"] is None


def test_live_ended_archives_to_last_broadcasts(
    persistence, state_cache,
):
    """After live_ended, `last_broadcasts[0]` carries the session
    snapshot and session fields are cleared."""
    state_cache.set("alice", version=1, data={
        "active_room_id": "9999",
        "live_started_at": "2026-05-13T10:00:00+00:00",
        "diamonds_session": 12345,
        "session_stats": {"n_gifts": 50, "n_comments": 200},
    })
    persistence._state_apply_live_ended("alice", {
        "duration_min": 90,
        "peak_viewers": 500,
    })
    _, data = state_cache.get("alice")
    assert data["active_room_id"] is None
    assert data["diamonds_session"] == 0
    lb = data["last_broadcasts"][0]
    assert lb["room_id"] == "9999"
    assert lb["diamonds"] == 12345
    assert lb["n_gifts"] == 50
    assert lb["duration_min"] == 90
    assert lb["peak_viewers"] == 500


# ── gift (the big one) ──────────────────────────────────────────────


class _DBSessionMock:
    """Mock for the SQLAlchemy session that the gift handler uses to
    look up `tiktok_viewers` (top-gifter nickname/avatar) and
    `tiktok_user_host_summary` (first-timer detection). Each call to
    `execute()` returns a configurable result."""

    def __init__(self) -> None:
        # Each entry: (sql_substr, rows_to_return)
        self._handlers: list[tuple[str, list[tuple]]] = []

    def expect(self, sql_substr: str, rows: list[tuple]) -> None:
        self._handlers.append((sql_substr, rows))

    def execute(self, query, params=None):
        sql = str(query)
        for substr, rows in self._handlers:
            if substr in sql:
                return _FakeResult(rows)
        return _FakeResult([])


class _FakeResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


def test_gift_accumulates_diamonds(persistence, state_cache):
    s = _DBSessionMock()
    persistence._state_apply_gift(s, "alice", {
        "diamond_count": 10, "repeat_count": 5,
    }, viewer=SimpleNamespace(user_id=42))
    # Verify via two ways: positional and keyword
    _, data = state_cache.get("alice")
    assert data["diamonds_session"] == 50
    assert data["session_stats"]["n_gifts"] == 1
    assert data["session_stats"]["largest_gift_diamonds"] == 50


def test_gift_rebuilds_top_3(persistence, state_cache):
    """Top-3 ordered by cumulative diamonds, descending."""
    s = _DBSessionMock()
    s.expect("FROM tiktok_viewers", [
        (1, "alpha", "https://a.example/avatar.jpg"),
        (2, "beta", "https://b.example/avatar.jpg"),
        (3, "gamma", "https://c.example/avatar.jpg"),
        (4, "delta", "https://d.example/avatar.jpg"),
    ])
    # 4 different gifters, varying amounts
    gifts = [
        (1, 100), (2, 50), (3, 200), (4, 10),
        (1, 50),   # alpha total 150
        (3, 300),  # gamma total 500
    ]
    for uid, value in gifts:
        persistence._state_apply_gift(
            s, "alice", {"diamond_count": value, "repeat_count": 1},
            viewer=SimpleNamespace(user_id=uid),
        )
    _, data = state_cache.get("alice")
    top = data["top_gifters"]
    assert len(top) == 3
    # 1st: gamma (500), 2nd: alpha (150), 3rd: beta (50)
    assert top[0]["diamonds"] == 500
    assert top[0]["nickname"] == "gamma"
    assert top[1]["diamonds"] == 150
    assert top[1]["nickname"] == "alpha"
    assert top[2]["diamonds"] == 50
    assert top[2]["nickname"] == "beta"


def test_gift_distinct_gifters_count(persistence, state_cache):
    s = _DBSessionMock()
    s.expect("FROM tiktok_viewers", [])
    for uid, value in [(1, 10), (2, 10), (3, 10), (1, 20)]:
        persistence._state_apply_gift(
            s, "alice", {"diamond_count": value, "repeat_count": 1},
            viewer=SimpleNamespace(user_id=uid),
        )
    assert state_cache.get("alice")[1]["n_unique_gifters"] == 3


def test_gift_zero_value_is_skipped_for_top_gifters(
    persistence, state_cache,
):
    """Diamondless gifts only bump `_last_event_at` — no other state."""
    s = _DBSessionMock()
    persistence._state_apply_gift(
        s, "alice", {"diamond_count": 0, "repeat_count": 1},
        viewer=SimpleNamespace(user_id=42),
    )
    _, data = state_cache.get("alice")
    assert "diamonds_session" not in data
    assert "_last_event_at" in data


def test_gift_first_timer_detection(persistence, state_cache):
    """When user_host_summary.first_seen_at >= live_started_at,
    increment n_first_time_gifters. Second gift from same user
    doesn't double-count."""
    live_start = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
    state_cache.set("alice", version=1, data={
        "live_started_at": live_start.isoformat(),
        "active_room_id": "1",
    })

    # Mock: user 7's first_seen_at is right at live start → first-timer.
    s = _DBSessionMock()
    s.expect("FROM tiktok_user_host_summary", [
        (live_start + timedelta(seconds=5),),
    ])
    s.expect("FROM tiktok_viewers", [
        (7, "newbie", None),
    ])
    persistence._state_apply_gift(
        s, "alice", {"diamond_count": 10, "repeat_count": 1},
        viewer=SimpleNamespace(user_id=7),
    )
    assert state_cache.get("alice")[1]["n_first_time_gifters"] == 1

    # Second gift from user 7 — same lookups would say "still first-time"
    # but the aux `_first_time_user_ids` set prevents double-counting.
    persistence._state_apply_gift(
        s, "alice", {"diamond_count": 5, "repeat_count": 1},
        viewer=SimpleNamespace(user_id=7),
    )
    assert state_cache.get("alice")[1]["n_first_time_gifters"] == 1


def test_gift_returning_user_not_counted(persistence, state_cache):
    """A user whose first_seen_at is BEFORE live_started_at is a
    returning user; n_first_time_gifters stays at 0."""
    live_start = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
    state_cache.set("alice", version=1, data={
        "live_started_at": live_start.isoformat(),
        "active_room_id": "1",
    })

    s = _DBSessionMock()
    # user 8 has been gifting for weeks — first_seen well before live_start.
    s.expect("FROM tiktok_user_host_summary", [
        (live_start - timedelta(days=30),),
    ])
    s.expect("FROM tiktok_viewers", [(8, "veteran", None)])
    persistence._state_apply_gift(
        s, "alice", {"diamond_count": 10, "repeat_count": 1},
        viewer=SimpleNamespace(user_id=8),
    )
    assert state_cache.get("alice")[1]["n_first_time_gifters"] == 0


# ── dispatcher smoke ────────────────────────────────────────────────


def test_dispatcher_routes_simple_events(persistence, state_cache):
    """End-to-end: `_apply_state_delta` itself (the dispatcher)
    forwards to the right helper based on `event_type`. Spot-check
    a handful of types."""
    persistence._apply_state_delta(
        None, "h", event_type="like", payload={},
    )
    persistence._apply_state_delta(
        None, "h", event_type="comment", payload={},
        viewer=SimpleNamespace(user_id=99),
    )
    persistence._apply_state_delta(
        None, "h", event_type="envelope", payload={"diamonds": 100},
    )
    _, data = state_cache.get("h")
    assert data["session_stats"]["n_likes"] == 1
    assert data["session_stats"]["n_comments"] == 1
    assert data["envelope_diamonds_session"] == 100


def test_dispatcher_unknown_event_only_touches_last_event_at(
    persistence, state_cache,
):
    """Unknown event types bump `_last_event_at` (aux-only) so the
    tick task's "is this host idle?" check works, but they don't
    leak anything to subscribers (aux-only patch is silent)."""
    persistence._apply_state_delta(
        None, "h", event_type="some_unknown_type", payload={},
    )
    _, data = state_cache.get("h")
    assert data == {"_last_event_at": data["_last_event_at"]}


def test_dispatcher_off_mode_is_noop():
    """When `state_cache=None`, the dispatcher is fully inert.
    This is the default Phase B mode (`PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH=off`)."""
    p = TikTokPersistenceAdapter(auto_init=False, state_cache=None)
    p._apply_state_delta(None, "h", event_type="like", payload={})
    # Nothing should raise — no state cache to write to.


def test_dispatcher_swallows_helper_errors(persistence, state_cache):
    """A bug in a helper must NOT break the persist path. The
    dispatcher catches + logs."""
    # Force a helper-internal error: viewer_count with non-int.
    persistence._apply_state_delta(
        None, "h",
        event_type="viewer_count_update",
        payload={"viewer_count": "not-a-number"},
    )
    # Cache may or may not have the host — what matters is we didn't raise.

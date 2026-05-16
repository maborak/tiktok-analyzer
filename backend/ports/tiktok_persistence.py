"""Port for TikTok-bot persistence operations."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from domain.entities.tiktok_models import (
    Match,
    Subscription,
    Room,
    TikTokViewer,
    TikTokEvent,
    TikTokGift,
)


class TikTokPersistencePort(ABC):
    """Storage operations for the TikTok-bot module."""

    # ── Subscriptions ────────────────────────────────────────────────

    @abstractmethod
    def list_subscriptions(self, *, enabled_only: bool = False) -> list[Subscription]:
        """All known subscriptions, optionally filtered to enabled."""

    @abstractmethod
    def get_subscriptions_by_user_ids(self, user_ids: list[int]) -> dict[int, Subscription]:
        """Targeted lookup keyed by `profile_user_id`. Used by opponent
        enrichment so we don't full-scan tiktok_subscriptions per request."""

    @abstractmethod
    def get_subscription(self, unique_id: str) -> Optional[Subscription]:
        """Look up a subscription by handle."""

    @abstractmethod
    def upsert_subscription(self, unique_id: str, *, enabled: bool = True) -> Subscription:
        """Insert or update by unique_id; return the resulting row."""

    @abstractmethod
    def set_subscription_enabled(self, unique_id: str, enabled: bool) -> Optional[Subscription]:
        """Toggle the enabled flag. Returns the updated row, or None if missing."""

    @abstractmethod
    def set_subscription_public(self, unique_id: str, is_public: bool) -> bool:
        """Toggle the `is_public` flag. Returns True if the row was found
        and updated, False otherwise."""

    @abstractmethod
    def list_public_subscriptions(self) -> list[Subscription]:
        """Subscriptions where `is_public=True`, ordered by `unique_id`.
        Drives the unauthenticated /public/tiktok/lives endpoint."""

    @abstractmethod
    def delete_subscription(self, unique_id: str) -> bool:
        """Hard-delete the subscription row. Returns True if a row was deleted."""

    @abstractmethod
    def list_subscriptions_with_stale_profiles(
        self, *, stale_after_seconds: int = 3600
    ) -> list[Subscription]:
        """Subscriptions whose profile_refreshed_at is older than
        `stale_after_seconds` (or never refreshed). Used by the periodic
        refresher."""

    @abstractmethod
    def update_subscription_profile(
        self, unique_id: str, *, profile: dict[str, Any], error: str | None = None
    ) -> None:
        """Persist profile-cache fields. `profile` is the dict shape
        returned by `fetch_public_profile`; only known keys are written.
        Always bumps `profile_refreshed_at` to now."""

    # ── Rooms ────────────────────────────────────────────────────────

    @abstractmethod
    def upsert_room(self, room: Room) -> None:
        """Insert or update a room by room_id; updates last_seen_at."""

    @abstractmethod
    def get_room(self, room_id: int) -> Optional[Room]:
        ...

    @abstractmethod
    def list_rooms_for_host(self, host_unique_id: str, *, limit: int = 50) -> list[Room]:
        ...

    @abstractmethod
    def room_totals(
        self,
        room_ids: list[int],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[int, dict[str, int]]:
        """Returns `{room_id: {diamonds, matches, likes}}` rollups for
        each input id. Drives per-broadcast metadata in the dropdown.

        Optional `since` / `until` clip gift / match / like
        aggregations to a UTC window — used by the day-picker modal so
        a broadcast that spans midnight only contributes the slice on
        the selected day. Likes (cumulative counter) are reported as
        the increment inside the window."""

    @abstractmethod
    def host_calendar(
        self,
        host_unique_id: str,
        *,
        since: datetime,
        until: datetime,
        tz: str = "UTC",
    ) -> list[dict[str, Any]]:
        """Per-day broadcast counts for one host between [since, until],
        bucketed in IANA zone `tz` (default UTC)."""

    # ── Viewers ──────────────────────────────────────────────────────

    @abstractmethod
    def upsert_viewer(self, viewer: TikTokViewer) -> None:
        """Insert or update a viewer by user_id; updates last_seen_at."""

    @abstractmethod
    def get_viewer_by_unique_id(self, unique_id: str) -> Optional[TikTokViewer]:
        """Most recently-seen viewer matching a @handle. Useful as a
        cache fallback when a TikTok lookup can't reach TikTok itself."""

    @abstractmethod
    def get_viewers_by_ids(self, user_ids: list[int]) -> dict[int, TikTokViewer]:
        """Look up viewers by user_id. Useful for filling in missing
        avatar/nickname on match opponents (we may have collected the
        viewer from earlier comment events even if anchor_info had no
        avatar)."""

    # ── Gifts (catalog) ──────────────────────────────────────────────

    @abstractmethod
    def upsert_gift(self, gift: TikTokGift) -> None:
        """Insert or update a gift by gift_id; refreshes name + diamond
        value + icon (TikTok rebrands gifts occasionally)."""

    @abstractmethod
    def list_gifts(self, *, limit: int = 200) -> list[TikTokGift]:
        """All known gifts ordered by diamond value desc."""

    # ── Matches ──────────────────────────────────────────────────────

    @abstractmethod
    def open_match(
        self,
        *,
        room_id: int,
        battle_id: int,
        opponents: list[dict[str, Any]] | None = None,
        scores: dict[str, int] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Match:
        """Insert a new match row, or return the existing one if (room_id,
        battle_id) is already open. Idempotent: safe to call on every
        battle_start event."""

    @abstractmethod
    def update_match(
        self,
        match_id: int,
        *,
        scores: dict[str, int] | None = None,
        opponents: list[dict[str, Any]] | None = None,
        opponent_scores: list[dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """Refresh scores/opponents/settings and bump last_seen_at.
        opponent_scores is [{user_id, score}, …] — merged into the
        existing opponents list by user_id (each entry's `score` field
        gets updated)."""

    @abstractmethod
    def close_match(
        self,
        match_id: int,
        *,
        winner_user_id: int | None = None,
    ) -> None:
        """Mark ended_at and optionally record the winner."""

    @abstractmethod
    def get_hosts_with_active_room(self, handles: list[str]) -> set[str]:
        """Subset of `handles` that currently have an active room row
        (ended_at IS NULL AND last_seen_at > NOW() - 5 min). Returns
        lowercased handles. Used by snapshot/overlay paths to gate
        cached session state against SQL authority."""

    @abstractmethod
    def get_active_match(self, room_id: int) -> Match | None:
        """The currently-open match for a room (ended_at IS NULL), if any."""

    @abstractmethod
    def list_matches(
        self,
        *,
        room_id: int | None = None,
        host_unique_id: str | None = None,
        limit: int = 50,
    ) -> list[Match]:
        """Match history, most recent first. Filter by room or by host."""

    @abstractmethod
    def match_diamonds_totals(
        self, match_ids: list[int]
    ) -> dict[int, int]:
        """Sum of (diamond_count × repeat_count) for gift events tagged
        with each match_id. Returns {match_id: total_diamonds}, missing
        keys default to 0."""

    # ── Events ───────────────────────────────────────────────────────

    @abstractmethod
    def insert_event(
        self,
        *,
        room_id: int,
        user_id: int | None,
        type: str,
        payload: dict[str, Any] | None,
        match_id: int | None = None,
    ) -> int:
        """Append one event row, return the inserted id.
        match_id is set when the room was in an active battle at fire-time."""

    @abstractmethod
    def persist_event_full(
        self,
        *,
        room_id: int,
        host_unique_id: str | None,
        viewer: TikTokViewer | None,
        type: str,
        payload: dict[str, Any] | None,
        match_id: int | None = None,
        push_room_seen: bool = True,
        push_viewer_seen: bool = True,
    ) -> int:
        """One-transaction upsert(room) + upsert(viewer) + insert(event).
        Cuts pool pressure to 1 session per event vs. 3 with the older
        per-call pattern, and uses ON CONFLICT to avoid races on the
        viewer/room unique keys.

        push_*_seen=False skips bumping last_seen_at for that side (the
        service throttles updates to ~1/30s instead of every event)."""

    @abstractmethod
    def list_events(
        self,
        room_id: int,
        *,
        type: str | None = None,
        limit: int = 200,
        before_id: int | None = None,
    ) -> list[TikTokEvent]:
        """Most-recent-first event listing, paged via before_id."""

    @abstractmethod
    def count_events(
        self,
        *,
        host_unique_id: str | None = None,
        room_id: int | None = None,
        room_ids: list[int] | None = None,
        user_id: int | None = None,
        match_id: int | None = None,
        type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
    ) -> int:
        """Counterpart to `search_events` — same filter surface, returns
        the total row count. Used by paginated UIs that need the total
        ("Comments (1,247)") alongside the current page."""

    @abstractmethod
    def search_events(
        self,
        *,
        host_unique_id: str | None = None,
        room_id: int | None = None,
        room_ids: list[int] | None = None,
        user_id: int | None = None,
        match_id: int | None = None,
        type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
        limit: int = 200,
        before_id: int | None = None,
        offset: int = 0,
    ) -> list[TikTokEvent]:
        """Cross-room/cross-creator event search with filters and pagination.
        `user_id` filters by the originating viewer (e.g. gifts from one
        top gifter); `match_id` scopes to events tagged with that PK
        battle (for the per-match events modal). `offset` enables
        page-by-page pagination — `before_id` (cursor) and `offset` are
        independent and can be used together."""

    # ── Aggregations (stats / dashboard) ─────────────────────────────

    @abstractmethod
    def room_event_counts_by_type(
        self,
        room_id: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, int]:
        """Per-event-type counts for a room (optionally bounded by ts window)."""

    @abstractmethod
    def room_top_gifters(
        self,
        room_id: int | list[int],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 10,
        offset: int = 0,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        """Top gifters (by total diamonds) for a room, optionally bounded by
        a ts window. Both `since` and `until` are inclusive lower / exclusive
        upper bounds on `tiktok_events.ts`. `q` substring-matches nickname
        or unique_id (case-insensitive).

        Returns: [{user_id, unique_id, nickname, diamonds, gifts, comments}, …]
        Aggregation runs in SQL when the dialect supports JSON ops (Postgres
        with JSONB), falling back to a Python pass on SQLite.
        """

    @abstractmethod
    def count_room_gifters(
        self,
        room_id: int | list[int],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
    ) -> int:
        """Distinct gifter count (users with diamonds_total > 0) in the
        same window/filter shape as `room_top_gifters`. Used to drive
        server-side pagination."""

    @abstractmethod
    def common_gifters(
        self,
        *,
        min_hosts: int = 2,
        limit: int = 25,
        offset: int = 0,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cross-creator gifter leaderboard: viewers who have gifted to
        ≥ `min_hosts` distinct hosts. Each item carries the totals plus
        a per-host breakdown (sorted desc by diamonds)."""

    @abstractmethod
    def count_common_gifters(
        self,
        *,
        min_hosts: int = 2,
        q: str | None = None,
    ) -> int:
        """Counterpart to `common_gifters` for paginated UIs."""

    @abstractmethod
    def common_gifter_detail(
        self,
        user_id: int,
        *,
        rooms_per_host: int = 5,
        gifts_per_host: int = 5,
    ) -> dict[str, Any]:
        """Deep-analysis payload for one viewer's gifting across every
        host: identity + totals + per-host top gift kinds + per-host
        recent rooms + per-host comment count. Powers the modal that
        opens from the Common Gifters list."""

    @abstractmethod
    def add_favorite_gifter(
        self,
        user_id: int,
        *,
        note: str | None = None,
        notify_gift: bool | None = None,
        notify_comment: bool | None = None,
        notify_join: bool | None = None,
    ) -> None: ...

    @abstractmethod
    def remove_favorite_gifter(self, user_id: int) -> bool: ...

    @abstractmethod
    def is_favorite_gifter(self, user_id: int) -> bool: ...

    @abstractmethod
    def list_favorite_gifter_ids(self) -> list[int]: ...

    @abstractmethod
    def list_favorite_gifter_notify_config(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def list_favorite_gifters_enriched(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def room_top_recipients(
        self,
        room_id: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Aggregate gift events by RECIPIENT (`payload->'to_user'->>'user_id'`)
        rather than by sender. In a multi-guest live or PK battle this answers
        "who got how many diamonds" (host vs each guest). Pre-`to_user`
        rows are ignored — the payload key was added later, so older
        broadcasts will return an empty list.

        Returns: [{user_id, unique_id, nickname, diamonds, gifts}, …]
        """

    @abstractmethod
    def host_event_counts_by_type(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, dict[str, int]]:
        """Per-host events totals grouped by type for the dashboard.
        Returns: {host_unique_id: {event_type: count}}
        """

    @abstractmethod
    def host_event_buckets(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        bucket_seconds: int = 3600,
        tz: str = "UTC",
    ) -> list[dict[str, Any]]:
        """Time-bucketed totals across all monitored creators, with
        bucket boundaries truncated in IANA zone `tz` (default UTC).
        Returns: [{bucket: ISO8601, host_unique_id, type, count}, …]
        """

    @abstractmethod
    def room_event_buckets(
        self,
        room_id: int | list[int],
        *,
        since: datetime,
        until: datetime,
        bucket_seconds: int,
    ) -> dict[str, Any]:
        """SQL-side bucketed event counts + diamond totals for one or
        more rooms, bounded by `[since, until]` and bucketed by
        `bucket_seconds`. Pass a list of room_ids to aggregate across
        multiple broadcasts (the calendar's day-view feature).

        Replaces the Python-side bucketing in ``get_room_stats`` which
        was capped at the latest 10 000 events per room — for long /
        heavy broadcasts that truncated everything older than the most
        recent ~30 minutes, so the headline ``diamonds_total`` and the
        chart series both understated reality.

        Returns:
            ``{
                "starts": [iso, ...],          # one per bucket (since-aligned)
                "by_type": {type: [int, ...]}, # counts per bucket per type
                "diamonds": [int, ...],         # diamond_count*repeat sum
                "diamonds_total": int,          # SUM across the whole window
            }``
        """

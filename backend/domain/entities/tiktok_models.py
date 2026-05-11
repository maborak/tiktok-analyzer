"""Domain entities for the TikTok-bot module.

Plain dataclasses + enums; no framework or DB imports. These are the
contract types passed across the port boundary between routes/services
and adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SubscriptionState(str, Enum):
    """Runtime connection state of a Subscription's TikTokLive client."""

    DISABLED = "DISABLED"
    DISCONNECTED = "DISCONNECTED"   # enabled but not currently connected (e.g. host offline)
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    LIVE_ENDED = "LIVE_ENDED"
    ERROR = "ERROR"


class TikTokEventType(str, Enum):
    """Discriminator for TikTokEvent.type. Free-form is allowed (we use
    str everywhere) — this enum just documents the canonical names."""

    COMMENT = "comment"
    GIFT = "gift"
    LIKE = "like"
    FOLLOW = "follow"
    SHARE = "share"
    JOIN = "join"
    VIEWER_COUNT = "viewer_count"
    LIVE_END = "live_end"
    ROOM_INFO = "room_info"
    SUBSCRIBE = "subscribe"
    MATCH_START = "match_start"
    MATCH_UPDATE = "match_update"
    MATCH_END = "match_end"


@dataclass
class Subscription:
    """A monitored @handle. Persisted in tiktok_subscriptions."""

    id: int | None
    unique_id: str           # the TikTok @handle (without leading @)
    enabled: bool = True
    # Cached public-profile fields (populated by the periodic refresher).
    profile_user_id: int | None = None
    sec_uid: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    verified: bool | None = None
    private: bool | None = None
    follower_count: int | None = None
    following_count: int | None = None
    video_count: int | None = None
    like_count: int | None = None
    profile_refreshed_at: datetime | None = None
    # Centralized live-status cache fields.
    is_live: bool | None = None
    live_checked_at: datetime | None = None
    current_room_id: int | None = None
    profile_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Room:
    """A TikTok live room we've ever observed."""

    room_id: int
    host_unique_id: str | None = None
    host_user_id: int | None = None
    title: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass
class TikTokViewer:
    """A TikTok platform user we've seen in any monitored room.
    Distinct from the framework's own User entity (auth)."""

    user_id: int
    unique_id: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass
class TikTokEvent:
    """One row per recorded event (comment / gift / like / etc).
    payload holds type-specific data as JSON-safe dict.
    match_id is set when the room was in an active PK battle at fire-time;
    used to filter "events fired during a match"."""

    id: int | None
    room_id: int
    user_id: int | None
    ts: datetime
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    match_id: int | None = None


@dataclass
class Match:
    """A PK / link-mic battle the host engaged in. Each battle has a
    TikTok-side battle_id that's unique within a room, plus a list of
    opponents (themselves TikTokViewers, since live hosts are also TikTok
    users). We close the match when TikTok signals battle end, or when
    the room disconnects."""

    id: int | None
    room_id: int
    battle_id: int
    opponents: list[dict[str, Any]] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)  # team_id → score
    # Battle settings (duration_seconds, start_time_ms, end_time_ms).
    settings: dict[str, Any] = field(default_factory=dict)
    winner_user_id: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass
class TikTokGift:
    """Registry of every gift seen across any monitored room. Persisted
    in tiktok_gifts. We upsert on each gift event so later queries can
    JOIN events to the canonical name + diamond value (TikTok occasionally
    rebrands gifts; we keep the latest values + first/last seen timestamps).
    """

    gift_id: int
    name: str | None = None
    diamond_count: int | None = None
    icon_url: str | None = None
    streakable: bool | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass
class TikTokWorker:
    """One running ingestion worker. Persisted in tiktok_workers. The
    `worker_key` is the stable logical identity (default = hostname,
    overridable via env for multi-worker-per-host setups). The DB row
    is the source of truth for "is this worker alive?" — `last_heartbeat_at`
    is bumped every 5s; older than 30s = stale, eligible for reaping.

    Admin control flows through the same DB row:
      - `desired_status` is the admin's request (running/paused/stopped).
      - `command` is a one-shot order (e.g. 'release_handle:@x').
      - Workers poll both on every reconcile tick and act + ack.
    """

    id: int | None
    worker_key: str
    host: str
    pid: int
    status: str = "running"
    capacity: int = 30
    sessions_count: int = 0
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    metadata: dict | None = None
    desired_status: str = "running"
    command: str | None = None
    command_issued_at: datetime | None = None
    command_acked_at: datetime | None = None


@dataclass
class TikTokWorkerLog:
    """Single log entry emitted by a worker. Persisted in tiktok_worker_log.
    The admin UI streams recent rows for each worker so operators can see
    what the worker has been doing."""

    id: int | None
    worker_id: int | None
    ts: datetime | None
    level: str  # 'info' | 'warn' | 'error'
    event: str  # short tag
    handle: str | None = None
    detail: dict | None = None

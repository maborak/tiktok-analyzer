"""SQLAlchemy models for the TikTok-bot module.

Tables (all prefixed `tiktok_` to namespace away from the framework's
own users / events tables):
  - tiktok_subscriptions: which @handles the bot is monitoring
  - tiktok_rooms:         every live room we've ever observed
  - tiktok_viewers:       deduplicated TikTok users we've seen
  - tiktok_events:        every event with JSONB payload (comment, gift, ...)
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from ..core.base import Base


class WorkerModel(Base):
    """Registry row for a running TikTok ingestion worker.

    Multi-worker coordination: each worker process registers itself
    here, heartbeats `last_heartbeat_at` every 5s, and claims a slice
    of the enabled `tiktok_subscriptions` to ingest. When a worker
    crashes, its `last_heartbeat_at` goes stale; another worker reaps
    the row + releases its subscription claims (`assigned_worker_id` /
    `assignment_lease_until`), and the freed handles get re-claimed
    on the next reconcile pass.
    """

    __tablename__ = "tiktok_workers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Logical worker identity that survives restart. Default is `host`,
    # but can be overridden via PHOVEU_BACKEND_TIKTOK_WORKER_NAME for
    # deployments that run multiple workers per host.
    worker_key = Column(String(128), unique=True, nullable=False)
    host = Column(String(128), nullable=False)
    pid = Column(Integer, nullable=False)
    started_at = Column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    last_heartbeat_at = Column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
        index=True,
    )
    status = Column(String(16), nullable=False, default="running")
    capacity = Column(Integer, nullable=False, default=30)
    sessions_count = Column(Integer, nullable=False, default=0)
    # JSON snapshot — sessions list, gap counts, etc. Same data the
    # heartbeat file used to carry; here it lives in DB so the API
    # status endpoint can render the worker tab without file I/O.
    metadata_ = Column("metadata", JSONB().with_variant(Text(), "sqlite"), nullable=True)
    # Admin-requested target state. Worker reads this on every
    # reconcile tick. Values: 'running' | 'paused' | 'stopped'.
    desired_status = Column(String(16), nullable=False, default="running", server_default="running")
    # One-shot command to execute (e.g. 'release_handle:<unique_id>').
    # Worker observes, performs the action, sets command_acked_at.
    command = Column(Text, nullable=True)
    command_issued_at = Column(DateTime(timezone=True), nullable=True)
    command_acked_at = Column(DateTime(timezone=True), nullable=True)


class WorkerLogModel(Base):
    """Lifecycle / audit events emitted by workers. Used by the admin
    UI to show what each worker has been doing recently."""

    __tablename__ = "tiktok_worker_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    worker_id = Column(
        Integer,
        ForeignKey("tiktok_workers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ts = Column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    level = Column(String(8), nullable=False, default="info")
    event = Column(String(64), nullable=False)
    handle = Column(String(64), nullable=True)
    detail = Column(JSONB().with_variant(Text(), "sqlite"), nullable=True)


class SubscriptionModel(Base):
    __tablename__ = "tiktok_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    unique_id = Column(String(64), unique=True, index=True, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    # Cached public profile (refreshed periodically by the service).
    # Source: parsing __UNIVERSAL_DATA_FOR_REHYDRATION__ on tiktok.com/@<handle>.
    profile_user_id = Column(BigInteger, nullable=True)
    sec_uid = Column(Text, nullable=True)
    nickname = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    verified = Column(Boolean, nullable=True)
    private = Column(Boolean, nullable=True)
    follower_count = Column(Integer, nullable=True)
    following_count = Column(Integer, nullable=True)
    video_count = Column(Integer, nullable=True)
    like_count = Column(BigInteger, nullable=True)
    # When we last successfully fetched the public profile.
    profile_refreshed_at = Column(DateTime(timezone=True), nullable=True)
    # Centralized live-status cache. Updated by the worker's scraper
    # task (one network call per handle per ~60s, max 1 outbound req
    # every few seconds across the whole worker). Supervisors read
    # these instead of scraping themselves.
    is_live = Column(Boolean, nullable=True)
    live_checked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    current_room_id = Column(BigInteger, nullable=True)
    # Last error message from the scraper, if the most recent attempt failed.
    profile_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )
    # Multi-worker assignment: which worker process is currently
    # responsible for ingesting this handle, and how long the lease
    # holds. NULL or expired lease => up for grabs by any worker.
    assigned_worker_id = Column(
        Integer,
        ForeignKey("tiktok_workers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assignment_lease_until = Column(DateTime(timezone=True), nullable=True)


class RoomModel(Base):
    __tablename__ = "tiktok_rooms"

    # Natural TikTok room id — never auto-generated.
    room_id = Column(BigInteger, primary_key=True, autoincrement=False)
    host_unique_id = Column(String(64), index=True)
    host_user_id = Column(BigInteger, index=True)
    title = Column(Text)
    started_at = Column(DateTime(timezone=True))
    ended_at = Column(DateTime(timezone=True))
    first_seen_at = Column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    last_seen_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class TikTokViewerModel(Base):
    __tablename__ = "tiktok_viewers"

    # Natural TikTok user id — never auto-generated.
    user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    unique_id = Column(String(64), index=True)
    nickname = Column(Text)
    avatar_url = Column(Text)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    last_seen_at = Column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class TikTokGiftModel(Base):
    """Catalog of gifts observed in monitored rooms.

    Not FK'd from tiktok_events (gift_id is in the event payload JSON);
    this is a registry so dashboards/exports can resolve names + values
    without re-parsing every payload. Diamond value is per-gift (i.e.
    one rose); event totals = diamond_count × repeat_count.
    """

    __tablename__ = "tiktok_gifts"

    # Natural TikTok gift id — never auto-generated.
    gift_id = Column(BigInteger, primary_key=True, autoincrement=False)
    name = Column(String(128), index=True, nullable=False)
    diamond_count = Column(Integer, nullable=False)
    icon_url = Column(Text)
    streakable = Column(Boolean)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    last_seen_at = Column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class TikTokMatchModel(Base):
    """One PK / link-mic battle. Closed when TikTok signals end (Punish or
    VictoryLap), when a new battle_id arrives for the same room (rare), or
    when the connection drops."""

    __tablename__ = "tiktok_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(
        BigInteger,
        ForeignKey("tiktok_rooms.room_id", ondelete="CASCADE"),
        nullable=False,
    )
    battle_id = Column(BigInteger, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    # Opponents (list of viewer dicts) and latest scores per team_id.
    opponents = Column(JSONB().with_variant(Text(), "sqlite"))
    scores = Column(JSONB().with_variant(Text(), "sqlite"))
    # Battle settings (countdown info from BattleSetting): duration in
    # seconds and end_time_ms so the UI can show a countdown clock that
    # matches TikTok's own.
    settings = Column(JSONB().with_variant(Text(), "sqlite"))
    winner_user_id = Column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("room_id", "battle_id", name="tiktok_matches_room_battle_uniq"),
        Index("tiktok_matches_room_ended_idx", "room_id", "ended_at"),
    )


class TikTokEventModel(Base):
    __tablename__ = "tiktok_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    room_id = Column(
        BigInteger,
        ForeignKey("tiktok_rooms.room_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        BigInteger,
        ForeignKey("tiktok_viewers.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    ts = Column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False, index=True)
    type = Column(String(32), nullable=False)
    # JSONB on Postgres; SQLAlchemy falls back to JSON on SQLite.
    payload = Column(JSONB().with_variant(Text(), "sqlite"))
    # Active match at fire-time (NULL when not in a battle). FK SET NULL on
    # delete so events outlive the match record if the match is purged.
    match_id = Column(
        Integer,
        ForeignKey("tiktok_matches.id", ondelete="SET NULL"),
        nullable=True,
    )
    # TikTok server-assigned per-emission ID (`base_message.message_id` on
    # every Webcast* protobuf). Stable across reconnects: if TikTok re-
    # delivers the cursor-edge message, message_id is identical so we can
    # dedup exactly. Distinct user actions always get distinct ids — even
    # for "5 gifts in 1 second" the lib emits 5 message_ids. NULL on
    # historical rows that pre-date capture; the dedup unique index is
    # partial (`WHERE message_id IS NOT NULL`) so old rows aren't
    # forced through it. See `add_event_message_id` migration.
    message_id = Column(BigInteger, nullable=True)

    __table_args__ = (
        Index("tiktok_events_room_ts_idx", "room_id", "ts"),
        Index("tiktok_events_room_type_idx", "room_id", "type"),
        Index("tiktok_events_type_idx", "type"),
        Index("tiktok_events_match_idx", "match_id"),
        # Composite (room_id, message_id) — partial. Queried by the
        # ON CONFLICT clause; per-room scope keeps the index lean and is
        # the correct natural key. Defined declaratively here so SQLAlchemy
        # round-trips the schema; the migration is idempotent on top.
        Index(
            "tiktok_events_room_msg_uniq",
            "room_id", "message_id",
            unique=True,
            postgresql_where=(message_id.isnot(None)),
        ),
    )


class TikTokEventHourCountModel(Base):
    """Pre-aggregated event count per (host, hour). Replaces the
    1.7M-row /admin/tiktok rhythm-strip scan with a ≤24-row-per-host
    indexed lookup. Bumped inline by the event-persist transaction
    (one UPSERT per event, fast as long as the PK index is hot).
    Backfilled once from `tiktok_events` by the migration; the live
    write hook keeps it accurate from then on."""

    __tablename__ = "tiktok_event_hour_counts"

    host_unique_id = Column(String(64), primary_key=True)
    # `date_trunc('hour', e.ts)` — Postgres truncates to the start of
    # the hour. Stored as timestamptz so the aggregation query can
    # filter via `> NOW() - INTERVAL '24 hours'` directly.
    hour_bucket = Column(DateTime(timezone=True), primary_key=True)
    n = Column(BigInteger, nullable=False, default=0)

"""Create `tiktok_room_stats` per-room pre-aggregate table and backfill.

Idempotent. Safe to re-run.

Phase 2 of the 2026-05-15 lives-list cold-mount perf plan. Four
helpers on the bundle path —
  - `_lives_summary_last_broadcasts` (stats per latest-broadcast room)
  - `_lives_summary_session_diamonds` (diamonds in current session)
  - `_lives_summary_30d_averages` (avg diamonds per closed room over 30d)
  - `_lives_summary_median_diamonds` (median diamonds per closed room)

all scan `tiktok_events` filtered by `room_id IN (:rids)` and
`type IN ('gift', 'comment', 'viewer_count')`, extracting JSONB
payload fields (`diamond_count`, `repeat_count`, `total`) with heap
fetches per matching row. On a 6-hour session that's ~100K heap
fetches; on a 30-day window over closed rooms it grows linearly.

This table snapshots the per-room aggregates inline at event-persist
time so the read path is a PK lookup over a tiny indexed table
(one row per room). Same write-time pattern as
`tiktok_event_hour_counts.diamonds`.

Schema:
  room_id          BIGINT PRIMARY KEY  references tiktok_rooms.room_id
  diamonds         BIGINT  NOT NULL DEFAULT 0  -- gift attribution-aware
  n_gifts          INTEGER NOT NULL DEFAULT 0  -- gift attribution-aware
  n_comments       INTEGER NOT NULL DEFAULT 0
  peak_viewers     INTEGER NOT NULL DEFAULT 0
  last_updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()

Indexes:
  PK on room_id is sufficient for the read patterns (all reads filter
  by `room_id = ANY(...)` from a per-host CTE).

PostgreSQL only — no-op on SQLite. SQLite dev path keeps reading
`tiktok_events` directly (small data, no perf issue).

Run:
    python database/migrations/add_tiktok_room_stats.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import inspect, text  # noqa: E402

from database.core.connection import create_database_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _table_exists(engine, table: str) -> bool:
    insp = inspect(engine)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def _create_table(engine) -> bool:
    if _table_exists(engine, "tiktok_room_stats"):
        logger.info("tiktok_room_stats already exists — skipping CREATE.")
        return False
    with engine.begin() as c:
        c.execute(text("""
            CREATE TABLE tiktok_room_stats (
                room_id          BIGINT       PRIMARY KEY,
                diamonds         BIGINT       NOT NULL DEFAULT 0,
                n_gifts          INTEGER      NOT NULL DEFAULT 0,
                n_comments       INTEGER      NOT NULL DEFAULT 0,
                peak_viewers     INTEGER      NOT NULL DEFAULT 0,
                last_updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
        """))
    logger.info("Created table tiktok_room_stats.")
    return True


def _backfill(engine) -> None:
    """One-shot grouped scan: compute aggregates per room from
    `tiktok_events` and upsert into `tiktok_room_stats`.

    Multi-host attribution: diamonds and n_gifts only count gifts
    whose `to_user.user_id` matches the room host's
    `profile_user_id` (or whose `to_user` is missing → unattributed
    counts to the host).

    `peak_viewers` is `MAX(payload->>'total')` on `viewer_count`
    events. `n_comments` is the count of `type='comment'` rows.

    Single statement, runs in a transaction. The `(room_id, type)`
    index on tiktok_events covers the grouping; payload heap fetches
    happen once per backfill regardless of subsequent read volume.
    """
    with engine.begin() as c:
        before = c.execute(text(
            "SELECT count(*) FROM tiktok_room_stats"
        )).scalar() or 0
        c.execute(text("""
            INSERT INTO tiktok_room_stats
                (room_id, diamonds, n_gifts, n_comments, peak_viewers, last_updated_at)
            SELECT
                e.room_id,
                COALESCE(SUM(
                    COALESCE((e.payload->>'diamond_count')::int, 0)
                    * COALESCE((e.payload->>'repeat_count')::int, 1)
                ) FILTER (
                    WHERE e.type = 'gift'
                      AND (
                        sub.profile_user_id IS NULL
                        OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                           IN ('0', sub.profile_user_id::text)
                      )
                ), 0)::bigint AS diamonds,
                COALESCE(COUNT(*) FILTER (
                    WHERE e.type = 'gift'
                      AND (
                        sub.profile_user_id IS NULL
                        OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                           IN ('0', sub.profile_user_id::text)
                      )
                ), 0)::int AS n_gifts,
                COALESCE(COUNT(*) FILTER (WHERE e.type = 'comment'), 0)::int AS n_comments,
                COALESCE(MAX((e.payload->>'total')::int) FILTER (
                    WHERE e.type = 'viewer_count'
                ), 0)::int AS peak_viewers,
                NOW() AS last_updated_at
            FROM tiktok_events e
            JOIN tiktok_rooms r ON r.room_id = e.room_id
            JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
            WHERE e.type IN ('gift', 'comment', 'viewer_count')
            GROUP BY e.room_id
            ON CONFLICT (room_id) DO UPDATE
                SET diamonds        = EXCLUDED.diamonds,
                    n_gifts         = EXCLUDED.n_gifts,
                    n_comments      = EXCLUDED.n_comments,
                    peak_viewers    = EXCLUDED.peak_viewers,
                    last_updated_at = EXCLUDED.last_updated_at
        """))
        after = c.execute(text(
            "SELECT count(*) FROM tiktok_room_stats"
        )).scalar() or 0
    logger.info(
        "Room stats backfill: %d rows before, %d rows after.",
        before, after,
    )


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "add_tiktok_room_stats: dialect=%s — skipping "
            "(Postgres only; SQLite read path scans events directly).",
            engine.dialect.name,
        )
        return

    _create_table(engine)
    _backfill(engine)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        try:
            c.execute(text("ANALYZE tiktok_room_stats"))
        except Exception:
            logger.exception("ANALYZE tiktok_room_stats failed (continuing).")
    logger.info("add_tiktok_room_stats: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

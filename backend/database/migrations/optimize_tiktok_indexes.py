"""Performance + correctness cleanup on tiktok_* tables.

Idempotent. Safe to re-run.

Changes:
  1. VACUUM ANALYZE tiktok_subscriptions  (50% dead-tuple bloat).
  2. DROP unused indexes:
       - ix_tiktok_rooms_host_user_id (0 scans observed)
       - ix_tiktok_gifts_name         (0 scans observed)
  3. ALTER tiktok_gifts: name + diamond_count → NOT NULL
     (only when no NULLs present — soft-skip otherwise).
  4. CREATE INDEX tiktok_viewers(unique_id, last_seen_at DESC)
     — covers the get_viewer_by_unique_id hot path which currently
     does an index scan + sort over 120k rows.
  5. CREATE INDEX tiktok_events(user_id, room_id, type, ts DESC)
     — composite index for `room_top_gifters` aggregations. Currently
     scanning ~103M tuples to fetch ~87M for leaderboard renders that
     run every 2–5 s per active room.

PostgreSQL only — no-op on SQLite (dev path).

Run:
    python database/migrations/optimize_tiktok_indexes.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text  # noqa: E402

from database.core.connection import create_database_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _vacuum_subscriptions(engine) -> None:
    """Clear the 50% dead-tuple bloat on tiktok_subscriptions. VACUUM
    can't run inside a transaction, so use a raw connection w/ AUTOCOMMIT."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        try:
            c.execute(text("VACUUM ANALYZE tiktok_subscriptions"))
            logger.info("VACUUM ANALYZE tiktok_subscriptions done.")
        except Exception:
            logger.exception("VACUUM ANALYZE tiktok_subscriptions failed (continuing).")


def _drop_unused_indexes(engine) -> None:
    """Drop indexes with 0 scans observed in pg_stat_user_indexes."""
    targets = [
        "ix_tiktok_rooms_host_user_id",
        "ix_tiktok_gifts_name",
    ]
    with engine.begin() as c:
        for ix in targets:
            try:
                c.execute(text(f"DROP INDEX IF EXISTS {ix}"))
                logger.info("Dropped index (if present): %s", ix)
            except Exception:
                logger.exception("DROP INDEX %s failed (continuing).", ix)


def _enforce_gift_not_nulls(engine) -> None:
    """Set NOT NULL on tiktok_gifts.name and diamond_count, but only when
    no existing NULLs. Otherwise log and skip — manual cleanup needed."""
    with engine.begin() as c:
        for col in ("name", "diamond_count"):
            null_count = c.execute(
                text(f"SELECT count(*) FROM tiktok_gifts WHERE {col} IS NULL")
            ).scalar()
            if null_count and null_count > 0:
                logger.warning(
                    "tiktok_gifts.%s: %d NULL row(s); NOT NULL skipped. "
                    "Backfill them and re-run.",
                    col, null_count,
                )
                continue
            try:
                c.execute(
                    text(f"ALTER TABLE tiktok_gifts ALTER COLUMN {col} SET NOT NULL")
                )
                logger.info("tiktok_gifts.%s → NOT NULL", col)
            except Exception:
                # Already NOT NULL or unsupported — fine.
                logger.debug(
                    "ALTER tiktok_gifts.%s SET NOT NULL no-op or failed",
                    col, exc_info=True,
                )


def _create_indexes(engine) -> None:
    """Create the new performance indexes. CREATE INDEX IF NOT EXISTS
    is idempotent; CONCURRENTLY can't run in a transaction so we use a
    raw connection in AUTOCOMMIT mode. CONCURRENTLY avoids locking
    writes on the hot tiktok_events table during the build."""
    indexes = [
        (
            "ix_tiktok_viewers_unique_id_seen",
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS '
            'ix_tiktok_viewers_unique_id_seen '
            'ON tiktok_viewers (unique_id, last_seen_at DESC)',
        ),
        (
            "ix_tiktok_events_user_room_type_ts",
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS '
            'ix_tiktok_events_user_room_type_ts '
            'ON tiktok_events (user_id, room_id, type, ts DESC)',
        ),
    ]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for name, ddl in indexes:
            try:
                c.execute(text(ddl))
                logger.info("Created (or already present): %s", name)
            except Exception:
                logger.exception("CREATE INDEX %s failed (continuing).", name)


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "optimize_tiktok_indexes: dialect=%s — skipping (Postgres only).",
            engine.dialect.name,
        )
        return

    _drop_unused_indexes(engine)
    _enforce_gift_not_nulls(engine)
    _create_indexes(engine)
    _vacuum_subscriptions(engine)
    logger.info("optimize_tiktok_indexes: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

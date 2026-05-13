"""Lives-summary index coverage for the /admin/tiktok call graph.

Idempotent. Safe to re-run.

Adds four indexes identified by the DB performance audit on the
`get_lives_summary` cold-miss path. Each helper had to either heap-
fetch beyond what `(host_unique_id)` or `(room_id, type)` could
filter, or run a JSONB expression with no expression index. The
indexes below close those gaps:

  1. ix_tiktok_rooms_host_active  (partial)
     ON tiktok_rooms (host_unique_id, last_seen_at DESC)
     WHERE ended_at IS NULL
     → `_lives_summary_active_rooms` — replaces a host-scoped index
       seek + heap fetch with a tight index probe on the partial
       index of currently-active rooms (small).

  2. ix_tiktok_rooms_host_first_seen
     ON tiktok_rooms (host_unique_id, first_seen_at DESC NULLS LAST)
     → `_lives_summary_last_broadcasts` — lets the PARTITION BY host
       ORDER BY first_seen_at DESC window walk the index in order
       and stop after 3 rows per host, instead of fetching every
       room and sorting.

  3. ix_tiktok_events_room_type_ts
     ON tiktok_events (room_id, type, ts DESC)
     → `_lives_summary_hourly`, `_week_calendar_cached`,
       `_lives_summary_30d_averages` — strictly more specific than
       the existing `(room_id, type)` and `(room_id, ts)` indexes;
       collapses the bitmap-AND pattern into one index seek and
       lets time-window predicates stop scanning at the ts boundary.

  4. ix_tiktok_worker_log_detail_host  (partial expression)
     ON tiktok_worker_log ((detail->>'host'))
     WHERE event = 'session_reconnect'
     → `_lives_summary_reconnects` — covers the JSONB extraction
       that today re-evaluates per surviving row of the
       `(event, ts)` index range.

All four use CREATE INDEX CONCURRENTLY so the build doesn't lock
writes on the hot `tiktok_events` / `tiktok_rooms` tables. The
catch with CONCURRENTLY is it can't run inside a transaction —
each statement runs on a connection in AUTOCOMMIT mode.

PostgreSQL only — no-op on SQLite (dev path).

Run:
    python database/migrations/add_tiktok_lives_summary_indexes.py
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


# (name, DDL). Each statement is idempotent (IF NOT EXISTS) and
# uses CONCURRENTLY so writes on the hot tables aren't blocked
# during the build. CONCURRENTLY can't run in a transaction, so
# we open the connection in AUTOCOMMIT mode below.
INDEXES = [
    (
        "ix_tiktok_rooms_host_active",
        # Partial: only indexes currently-active rooms (ended_at IS
        # NULL). Massively smaller than a full index because most
        # rooms in the table are ended sessions. The `last_seen_at
        # DESC` second column lets the >NOW()-5min predicate in
        # `_lives_summary_active_rooms` walk the index and stop early.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_tiktok_rooms_host_active "
        "ON tiktok_rooms (host_unique_id, last_seen_at DESC) "
        "WHERE ended_at IS NULL",
    ),
    (
        "ix_tiktok_rooms_host_first_seen",
        # Composite (host, first_seen_at DESC). Lets the PARTITION
        # BY host ORDER BY first_seen_at DESC NULLS LAST window in
        # `_lives_summary_last_broadcasts` walk the index and stop
        # after rn <= 3 per host (incremental sort).
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_tiktok_rooms_host_first_seen "
        "ON tiktok_rooms (host_unique_id, first_seen_at DESC NULLS LAST)",
    ),
    (
        "ix_tiktok_events_room_type_ts",
        # Strictly more specific than the existing
        # `tiktok_events_room_type_idx (room_id, type)` and
        # `tiktok_events_room_ts_idx (room_id, ts)`. Postgres can
        # use this single index to satisfy any room-scoped type +
        # ts predicate without a bitmap-AND. Lets time-window
        # queries (`ts > NOW() - 60min` / `ts > NOW() - 7d`) stop
        # scanning at the ts boundary per room.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_tiktok_events_room_type_ts "
        "ON tiktok_events (room_id, type, ts DESC)",
    ),
    (
        "ix_tiktok_worker_log_detail_host",
        # Partial expression index. The `_lives_summary_reconnects`
        # helper filters `WHERE event = 'session_reconnect' AND ts >
        # NOW() - 1h AND detail->>'host' = ANY(:hs)`. The existing
        # `(event, ts)` index narrows to recent reconnect events
        # but still requires a per-row JSONB extraction. This index
        # makes the host filter a direct probe.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_tiktok_worker_log_detail_host "
        "ON tiktok_worker_log ((detail->>'host')) "
        "WHERE event = 'session_reconnect'",
    ),
]


def _create_indexes(engine) -> None:
    """CREATE INDEX CONCURRENTLY for every entry in `INDEXES`.

    Each statement runs on its own AUTOCOMMIT connection because
    CONCURRENTLY refuses to run inside a transaction. A failure on
    one index doesn't abort the rest — log and continue."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for name, ddl in INDEXES:
            try:
                c.execute(text(ddl))
                logger.info("Created (or already present): %s", name)
            except Exception:
                logger.exception(
                    "CREATE INDEX %s failed (continuing). "
                    "Re-run after fixing the cause.",
                    name,
                )


def _analyze_tables(engine) -> None:
    """Refresh planner statistics so the new indexes are used. Cheap;
    Postgres autovacuum will eventually do it anyway, but doing it
    inline means EXPLAIN immediately reflects the new shape."""
    targets = ("tiktok_rooms", "tiktok_events", "tiktok_worker_log")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for t in targets:
            try:
                c.execute(text(f"ANALYZE {t}"))
                logger.info("ANALYZE %s done.", t)
            except Exception:
                logger.exception("ANALYZE %s failed (continuing).", t)


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "add_tiktok_lives_summary_indexes: dialect=%s — skipping "
            "(Postgres only).",
            engine.dialect.name,
        )
        return

    _create_indexes(engine)
    _analyze_tables(engine)
    logger.info("add_tiktok_lives_summary_indexes: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

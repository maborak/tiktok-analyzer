"""Targeted indexes to make the /admin/tiktok page polling cheaper.

Idempotent. Safe to re-run. PostgreSQL only — no-op on SQLite (dev).

Indexes added:

1. `ix_tiktok_events_type_ts` on `tiktok_events (type, ts DESC)` —
   covers `get_lives_totals`'s unfiltered aggregates:
       SELECT … WHERE type='gift' AND ts > NOW() - INTERVAL '24 hours'
       SELECT … WHERE ts > NOW() - INTERVAL '5 minutes'
   Polled every 30 s by /admin/tiktok header strip. Without this
   index the only candidates were single-column `(type)` (heap-fetch
   every historical gift) or `(ts)` (re-check type per row). Both
   become wide scans at 10M+ rows.

2. `ix_tiktok_worker_log_event_ts` on `tiktok_worker_log (event, ts DESC)`
   — covers `get_lives_summary`'s reconnect-in-last-hour aggregate:
       SELECT detail->>'host', COUNT(*) FROM tiktok_worker_log
       WHERE event='session_reconnect' AND ts > NOW() - INTERVAL '1 hour'
   `tiktok_worker_log` is a write-hot audit table that grows fast;
   the existing single-column `(event)` index is fine today but
   degrades within months. Adding the composite preemptively + dropping
   the redundant single-column afterwards (leftmost-prefix covers it).

Both built with CREATE INDEX CONCURRENTLY so existing writes on
`tiktok_events` aren't blocked during the build. CONCURRENTLY can't
run inside a transaction — we use a raw connection in AUTOCOMMIT.

Run:
    python database/migrations/add_events_type_ts_and_worker_log_event_ts_indexes.py
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


def _create_indexes(engine) -> None:
    """Create the new performance indexes CONCURRENTLY."""
    indexes = [
        (
            "ix_tiktok_events_type_ts",
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS '
            'ix_tiktok_events_type_ts '
            'ON tiktok_events (type, ts DESC)',
        ),
        (
            "ix_tiktok_worker_log_event_ts",
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS '
            'ix_tiktok_worker_log_event_ts '
            'ON tiktok_worker_log (event, ts DESC)',
        ),
    ]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for name, ddl in indexes:
            try:
                c.execute(text(ddl))
                logger.info("Created (or already present): %s", name)
            except Exception:
                logger.exception("CREATE INDEX %s failed (continuing).", name)


def _drop_redundant_indexes(engine) -> None:
    """Drop the single-column `(event)` index on `tiktok_worker_log`.
    The new `(event, ts DESC)` composite covers every query the
    single-column variant would have served (leftmost-prefix rule).
    Idempotent — DROP IF EXISTS is a no-op when the index is absent."""
    targets = [
        "ix_tiktok_worker_log_event",
    ]
    with engine.begin() as c:
        for ix in targets:
            try:
                c.execute(text(f"DROP INDEX IF EXISTS {ix}"))
                logger.info("Dropped redundant index (if present): %s", ix)
            except Exception:
                logger.exception("DROP INDEX %s failed (continuing).", ix)


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "add_events_type_ts_and_worker_log_event_ts_indexes: "
            "dialect=%s — skipping (Postgres only).",
            engine.dialect.name,
        )
        return

    _create_indexes(engine)
    _drop_redundant_indexes(engine)
    logger.info("add_events_type_ts_and_worker_log_event_ts_indexes: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

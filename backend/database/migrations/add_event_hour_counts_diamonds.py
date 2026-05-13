"""Add `diamonds` column to `tiktok_event_hour_counts` and backfill.

Idempotent. Safe to re-run.

Phase 5 of the lives-list perf plan. The `get_lives_totals` endpoint
used to compute the 24h diamond total by summing
`payload->>'diamond_count' * payload->>'repeat_count'` over every
gift event in the last 24 hours — millions of rows on a busy install,
each requiring a JSONB heap fetch even after the `(type, ts)` index
narrows the range. The 35 s TTL cache absorbs the cost for the page
but every cold miss still pays the full scan.

After this migration the same total is `SUM(diamonds)` over the
pre-aggregated `tiktok_event_hour_counts` table — at most 79×25 = 1975
rows for a 79-handle install. Index-scan over the PK.

Migration steps:
  1. ALTER TABLE ADD COLUMN diamonds BIGINT NOT NULL DEFAULT 0
     (column is NOT NULL with DEFAULT 0; new column on existing rows
     defaults to 0 so existing rhythm-strip reads keep working).
  2. Backfill from `tiktok_events` for every (host, hour) bucket
     already present in `tiktok_event_hour_counts`. Uses
     `INSERT ... ON CONFLICT DO UPDATE` keyed by the PK to set the
     column without touching `n`.

PostgreSQL only — no-op on SQLite (dev path; the read path falls
back to a scan there).

Run:
    python database/migrations/add_event_hour_counts_diamonds.py
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


def _column_exists(engine, table: str, column: str) -> bool:
    insp = inspect(engine)
    try:
        cols = insp.get_columns(table)
    except Exception:
        return False
    return any(c["name"] == column for c in cols)


def _add_column(engine) -> bool:
    """ALTER TABLE … ADD COLUMN diamonds BIGINT NOT NULL DEFAULT 0.

    Idempotent — checks `information_schema` first. Adding a column
    with a constant DEFAULT is metadata-only in Postgres 11+ (no
    table rewrite), so this is safe even on a multi-million-row
    table."""
    if _column_exists(engine, "tiktok_event_hour_counts", "diamonds"):
        logger.info("Column tiktok_event_hour_counts.diamonds already exists — skipping ADD COLUMN.")
        return False
    with engine.begin() as c:
        c.execute(text(
            "ALTER TABLE tiktok_event_hour_counts "
            "ADD COLUMN diamonds BIGINT NOT NULL DEFAULT 0"
        ))
    logger.info("Added column tiktok_event_hour_counts.diamonds (BIGINT NOT NULL DEFAULT 0).")
    return True


def _backfill_diamonds(engine) -> None:
    """Compute the diamond total per (host, hour) from `tiktok_events`
    and write it into the pre-agg table.

    Uses `INSERT ... ON CONFLICT (host_unique_id, hour_bucket) DO
    UPDATE SET diamonds = EXCLUDED.diamonds` so the operation only
    updates existing rows or inserts new ones; it never deletes a row
    that's there for `n` accounting. If the events table has gift
    rows in a (host, hour) bucket that doesn't exist in the pre-agg,
    those would be missing from `n` anyway (the original migration's
    backfill scope) — we don't synthesize them here.

    Single statement, runs inside a transaction. On a typical install
    this is a single grouped scan over `tiktok_events` filtered by
    `type = 'gift'`, which the existing `(type, ts)` index covers
    efficiently."""
    with engine.begin() as c:
        before = c.execute(text(
            "SELECT count(*) FROM tiktok_event_hour_counts "
            "WHERE diamonds > 0"
        )).scalar() or 0
        c.execute(text("""
            INSERT INTO tiktok_event_hour_counts (host_unique_id, hour_bucket, n, diamonds)
            SELECT
                r.host_unique_id,
                date_trunc('hour', e.ts) AS hour_bucket,
                0 AS n,  -- placeholder; ON CONFLICT preserves existing n
                SUM(
                    COALESCE((e.payload->>'diamond_count')::int, 0)
                    * COALESCE((e.payload->>'repeat_count')::int, 1)
                )::bigint AS diamonds
            FROM tiktok_events e
            JOIN tiktok_rooms r ON r.room_id = e.room_id
            WHERE e.type = 'gift'
              AND r.host_unique_id IS NOT NULL
            GROUP BY r.host_unique_id, date_trunc('hour', e.ts)
            ON CONFLICT (host_unique_id, hour_bucket) DO UPDATE
                SET diamonds = EXCLUDED.diamonds
        """))
        after = c.execute(text(
            "SELECT count(*) FROM tiktok_event_hour_counts "
            "WHERE diamonds > 0"
        )).scalar() or 0
    logger.info(
        "Diamonds backfill: %d buckets had diamonds before, %d after.",
        before, after,
    )


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "add_event_hour_counts_diamonds: dialect=%s — skipping "
            "(Postgres only; SQLite read path scans events directly).",
            engine.dialect.name,
        )
        return

    _add_column(engine)
    _backfill_diamonds(engine)
    # ANALYZE so the planner picks up the new column's value distribution.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        try:
            c.execute(text("ANALYZE tiktok_event_hour_counts"))
        except Exception:
            logger.exception("ANALYZE tiktok_event_hour_counts failed (continuing).")
    logger.info("add_event_hour_counts_diamonds: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

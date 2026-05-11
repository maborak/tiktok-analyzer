"""Add `tiktok_event_hour_counts` — write-time pre-aggregate of
events per (host, hour) bucket.

Idempotent. Safe to re-run.

Why:
  The 24h rhythm-strip query on /admin/tiktok was scanning ~1.7M
  event rows per poll (counting events × 43 handles × last 24h)
  and spending ~750ms doing it. The data volume is the cost — the
  index path is already optimal. Pre-aggregating into a small
  table reduces the read to ≤24 rows per host, which lookups in
  a few ms instead of 750.

  Writes: every persisted event runs an extra UPSERT keyed on
  (host_unique_id, date_trunc('hour', NOW())). One indexed
  round-trip per event — lost in the noise of the room/viewer/
  user_host_summary upserts that already happen.

Schema:
  tiktok_event_hour_counts (
      host_unique_id  TEXT          NOT NULL,
      hour_bucket     TIMESTAMPTZ   NOT NULL,   -- date_trunc('hour', ts)
      n               BIGINT        NOT NULL DEFAULT 0,
      PRIMARY KEY (host_unique_id, hour_bucket)
  );

  The PK doubles as the read-path index: `WHERE host = ANY(:hs)
  AND hour_bucket > NOW() - INTERVAL '24 hours'` is served by an
  index range scan.

Backfill:
  Populate the last 25h from existing tiktok_events so the rhythm
  strip is correct immediately on first deploy. After that the
  write hook keeps it live.
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
    return table in inspect(engine).get_table_names()


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name
    if dialect != "postgresql":
        logger.info("Skipping (sqlite dev path): pre-aggregate is Postgres-only.")
        return

    created = not _table_exists(engine, "tiktok_event_hour_counts")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("""
            CREATE TABLE IF NOT EXISTS tiktok_event_hour_counts (
                host_unique_id TEXT          NOT NULL,
                hour_bucket    TIMESTAMPTZ   NOT NULL,
                n              BIGINT        NOT NULL DEFAULT 0,
                PRIMARY KEY (host_unique_id, hour_bucket)
            )
        """))
        if created:
            logger.info("Created table tiktok_event_hour_counts")
        else:
            logger.info("tiktok_event_hour_counts already exists — skipping create.")

        # Backfill last 25h. Idempotent via the PK ON CONFLICT.
        # We only run the backfill on first creation OR when the table
        # is empty — re-running on a populated table would overwrite
        # in-flight live counts with the read-time view, which is fine
        # but wasteful.
        n_existing = c.execute(text(
            "SELECT count(*) FROM tiktok_event_hour_counts"
        )).scalar()
        if n_existing == 0:
            logger.info("Backfilling last 25h from tiktok_events…")
            c.execute(text("""
                INSERT INTO tiktok_event_hour_counts (host_unique_id, hour_bucket, n)
                SELECT r.host_unique_id,
                       date_trunc('hour', e.ts) AS hour_bucket,
                       COUNT(*)
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                WHERE r.host_unique_id IS NOT NULL
                  AND e.ts > NOW() - INTERVAL '25 hours'
                GROUP BY 1, 2
                ON CONFLICT (host_unique_id, hour_bucket)
                  DO UPDATE SET n = EXCLUDED.n
            """))
            n_after = c.execute(text(
                "SELECT count(*) FROM tiktok_event_hour_counts"
            )).scalar()
            logger.info("Backfill complete — %d rows seeded.", n_after)
        else:
            logger.info(
                "Skip backfill — %d existing rows. Re-run with TRUNCATE first if a rebuild is needed.",
                n_existing,
            )

    logger.info("add_event_hour_counts: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

"""Drop captured `caption`, `rank_text`, `rank_update` event rows
from `tiktok_events` and rebuild the pre-aggregated hour-count
table to reflect the new totals.

Idempotent. Safe to re-run — subsequent runs are no-ops (delete
returns 0, rebuild produces the same totals).

Why:
  These three event types are no longer captured by the listener
  (see the NOTE block in `adapters/tiktok_live_client.py`).
  Existing rows are dead data — high-volume captions (432k+ rows)
  bloat the table and slow non-targeted aggregations, while the
  100-odd `rank_*` rows hold no useful UI surface.

  Pre-agg `tiktok_event_hour_counts` was written by the same
  insert hook that counted these events, so deleting raw rows
  without rebuilding leaves the hour buckets over-counted. The
  rebuild is bounded (≤24h * ~50 handles ≈ 1200 rows) and runs
  on the same engine connection.

Batch sizing:
  Captions alone can be 400k+ rows. A single `DELETE` would
  acquire row locks for the duration; batched with `LIMIT` keeps
  any concurrent writes from blocking too long. PG's
  `DELETE FROM … WHERE ctid IN (SELECT … LIMIT N)` is the
  idiomatic pagination here.
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

DROP_TYPES = ("caption", "rank_text", "rank_update")
BATCH_SIZE = 10_000


def _count_targets(c) -> int:
    return c.execute(text(
        "SELECT count(*) FROM tiktok_events WHERE type = ANY(:types)"
    ), {"types": list(DROP_TYPES)}).scalar() or 0


def _delete_batch(c) -> int:
    res = c.execute(text(f"""
        DELETE FROM tiktok_events
        WHERE id IN (
            SELECT id FROM tiktok_events
            WHERE type = ANY(:types)
            LIMIT {BATCH_SIZE}
        )
    """), {"types": list(DROP_TYPES)})
    return res.rowcount or 0


def _rebuild_hour_counts(c) -> int:
    """Rebuild `tiktok_event_hour_counts` from the surviving rows.

    Truncates the pre-agg table and re-runs the same aggregation
    the original migration used as a backfill. Caps to the last
    25h since the read path only ever queries the last 24h."""
    c.execute(text("TRUNCATE tiktok_event_hour_counts"))
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
    )).scalar() or 0
    return n_after


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info("Skipping (sqlite dev path).")
        return

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        n_target = _count_targets(c)
        if n_target == 0:
            logger.info("No caption / rank_* rows to drop. Skipping rebuild.")
            return
        logger.info("Dropping %d rows of type IN %s in batches of %d…",
                    n_target, DROP_TYPES, BATCH_SIZE)

        dropped = 0
        while True:
            batch = _delete_batch(c)
            if batch == 0:
                break
            dropped += batch
            logger.info("  …deleted %d / %d", dropped, n_target)
        logger.info("Delete complete — %d rows removed.", dropped)

        n_after = _rebuild_hour_counts(c)
        logger.info("Pre-agg rebuilt — tiktok_event_hour_counts now has %d rows.", n_after)

    logger.info("drop_caption_rank_events: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

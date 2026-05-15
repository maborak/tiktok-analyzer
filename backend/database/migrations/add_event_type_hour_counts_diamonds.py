"""Add `diamonds` column to `tiktok_event_type_hour_counts` and backfill.

Idempotent. Safe to re-run.

Phase 1 of the 2026-05-15 lives-list cold-mount perf plan. The
`_lives_summary_hourly` helper used to build the 60-minute sparkline
by scanning every gift event in the last hour from `tiktok_events`,
extracting `payload->>'diamond_count'` and `payload->>'repeat_count'`
per row (heap fetch per match). On a busy install that's thousands of
JSONB heap fetches per cold cache miss — directly on the bundle path.

We already write a one-row-per-(host, hour, type) UPSERT into
`tiktok_event_type_hour_counts` from `_bump_event_type_hour_count` on
every event. After this migration the same UPSERT also accumulates
`diamonds` (when `type='gift'` AND the gift's `to_user` matches the
host's `profile_user_id`). The 60-minute sparkline read then becomes
a tiny indexed range scan: `WHERE host=ANY(:hs) AND hour_bucket >
NOW() - INTERVAL '1 hour' AND type='gift'` — ≤2 rows per host (the
current partial hour + the previous full hour at the boundary).

Migration steps:
  1. ALTER TABLE ADD COLUMN diamonds BIGINT NOT NULL DEFAULT 0
     (metadata-only in Postgres 11+, no table rewrite).
  2. Backfill from `tiktok_events` for every (host, hour, type='gift')
     bucket. Uses `INSERT ... ON CONFLICT DO UPDATE` keyed by the PK
     so existing `n` counts are preserved.

Multi-host attribution: the same `to_user.user_id ∈ ('0', host
profile_user_id)` predicate as `add_event_hour_counts_diamonds.py`
applies — guest gifts to a co-host on the same room do NOT credit
the room's host.

PostgreSQL only — no-op on SQLite (dev path; the read path falls
back to a scan there).

Run:
    python database/migrations/add_event_type_hour_counts_diamonds.py
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
    if _column_exists(engine, "tiktok_event_type_hour_counts", "diamonds"):
        logger.info(
            "Column tiktok_event_type_hour_counts.diamonds already exists "
            "— skipping ADD COLUMN."
        )
        return False
    with engine.begin() as c:
        c.execute(text(
            "ALTER TABLE tiktok_event_type_hour_counts "
            "ADD COLUMN diamonds BIGINT NOT NULL DEFAULT 0"
        ))
    logger.info(
        "Added column tiktok_event_type_hour_counts.diamonds "
        "(BIGINT NOT NULL DEFAULT 0)."
    )
    return True


def _backfill_diamonds(engine) -> None:
    """Compute the diamond total per (host, hour, type='gift') from
    `tiktok_events` and write it into the pre-agg table.

    Uses `INSERT ... ON CONFLICT (host_unique_id, hour_bucket, type)
    DO UPDATE` so the operation only writes the diamonds column on
    existing rows or inserts new ones; existing `n` counts are
    preserved (the `n=0` placeholder is overwritten by EXCLUDED only
    when no row existed). To be safe across pg versions we explicitly
    drop EXCLUDED.n from the SET list.

    Single grouped statement, covered by `(type, ts)` partial index
    on tiktok_events."""
    with engine.begin() as c:
        before = c.execute(text(
            "SELECT count(*) FROM tiktok_event_type_hour_counts "
            "WHERE diamonds > 0"
        )).scalar() or 0
        c.execute(text("""
            INSERT INTO tiktok_event_type_hour_counts
                (host_unique_id, hour_bucket, type, n, diamonds)
            SELECT
                r.host_unique_id,
                date_trunc('hour', e.ts) AS hour_bucket,
                'gift' AS type,
                0 AS n,  -- placeholder; ON CONFLICT preserves existing n
                SUM(
                    COALESCE((e.payload->>'diamond_count')::int, 0)
                    * COALESCE((e.payload->>'repeat_count')::int, 1)
                )::bigint AS diamonds
            FROM tiktok_events e
            JOIN tiktok_rooms r ON r.room_id = e.room_id
            JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
            WHERE e.type = 'gift'
              AND r.host_unique_id IS NOT NULL
              AND (
                sub.profile_user_id IS NULL
                OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                   IN ('0', sub.profile_user_id::text)
              )
            GROUP BY r.host_unique_id, date_trunc('hour', e.ts)
            ON CONFLICT (host_unique_id, hour_bucket, type) DO UPDATE
                SET diamonds = EXCLUDED.diamonds
        """))
        after = c.execute(text(
            "SELECT count(*) FROM tiktok_event_type_hour_counts "
            "WHERE diamonds > 0"
        )).scalar() or 0
    logger.info(
        "Diamonds backfill: %d gift buckets had diamonds before, %d after.",
        before, after,
    )


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "add_event_type_hour_counts_diamonds: dialect=%s — skipping "
            "(Postgres only; SQLite read path scans events directly).",
            engine.dialect.name,
        )
        return

    _add_column(engine)
    _backfill_diamonds(engine)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        try:
            c.execute(text("ANALYZE tiktok_event_type_hour_counts"))
        except Exception:
            logger.exception(
                "ANALYZE tiktok_event_type_hour_counts failed (continuing)."
            )
    logger.info("add_event_type_hour_counts_diamonds: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

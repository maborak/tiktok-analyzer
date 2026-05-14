"""Add an incrementally-maintained (user, host) gift-totals summary
table — `tiktok_user_host_summary`.

Powers the Common Gifters tab. The previous SQL aggregated every
gift event in `tiktok_events` on every request, which got slow as
the event table grew. This summary table gives O(few thousand rows)
reads regardless of underlying event volume, and is kept fresh by
an UPSERT in the gift-event persist path (so reads are always live,
no refresh interval, no staleness window).

Idempotent. Safe to re-run. Backfills from existing events the first
time it sees an empty table.

Schema:
  user_id          BIGINT       — gifter's TikTok user_id
  host_unique_id   TEXT         — host (creator) the gift went to
  diamonds         BIGINT       — sum of diamond_count × repeat_count
  gifts            BIGINT       — sum of repeat_count
  first_seen_at    TIMESTAMPTZ  — earliest gift event ts for this pair
  last_seen_at     TIMESTAMPTZ  — most recent gift event ts
  PRIMARY KEY      (user_id, host_unique_id)
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


def _create_summary_table(c, dialect: str) -> None:
    if dialect == "postgresql":
        c.execute(text("""
            CREATE TABLE IF NOT EXISTS tiktok_user_host_summary (
                user_id        BIGINT      NOT NULL,
                host_unique_id TEXT        NOT NULL,
                diamonds       BIGINT      NOT NULL DEFAULT 0,
                gifts          BIGINT      NOT NULL DEFAULT 0,
                first_seen_at  TIMESTAMPTZ NOT NULL,
                last_seen_at   TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (user_id, host_unique_id)
            )
        """))
        # Per-host lookups (e.g. "all gifters of @handle").
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_user_host_summary_host "
            "ON tiktok_user_host_summary (host_unique_id)"
        ))
        # Top-N per user — supports the Common Gifters ORDER BY diamonds DESC.
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_user_host_summary_diamonds "
            "ON tiktok_user_host_summary (user_id, diamonds DESC)"
        ))
    else:  # SQLite (dev)
        c.execute(text("""
            CREATE TABLE IF NOT EXISTS tiktok_user_host_summary (
                user_id        INTEGER NOT NULL,
                host_unique_id TEXT    NOT NULL,
                diamonds       INTEGER NOT NULL DEFAULT 0,
                gifts          INTEGER NOT NULL DEFAULT 0,
                first_seen_at  TEXT    NOT NULL,
                last_seen_at   TEXT    NOT NULL,
                PRIMARY KEY (user_id, host_unique_id)
            )
        """))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_user_host_summary_host "
            "ON tiktok_user_host_summary (host_unique_id)"
        ))


def _backfill_from_events(c, dialect: str) -> None:
    # Skip if the table already has rows — backfill is a one-time op,
    # the UPSERT in the event-persist path keeps it current after that.
    existing = c.execute(text(
        "SELECT COUNT(*) FROM tiktok_user_host_summary"
    )).scalar() or 0
    if existing > 0:
        logger.info(
            "Backfill skipped: tiktok_user_host_summary already has %d rows.",
            existing,
        )
        return

    logger.info(
        "Backfilling tiktok_user_host_summary from tiktok_events. "
        "This is a one-time aggregate scan; can take a minute on a large DB."
    )
    if dialect == "postgresql":
        # Filter multi-host guest gifts so a gifter's per-host roll-up
        # only credits the host they actually sent to. When the host's
        # profile_user_id is unknown (unprobed handle) fall through to
        # legacy "count everything" so the row still exists.
        c.execute(text("""
            INSERT INTO tiktok_user_host_summary
                (user_id, host_unique_id, diamonds, gifts,
                 first_seen_at, last_seen_at)
            SELECT
                e.user_id,
                r.host_unique_id,
                COALESCE(SUM(
                    COALESCE(NULLIF(e.payload->>'diamond_count','')::int, 0)
                    * COALESCE(NULLIF(e.payload->>'repeat_count','')::int, 1)
                ), 0) AS diamonds,
                COALESCE(SUM(
                    COALESCE(NULLIF(e.payload->>'repeat_count','')::int, 1)
                ), 0) AS gifts,
                MIN(e.ts) AS first_seen_at,
                MAX(e.ts) AS last_seen_at
            FROM tiktok_events e
            JOIN tiktok_rooms r ON r.room_id = e.room_id
            JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
            WHERE e.type = 'gift'
              AND e.user_id IS NOT NULL
              AND r.host_unique_id IS NOT NULL
              AND (
                sub.profile_user_id IS NULL
                OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                   IN ('0', sub.profile_user_id::text)
              )
            GROUP BY e.user_id, r.host_unique_id
            ON CONFLICT (user_id, host_unique_id) DO NOTHING
        """))
    else:
        # SQLite path: aggregate in Python over a bounded scan. Dev DB
        # only — not exercised in production.
        rows = c.execute(text("""
            SELECT e.user_id, r.host_unique_id, e.payload, e.ts
            FROM tiktok_events e
            JOIN tiktok_rooms r ON r.room_id = e.room_id
            WHERE e.type = 'gift'
              AND e.user_id IS NOT NULL
              AND r.host_unique_id IS NOT NULL
            LIMIT 200000
        """)).fetchall()
        agg: dict[tuple[int, str], dict] = {}
        import json
        for r in rows:
            payload = r.payload
            if isinstance(payload, str):
                try: payload = json.loads(payload)
                except Exception: payload = {}
            if not isinstance(payload, dict):
                payload = {}
            d = int(payload.get("diamond_count") or 0) * int(payload.get("repeat_count") or 1)
            g = int(payload.get("repeat_count") or 1)
            key = (int(r.user_id), str(r.host_unique_id))
            entry = agg.setdefault(
                key,
                {"diamonds": 0, "gifts": 0, "first": r.ts, "last": r.ts},
            )
            entry["diamonds"] += d
            entry["gifts"] += g
            if r.ts < entry["first"]: entry["first"] = r.ts
            if r.ts > entry["last"]: entry["last"] = r.ts
        for (uid, host), v in agg.items():
            c.execute(text("""
                INSERT INTO tiktok_user_host_summary
                    (user_id, host_unique_id, diamonds, gifts,
                     first_seen_at, last_seen_at)
                VALUES (:uid, :host, :d, :g, :first, :last)
                ON CONFLICT (user_id, host_unique_id) DO NOTHING
            """), {
                "uid": uid, "host": host,
                "d": v["diamonds"], "g": v["gifts"],
                "first": v["first"], "last": v["last"],
            })

    final = c.execute(text(
        "SELECT COUNT(*) FROM tiktok_user_host_summary"
    )).scalar() or 0
    logger.info("Backfill done: %d (user, host) rows.", final)


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        _create_summary_table(c, dialect)
        _backfill_from_events(c, dialect)
    logger.info("add_user_host_summary: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

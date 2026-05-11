"""Migrate every tiktok_* timestamp column from `timestamp` (naive) to
`timestamptz` (UTC-aware). Idempotent.

Why: existing values were stored via `datetime.utcnow()` — semantically
UTC, but the column type was naive. Comparisons against tz-aware Python
datetimes raise `can't compare offset-naive and offset-aware datetimes`,
and a future server-timezone change or a multi-region deploy would
silently shift every timestamp. tz-aware columns make the storage
unambiguous and let Python keep aware datetimes end-to-end.

Applied with `USING <col> AT TIME ZONE 'UTC'` so the existing naive
values are interpreted as UTC (which is what they were).

PostgreSQL only — no-op on SQLite (dev).

WARNING: ALTER COLUMN ... TYPE timestamptz USING ... rewrites the table.
For tiktok_events (~500k rows / ~260MB) this takes a few seconds and
holds an ACCESS EXCLUSIVE lock on the table during that window. Plan
deploy time accordingly.
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


# (table, column) pairs that store time-of-event style data and should
# be tz-aware. Enumerated explicitly so the migration is auditable.
TARGETS: list[tuple[str, str]] = [
    ("tiktok_events", "ts"),
    ("tiktok_gifts", "first_seen_at"),
    ("tiktok_gifts", "last_seen_at"),
    ("tiktok_matches", "started_at"),
    ("tiktok_matches", "ended_at"),
    ("tiktok_matches", "last_seen_at"),
    ("tiktok_rooms", "started_at"),
    ("tiktok_rooms", "ended_at"),
    ("tiktok_rooms", "first_seen_at"),
    ("tiktok_rooms", "last_seen_at"),
    ("tiktok_subscriptions", "created_at"),
    ("tiktok_subscriptions", "updated_at"),
    ("tiktok_subscriptions", "profile_refreshed_at"),
    ("tiktok_viewers", "first_seen_at"),
    ("tiktok_viewers", "last_seen_at"),
]


def _column_data_type(c, table: str, column: str) -> str | None:
    return c.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).scalar()


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "tz_aware_tiktok_timestamps: dialect=%s — skipping.",
            engine.dialect.name,
        )
        return

    converted = 0
    skipped = 0
    with engine.begin() as c:
        for table, column in TARGETS:
            current = _column_data_type(c, table, column)
            if current is None:
                logger.warning("Column %s.%s not found — skipping.", table, column)
                skipped += 1
                continue
            if current == "timestamp with time zone":
                logger.debug("%s.%s already timestamptz — skipping.", table, column)
                skipped += 1
                continue
            if current != "timestamp without time zone":
                logger.warning(
                    "%s.%s has unexpected type %r — skipping.",
                    table, column, current,
                )
                skipped += 1
                continue
            ddl = (
                f'ALTER TABLE "{table}" '
                f'ALTER COLUMN "{column}" TYPE timestamptz '
                f'USING "{column}" AT TIME ZONE \'UTC\''
            )
            try:
                c.execute(text(ddl))
                logger.info("%s.%s → timestamptz (UTC)", table, column)
                converted += 1
            except Exception:
                logger.exception("ALTER %s.%s failed", table, column)

    logger.info(
        "tz_aware_tiktok_timestamps: %d converted, %d skipped.",
        converted, skipped,
    )


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

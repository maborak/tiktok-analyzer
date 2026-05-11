"""Add live-status cache columns to tiktok_subscriptions.

Idempotent. Safe to re-run.

Why:
  Multiple supervisors each scraping `tiktok.com/@<handle>` every 60s
  to detect "creator went live" was hitting TikTok hard enough to
  trigger DEVICE_BLOCKED. With a DB cache + a single per-worker
  scraper task, we go from N parallel pollers to 1 throttled one,
  and supervisors just read the cached value.

Columns added:
  - is_live (boolean) — last known live state.
  - live_checked_at (timestamptz) — when we last checked.
  - current_room_id (bigint) — most-recent room_id seen for this
    handle, so a brief WS reconnect can skip the room-info fetch.
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
    return column in {c["name"] for c in inspect(engine).get_columns(table)}


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name
    ts_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TIMESTAMP"
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        if not _column_exists(engine, "tiktok_subscriptions", "is_live"):
            c.execute(text(
                "ALTER TABLE tiktok_subscriptions ADD COLUMN is_live BOOLEAN"
            ))
            logger.info("Added column tiktok_subscriptions.is_live")
        if not _column_exists(engine, "tiktok_subscriptions", "live_checked_at"):
            c.execute(text(
                f"ALTER TABLE tiktok_subscriptions "
                f"ADD COLUMN live_checked_at {ts_type}"
            ))
            logger.info("Added column tiktok_subscriptions.live_checked_at")
        if not _column_exists(engine, "tiktok_subscriptions", "current_room_id"):
            c.execute(text(
                "ALTER TABLE tiktok_subscriptions "
                "ADD COLUMN current_room_id BIGINT"
            ))
            logger.info("Added column tiktok_subscriptions.current_room_id")
        # Used by the central scraper to find handles that need a check.
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tiktok_subs_live_checked "
            "ON tiktok_subscriptions (live_checked_at)"
        ))
    logger.info("add_subscription_live_cache: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

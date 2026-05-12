"""Add `is_public` flag to tiktok_subscriptions.

Idempotent. Safe to re-run.

Why:
  Admins now mark individual subscriptions as public so an
  unauthenticated /public/tiktok/lives endpoint can surface a
  sanitized subset (nickname, avatar, follower count, live state,
  viewer count, session diamonds, started_at, hourly_buckets) —
  nothing operator-only. Default False keeps existing rows private
  until the admin explicitly opts in.
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
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        if not _column_exists(engine, "tiktok_subscriptions", "is_public"):
            # Postgres + SQLite both accept this syntax. NOT NULL + DEFAULT
            # FALSE seeds every existing row to False in one statement.
            c.execute(text(
                "ALTER TABLE tiktok_subscriptions "
                "ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            logger.info("Added column tiktok_subscriptions.is_public")
        else:
            logger.info("Column tiktok_subscriptions.is_public already exists; skipping")
    logger.info("add_subscription_is_public: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

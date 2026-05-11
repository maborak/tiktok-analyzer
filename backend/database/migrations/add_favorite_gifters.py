"""Add `tiktok_favorite_gifters` — admin-managed list of viewers
to watch across every tracked creator.

Idempotent. Safe to re-run.

Schema:
  user_id      BIGINT       NOT NULL PRIMARY KEY
  note         TEXT         optional admin note
  added_at     TIMESTAMPTZ  NOT NULL DEFAULT now()

Used by the "Favorites" tab and the live-alert toast on /admin/tiktok:
when a gift event lands for a user_id in this table we surface a
realtime notification like "@xxx sent <gift> in @host's live".
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


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        if dialect == "postgresql":
            c.execute(text("""
                CREATE TABLE IF NOT EXISTS tiktok_favorite_gifters (
                    user_id   BIGINT      PRIMARY KEY,
                    note      TEXT,
                    added_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
        else:
            c.execute(text("""
                CREATE TABLE IF NOT EXISTS tiktok_favorite_gifters (
                    user_id   INTEGER PRIMARY KEY,
                    note      TEXT,
                    added_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_favorite_gifters_added_at "
            "ON tiktok_favorite_gifters (added_at DESC)"
        ))
    logger.info("add_favorite_gifters: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

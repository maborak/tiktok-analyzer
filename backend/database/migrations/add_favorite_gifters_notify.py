"""Add per-favourite notification toggles to `tiktok_favorite_gifters`.

Three new columns control which event types fire a live toast for
this gifter on the admin UI: Gifts (default ON), Comments, Joins.

Idempotent. Safe to re-run.
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
    cols = {c["name"] for c in insp.get_columns(table)}
    return column in cols


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for col, default in (
            ("notify_gift",    "TRUE"),
            ("notify_comment", "FALSE"),
            ("notify_join",    "FALSE"),
        ):
            if _column_exists(engine, "tiktok_favorite_gifters", col):
                continue
            if dialect == "postgresql":
                c.execute(text(
                    f"ALTER TABLE tiktok_favorite_gifters "
                    f"ADD COLUMN {col} BOOLEAN NOT NULL DEFAULT {default}"
                ))
            else:
                # SQLite: default literals work the same.
                c.execute(text(
                    f"ALTER TABLE tiktok_favorite_gifters "
                    f"ADD COLUMN {col} INTEGER NOT NULL DEFAULT "
                    f"{1 if default == 'TRUE' else 0}"
                ))
            logger.info("Added column %s", col)
    logger.info("add_favorite_gifters_notify: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

"""Drop unused profile-stat columns from `tiktok_subscriptions`.

Removes `video_count` and `like_count` — both were populated by the
public-profile scraper from the `__UNIVERSAL_DATA_FOR_REHYDRATION__`
blob but never surfaced in the operator UI or aggregated anywhere.
The corresponding `friend_count` was only a transient scraper field
(never persisted), so this migration only touches the DB columns
that actually exist.

Idempotent. Safe to re-run. PostgreSQL + SQLite (dev) compatible.

Run:
    python database/migrations/drop_subscription_unused_count_columns.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, inspect  # noqa: E402

from database.core.connection import create_database_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


_TABLE = "tiktok_subscriptions"
_COLUMNS = ("video_count", "like_count")


def _drop_columns(engine) -> None:
    """Drop each unused column if present. ALTER TABLE DROP COLUMN
    is supported on both Postgres and SQLite 3.35+. We inspect the
    current schema first so a re-run on a partially-migrated DB is
    a clean no-op."""
    insp = inspect(engine)
    if _TABLE not in insp.get_table_names():
        logger.info("Table %s not found — skipping.", _TABLE)
        return
    existing = {c["name"] for c in insp.get_columns(_TABLE)}
    with engine.begin() as c:
        for col in _COLUMNS:
            if col not in existing:
                logger.info("Column %s.%s already absent — skipping.", _TABLE, col)
                continue
            try:
                c.execute(text(f"ALTER TABLE {_TABLE} DROP COLUMN {col}"))
                logger.info("Dropped %s.%s.", _TABLE, col)
            except Exception:
                logger.exception(
                    "Failed to drop %s.%s (continuing).", _TABLE, col,
                )


def migrate() -> None:
    engine = create_database_engine()
    _drop_columns(engine)
    logger.info("drop_subscription_unused_count_columns: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

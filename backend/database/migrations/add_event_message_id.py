"""Add `tiktok_events.message_id` (TikTok server-assigned per-emission ID)
plus a partial unique index that makes WS-reconnect cursor-replay
duplicates structurally impossible.

Idempotent. Safe to re-run.

Why a partial unique index:
  Old rows pre-date capture and have message_id IS NULL. A normal
  unique constraint would force them through it; a partial constraint
  (`WHERE message_id IS NOT NULL`) only enforces uniqueness on rows
  that actually carry a TikTok-assigned id. Going forward, every
  inserted row carries one and dedup is exact.

Why composite (room_id, message_id) and not just message_id:
  TikTok message_ids are globally unique in practice but indexing per
  room is cheaper to maintain (smaller tree per room, locality on the
  hot insert path) and is the natural key the ON CONFLICT clause uses
  in `persist_event_full`.
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


def _index_exists(engine, table: str, index: str) -> bool:
    insp = inspect(engine)
    return any(ix["name"] == index for ix in insp.get_indexes(table))


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        # 1. Add the column (BIGINT, nullable).
        if not _column_exists(engine, "tiktok_events", "message_id"):
            int_type = "BIGINT" if dialect == "postgresql" else "INTEGER"
            c.execute(text(
                f"ALTER TABLE tiktok_events ADD COLUMN message_id {int_type}"
            ))
            logger.info("Added column tiktok_events.message_id")
        else:
            logger.info("Column tiktok_events.message_id already exists; skipping.")

        # 2. Create the partial unique index. Postgres supports the
        # `WHERE` clause; SQLite (dev) needs the same `WHERE` syntax —
        # which it does support, since 3.8.
        idx_name = "tiktok_events_room_msg_uniq"
        if not _index_exists(engine, "tiktok_events", idx_name):
            if dialect == "postgresql":
                c.execute(text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} "
                    "ON tiktok_events (room_id, message_id) "
                    "WHERE message_id IS NOT NULL"
                ))
            else:
                c.execute(text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} "
                    "ON tiktok_events (room_id, message_id) "
                    "WHERE message_id IS NOT NULL"
                ))
            logger.info("Created partial unique index %s", idx_name)
        else:
            logger.info("Index %s already exists; skipping.", idx_name)
    logger.info("add_event_message_id: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.exception("add_event_message_id: failed: %s", e)
        sys.exit(1)

"""Add `tiktok_notifications` — server-persisted notification history
that backs the iOS-style notification center on /admin/tiktok.

Idempotent. Safe to re-run.

Schema:
  id              BIGSERIAL    PRIMARY KEY
  ts              TIMESTAMPTZ  NOT NULL DEFAULT now()  -- when the
                                                         underlying event
                                                         happened (or was
                                                         received)
  type            TEXT         NOT NULL                 -- 'gift' | 'comment'
                                                         | 'join' | 'system'
  title           TEXT         NOT NULL                 -- one-line summary
  body            TEXT                                   -- optional 2nd line
  host_unique_id  TEXT                                   -- broadcast host;
                                                         drives the click-
                                                         through link
  user_id         BIGINT                                 -- gifter / actor;
                                                         nullable for system
  payload         JSONB                                  -- raw event for
                                                         drill (tolerant
                                                         shape)
  read            BOOLEAN      NOT NULL DEFAULT FALSE
  cleared         BOOLEAN      NOT NULL DEFAULT FALSE   -- soft-delete; we
                                                         keep cleared rows
                                                         for a short window
                                                         to support undo
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()

Indexes:
  ts DESC                                                -- list endpoint
  read partial                                           -- unread_count is hot
  host_unique_id                                         -- per-host filter
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
                CREATE TABLE IF NOT EXISTS tiktok_notifications (
                    id              BIGSERIAL   PRIMARY KEY,
                    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
                    type            TEXT        NOT NULL,
                    title           TEXT        NOT NULL,
                    body            TEXT,
                    host_unique_id  TEXT,
                    user_id         BIGINT,
                    payload         JSONB,
                    read            BOOLEAN     NOT NULL DEFAULT FALSE,
                    cleared         BOOLEAN     NOT NULL DEFAULT FALSE,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            c.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_tiktok_notifications_ts "
                "ON tiktok_notifications (ts DESC)"
            ))
            # Partial index — unread_count is the most-called read path.
            c.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_tiktok_notifications_unread "
                "ON tiktok_notifications (id) "
                "WHERE NOT read AND NOT cleared"
            ))
            c.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_tiktok_notifications_host "
                "ON tiktok_notifications (host_unique_id) "
                "WHERE host_unique_id IS NOT NULL"
            ))
        else:
            # SQLite — no JSONB, no partial-index WHERE on simple columns.
            c.execute(text("""
                CREATE TABLE IF NOT EXISTS tiktok_notifications (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts              TEXT    NOT NULL DEFAULT (datetime('now')),
                    type            TEXT    NOT NULL,
                    title           TEXT    NOT NULL,
                    body            TEXT,
                    host_unique_id  TEXT,
                    user_id         INTEGER,
                    payload         TEXT,
                    read            INTEGER NOT NULL DEFAULT 0,
                    cleared         INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """))
            c.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_tiktok_notifications_ts "
                "ON tiktok_notifications (ts DESC)"
            ))
    logger.info("add_notifications: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

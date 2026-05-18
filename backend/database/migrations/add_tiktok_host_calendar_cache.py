"""Add `tiktok_host_calendar_cache` — per-(host, tz, day) materialised
cache for the heatmap on the live-detail page.

Idempotent. Safe to re-run.

Why:
  `host_calendar()` aggregates events / rooms / matches per host-day
  with a 4-CTE Postgres query. On a busy host (4000+ rooms over 90
  days) the cold-load shape is ~2.7 s and the in-memory cache it had
  before this table died on every uvicorn restart.

  The cache table makes the per-day result a write-once read-many fact
  for any day in the past (frozen — events from yesterday won't change)
  and a 5-min-TTL'd refresh for today. Both the API (lazy populator
  on cache-miss) and the new `system tiktok warm-caches` CLI
  (proactive populator) write to this table; their `computed_at`
  timestamps coordinate without locks — neither does redundant work
  when the other got there first.

Schema:
  CREATE TABLE tiktok_host_calendar_cache (
      host_unique_id   TEXT        NOT NULL,
      tz               TEXT        NOT NULL,
      day              DATE        NOT NULL,
      rooms            INTEGER     NOT NULL DEFAULT 0,
      duration_seconds BIGINT      NOT NULL DEFAULT 0,
      diamonds         BIGINT      NOT NULL DEFAULT 0,
      matches          INTEGER     NOT NULL DEFAULT 0,
      computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (host_unique_id, tz, day)
  );

  CREATE INDEX ix_tiktok_host_calendar_cache_computed
    ON tiktok_host_calendar_cache (computed_at);

  CREATE INDEX ix_tiktok_host_calendar_cache_host_day
    ON tiktok_host_calendar_cache (host_unique_id, day DESC);

SQLite branch keeps the same shape with TEXT/INTEGER fallbacks so
local dev can exercise the cache path without Postgres-specific types.
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

TABLE = "tiktok_host_calendar_cache"


def _table_exists(engine, name: str) -> bool:
    return name in inspect(engine).get_table_names()


def _index_exists(engine, table: str, name: str) -> bool:
    try:
        return any(ix["name"] == name for ix in inspect(engine).get_indexes(table))
    except Exception:
        return False


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        if _table_exists(engine, TABLE):
            logger.info("%s already exists — skipping CREATE TABLE.", TABLE)
        else:
            if dialect == "postgresql":
                c.execute(text(f"""
                    CREATE TABLE {TABLE} (
                        host_unique_id   TEXT        NOT NULL,
                        tz               TEXT        NOT NULL,
                        day              DATE        NOT NULL,
                        rooms            INTEGER     NOT NULL DEFAULT 0,
                        duration_seconds BIGINT      NOT NULL DEFAULT 0,
                        diamonds         BIGINT      NOT NULL DEFAULT 0,
                        matches          INTEGER     NOT NULL DEFAULT 0,
                        computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (host_unique_id, tz, day)
                    )
                """))
            else:  # SQLite
                c.execute(text(f"""
                    CREATE TABLE {TABLE} (
                        host_unique_id   TEXT    NOT NULL,
                        tz               TEXT    NOT NULL,
                        day              TEXT    NOT NULL,
                        rooms            INTEGER NOT NULL DEFAULT 0,
                        duration_seconds INTEGER NOT NULL DEFAULT 0,
                        diamonds         INTEGER NOT NULL DEFAULT 0,
                        matches          INTEGER NOT NULL DEFAULT 0,
                        computed_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (host_unique_id, tz, day)
                    )
                """))
            logger.info("Created %s.", TABLE)

        ix_computed = "ix_tiktok_host_calendar_cache_computed"
        ix_host_day = "ix_tiktok_host_calendar_cache_host_day"

        if not _index_exists(engine, TABLE, ix_computed):
            c.execute(text(
                f"CREATE INDEX {ix_computed} ON {TABLE} (computed_at)"
            ))
            logger.info("Created index %s.", ix_computed)
        else:
            logger.info("Index %s already exists.", ix_computed)

        if not _index_exists(engine, TABLE, ix_host_day):
            if dialect == "postgresql":
                c.execute(text(
                    f"CREATE INDEX {ix_host_day} ON {TABLE} "
                    "(host_unique_id, day DESC)"
                ))
            else:
                c.execute(text(
                    f"CREATE INDEX {ix_host_day} ON {TABLE} "
                    "(host_unique_id, day)"
                ))
            logger.info("Created index %s.", ix_host_day)
        else:
            logger.info("Index %s already exists.", ix_host_day)

    logger.info("add_tiktok_host_calendar_cache: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

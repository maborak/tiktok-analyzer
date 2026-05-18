"""Add `tiktok_room_stats_cache` — JSONB-payload cache for the
service-layer `get_room_stats(room_id, since, until, ...)` response.

Idempotent. Safe to re-run.

Why:
  `/admin/tiktok/rooms/{room_id}/stats` is the highest-volume traced
  endpoint (~7000+ calls in 24 h). The handler aggregates 4–5 indexed
  SELECTs (event counts, top gifters, time buckets, active match). For
  any (room, since, until) window whose `until` is more than a minute
  in the past, the answer is IMMUTABLE — no new events can land in
  that window. We persist the rendered response keyed on those
  parameters so subsequent visits skip the aggregation entirely.

  Pairs with an in-memory L1 cache in the service layer; L2 here
  survives uvicorn restarts and is shared with the worker process.

Schema:
  CREATE TABLE tiktok_room_stats_cache (
      room_id     BIGINT      NOT NULL,
      params_key  TEXT        NOT NULL,
      payload     JSONB       NOT NULL,
      computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (room_id, params_key)
  );

  CREATE INDEX ix_tiktok_room_stats_cache_computed
    ON tiktok_room_stats_cache (computed_at);

Why `params_key TEXT` instead of separate since/until/bucket columns:
  The handler accepts an open-ended parameter shape (window_minutes,
  bucket_seconds, since, until, gifters_limit) and may grow more
  someday. Stashing the canonicalised parameter string keeps the
  schema stable across handler-signature changes — only the
  serialiser in the persistence layer needs to evolve.
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

TABLE = "tiktok_room_stats_cache"


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
                        room_id     BIGINT      NOT NULL,
                        params_key  TEXT        NOT NULL,
                        payload     JSONB       NOT NULL,
                        computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (room_id, params_key)
                    )
                """))
            else:  # SQLite
                c.execute(text(f"""
                    CREATE TABLE {TABLE} (
                        room_id     INTEGER NOT NULL,
                        params_key  TEXT    NOT NULL,
                        payload     TEXT    NOT NULL,
                        computed_at TEXT    NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (room_id, params_key)
                    )
                """))
            logger.info("Created %s.", TABLE)

        ix_computed = "ix_tiktok_room_stats_cache_computed"
        if not _index_exists(engine, TABLE, ix_computed):
            c.execute(text(
                f"CREATE INDEX {ix_computed} ON {TABLE} (computed_at)"
            ))
            logger.info("Created index %s.", ix_computed)
        else:
            logger.info("Index %s already exists.", ix_computed)

    logger.info("add_tiktok_room_stats_cache: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

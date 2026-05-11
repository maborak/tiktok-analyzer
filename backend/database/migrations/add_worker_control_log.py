"""DB-only worker control: command + desired_status columns on
tiktok_workers, plus tiktok_worker_log for lifecycle/audit events.

Idempotent. Safe to re-run.

Why: replaces the file-based flock + signal-based pause/resume/kill
with DB writes. Workers poll their own row + log lifecycle events.
The admin UI / API mutate the same columns to issue orders.

Schema:
  tiktok_workers — additions:
    desired_status   TEXT  default 'running'  -- admin-requested target
    command          TEXT  nullable           -- one-shot order
    command_issued_at TIMESTAMPTZ
    command_acked_at  TIMESTAMPTZ

  tiktok_worker_log — new:
    id                BIGSERIAL PK
    worker_id         FK tiktok_workers.id ON DELETE CASCADE
    ts                TIMESTAMPTZ default now()
    level             TEXT  ('info' | 'warn' | 'error')
    event             TEXT  short tag — 'startup', 'session_start', etc.
    handle            TEXT  nullable — relevant subscription
    detail            JSONB nullable — structured extras
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
        # ── tiktok_workers extensions ────────────────────────────────
        for col, ddl in [
            ("desired_status",
             f"ALTER TABLE tiktok_workers ADD COLUMN desired_status TEXT NOT NULL DEFAULT 'running'"),
            ("command",
             f"ALTER TABLE tiktok_workers ADD COLUMN command TEXT"),
            ("command_issued_at",
             f"ALTER TABLE tiktok_workers ADD COLUMN command_issued_at {ts_type}"),
            ("command_acked_at",
             f"ALTER TABLE tiktok_workers ADD COLUMN command_acked_at {ts_type}"),
        ]:
            if not _column_exists(engine, "tiktok_workers", col):
                c.execute(text(ddl))
                logger.info("Added column tiktok_workers.%s", col)

        # ── tiktok_worker_log ─────────────────────────────────────────
        if dialect == "postgresql":
            c.execute(text("""
                CREATE TABLE IF NOT EXISTS tiktok_worker_log (
                    id BIGSERIAL PRIMARY KEY,
                    worker_id INTEGER REFERENCES tiktok_workers(id) ON DELETE CASCADE,
                    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                    level TEXT NOT NULL DEFAULT 'info',
                    event TEXT NOT NULL,
                    handle TEXT,
                    detail JSONB
                )
            """))
        else:
            c.execute(text("""
                CREATE TABLE IF NOT EXISTS tiktok_worker_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id INTEGER,
                    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    level TEXT NOT NULL DEFAULT 'info',
                    event TEXT NOT NULL,
                    handle TEXT,
                    detail TEXT
                )
            """))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tiktok_worker_log_worker_ts "
            "ON tiktok_worker_log (worker_id, ts DESC)"
        ))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tiktok_worker_log_event "
            "ON tiktok_worker_log (event)"
        ))
    logger.info("add_worker_control_log: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

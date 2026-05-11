"""Add a worker-registry + per-subscription assignment lease to support
multi-worker TikTok ingestion.

Idempotent. Safe to re-run.

Schema:
  - `tiktok_workers` — one row per running worker process. Heartbeat
    `last_heartbeat_at` extended every 5s; stale rows are reaped after
    30s by other workers on startup or by the live-status query.
  - `tiktok_subscriptions.assigned_worker_id` (FK → tiktok_workers.id,
    SET NULL on delete) — which worker currently owns this handle.
  - `tiktok_subscriptions.assignment_lease_until` — when the lease
    expires; another worker can re-claim if expired even if the
    assigned_worker_id row still exists (worker died abruptly).

This replaces the flock-based single-worker mutex with a multi-worker
coordination primitive. The flock stays in place as a single-host
fallback until we drop it explicitly.
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


def _create_workers_table(c, dialect: str) -> None:
    if dialect == "postgresql":
        c.execute(text("""
            CREATE TABLE IF NOT EXISTS tiktok_workers (
                id SERIAL PRIMARY KEY,
                worker_key TEXT NOT NULL UNIQUE,
                host TEXT NOT NULL,
                pid INTEGER NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                status TEXT NOT NULL DEFAULT 'running',
                capacity INTEGER NOT NULL DEFAULT 30,
                sessions_count INTEGER NOT NULL DEFAULT 0,
                metadata JSONB
            )
        """))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tiktok_workers_heartbeat "
            "ON tiktok_workers (last_heartbeat_at)"
        ))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_tiktok_workers_status "
            "ON tiktok_workers (status)"
        ))
    else:
        # SQLite dev fallback.
        c.execute(text("""
            CREATE TABLE IF NOT EXISTS tiktok_workers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_key TEXT NOT NULL UNIQUE,
                host TEXT NOT NULL,
                pid INTEGER NOT NULL,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_heartbeat_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'running',
                capacity INTEGER NOT NULL DEFAULT 30,
                sessions_count INTEGER NOT NULL DEFAULT 0,
                metadata TEXT
            )
        """))


def _add_assignment_columns(c, engine, dialect: str) -> None:
    """Add `assigned_worker_id` + `assignment_lease_until` to subscriptions.
    SQLite can't ALTER ... ADD COLUMN with FK in older versions, so we
    skip the FK there and rely on application-level integrity."""
    if not _column_exists(engine, "tiktok_subscriptions", "assigned_worker_id"):
        if dialect == "postgresql":
            c.execute(text(
                "ALTER TABLE tiktok_subscriptions "
                "ADD COLUMN assigned_worker_id INTEGER "
                "REFERENCES tiktok_workers(id) ON DELETE SET NULL"
            ))
        else:
            c.execute(text(
                "ALTER TABLE tiktok_subscriptions "
                "ADD COLUMN assigned_worker_id INTEGER"
            ))
        logger.info("Added column tiktok_subscriptions.assigned_worker_id")

    if not _column_exists(engine, "tiktok_subscriptions", "assignment_lease_until"):
        ts_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TIMESTAMP"
        c.execute(text(
            f"ALTER TABLE tiktok_subscriptions "
            f"ADD COLUMN assignment_lease_until {ts_type}"
        ))
        logger.info("Added column tiktok_subscriptions.assignment_lease_until")

    # Index used by the claim query (assigned IS NULL OR lease < now()).
    c.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_tiktok_subs_assignment "
        "ON tiktok_subscriptions (assigned_worker_id, assignment_lease_until)"
    ))


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name
    # Run each DDL with AUTOCOMMIT — pgbouncer in transaction-pool mode
    # is fragile when a single transaction issues multiple ALTERs against
    # different tables (we lose the connection mid-stream). Per-statement
    # autocommit avoids that. Each helper internally checks idempotence.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        _create_workers_table(c, dialect)
        _add_assignment_columns(c, engine, dialect)
    logger.info("add_tiktok_worker_registry: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

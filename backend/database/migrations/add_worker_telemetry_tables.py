"""Telemetry tables for the worker dashboard.

Idempotent. Safe to re-run.

Two new tables fed by hooks already on the listener-pool hot path:

  * tiktok_worker_heartbeat_log
      One row every ~5s per worker process. Captures the snapshot
      that the existing `_db_heartbeat_loop` already writes to the
      `tiktok_workers` registry (sessions_count, connected_count,
      capacity) PLUS process memory + CPU. The registry row is
      overwritten on every tick — this log preserves history so the
      dashboard can chart "sessions held over time" instead of just
      the current value.

  * tiktok_event_type_hour_counts
      Per-(host, hour, type) ingest counter, bumped inline from the
      same `_bump_event_hour_count` hook that already maintains
      `tiktok_event_hour_counts`. Lets per-event-type charts read
      ≤24×N×T rows instead of scanning the full event stream.

Schemas:

  tiktok_worker_heartbeat_log
    id                BIGSERIAL PK
    ts                TIMESTAMPTZ DEFAULT NOW()
    worker_id         INT NULL  (FK to tiktok_workers.id; nullable
                                 so a heartbeat from a process whose
                                 registry row was reaped still logs)
    sessions_count    INT       (held)
    connected_count   INT       (subset that's CONNECTED)
    capacity          INT
    memory_rss_mb     INT       (process RSS in MB, rounded)
    cpu_pct           REAL      (process CPU % since previous sample)
    INDEX (ts DESC)
    INDEX (worker_id, ts DESC)

  tiktok_event_type_hour_counts
    host_unique_id    VARCHAR(64)
    hour_bucket       TIMESTAMPTZ
    type              VARCHAR(32)
    n                 INT
    PRIMARY KEY (host_unique_id, hour_bucket, type)
    INDEX (hour_bucket DESC, type)

Run:
    python database/migrations/add_worker_telemetry_tables.py
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


def _table_exists(engine, name: str) -> bool:
    insp = inspect(engine)
    return insp.has_table(name)


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "add_worker_telemetry_tables: dialect=%s — skipping (Postgres only).",
            engine.dialect.name,
        )
        return

    # ── tiktok_worker_heartbeat_log ─────────────────────────────────
    if _table_exists(engine, "tiktok_worker_heartbeat_log"):
        logger.info("tiktok_worker_heartbeat_log exists — skipping CREATE.")
    else:
        with engine.begin() as c:
            c.execute(text("""
                CREATE TABLE tiktok_worker_heartbeat_log (
                    id              BIGSERIAL PRIMARY KEY,
                    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    worker_id       INTEGER,
                    sessions_count  INTEGER NOT NULL DEFAULT 0,
                    connected_count INTEGER NOT NULL DEFAULT 0,
                    capacity        INTEGER NOT NULL DEFAULT 0,
                    memory_rss_mb   INTEGER,
                    cpu_pct         REAL
                )
            """))
        logger.info("Created tiktok_worker_heartbeat_log.")
    with engine.begin() as c:
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_hb_log_ts "
            "ON tiktok_worker_heartbeat_log (ts DESC)"
        ))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_hb_log_worker_ts "
            "ON tiktok_worker_heartbeat_log (worker_id, ts DESC)"
        ))

    # ── tiktok_event_type_hour_counts ───────────────────────────────
    if _table_exists(engine, "tiktok_event_type_hour_counts"):
        logger.info("tiktok_event_type_hour_counts exists — skipping CREATE.")
    else:
        with engine.begin() as c:
            c.execute(text("""
                CREATE TABLE tiktok_event_type_hour_counts (
                    host_unique_id  VARCHAR(64) NOT NULL,
                    hour_bucket     TIMESTAMPTZ NOT NULL,
                    type            VARCHAR(32) NOT NULL,
                    n               INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (host_unique_id, hour_bucket, type)
                )
            """))
        logger.info("Created tiktok_event_type_hour_counts.")
    with engine.begin() as c:
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_event_type_hour_hb_type "
            "ON tiktok_event_type_hour_counts (hour_bucket DESC, type)"
        ))

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        try:
            c.execute(text("ANALYZE tiktok_worker_heartbeat_log"))
            c.execute(text("ANALYZE tiktok_event_type_hour_counts"))
        except Exception:
            logger.exception("ANALYZE failed (continuing).")
    logger.info("add_worker_telemetry_tables: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

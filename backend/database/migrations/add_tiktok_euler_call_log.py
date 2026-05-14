"""Create `tiktok_euler_call_log` — one row per Euler-signed HTTP call.

Idempotent. Safe to re-run.

Captures every request the TikTokLive lib makes against EulerStream's
signing service (and the signed `webcast.tiktok.com/webcast/*` URLs
that go through the same per-request signing budget) so we can answer
"what burned my Euler quota?" with hard data instead of guessing from
worker-restart counts.

Schema:
  id          BIGSERIAL PRIMARY KEY
  ts          TIMESTAMPTZ DEFAULT NOW()           — call start
  api_key_fp  VARCHAR(48)                          — fingerprint of the
                                                     Euler API key in use
                                                     ("euler_OG…UxNjkx (78)").
                                                     Lets the dashboard
                                                     differentiate calls
                                                     across key rotations
                                                     without storing the
                                                     full secret.
  endpoint    VARCHAR(96)                          — short label:
                                                     "room/info",
                                                     "webcast/fetch",
                                                     "check_alive", etc.
  handle      VARCHAR(64) NULL                     — `unique_id=…` from
                                                     the query, when
                                                     extractable.
  status_code INT NULL                             — HTTP status
                                                     (NULL on network err)
  latency_ms  INT NULL                             — server response time
  error_kind  VARCHAR(64) NULL                     — exception class
                                                     ("ConnectError",
                                                     "ReadTimeout", …) when
                                                     status_code is NULL

Indexes:
  (ts DESC)                                         — histogram scan
  (api_key_fp, ts DESC)                             — per-key drill-down
  (endpoint, ts DESC)                               — per-endpoint slice

Postgres-only — SQLite dev path is a no-op (the worker doesn't run
under SQLite in practice; capture is for the production listener).

Run:
    python database/migrations/add_tiktok_euler_call_log.py
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
            "add_tiktok_euler_call_log: dialect=%s — skipping (Postgres only).",
            engine.dialect.name,
        )
        return

    if _table_exists(engine, "tiktok_euler_call_log"):
        logger.info("tiktok_euler_call_log already exists — skipping CREATE.")
    else:
        with engine.begin() as c:
            c.execute(text("""
                CREATE TABLE tiktok_euler_call_log (
                    id          BIGSERIAL PRIMARY KEY,
                    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    api_key_fp  VARCHAR(48) NOT NULL,
                    endpoint    VARCHAR(96) NOT NULL,
                    handle      VARCHAR(64),
                    status_code INTEGER,
                    latency_ms  INTEGER,
                    error_kind  VARCHAR(64)
                )
            """))
        logger.info("Created table tiktok_euler_call_log.")

    # Indexes — CREATE IF NOT EXISTS is supported by PG 9.5+, and these
    # are small enough that CONCURRENTLY isn't worth the complexity.
    with engine.begin() as c:
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_euler_call_log_ts "
            "ON tiktok_euler_call_log (ts DESC)"
        ))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_euler_call_log_key_ts "
            "ON tiktok_euler_call_log (api_key_fp, ts DESC)"
        ))
        c.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_euler_call_log_endpoint_ts "
            "ON tiktok_euler_call_log (endpoint, ts DESC)"
        ))
    logger.info("Indexes ensured (ts; api_key_fp+ts; endpoint+ts).")

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        try:
            c.execute(text("ANALYZE tiktok_euler_call_log"))
        except Exception:
            logger.exception("ANALYZE failed (continuing).")
    logger.info("add_tiktok_euler_call_log: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

"""Extend the `ledgersource` PG enum with `MONITOR_TIKTOK` +
`MONITOR_TIKTOK_REFUND` so the credit ledger can record TikTok-monitor
adds (1 credit debit) + refunds (positive credit within 24 h).

Idempotent. Safe to re-run.

Why:
  The TikTok-monitor product is the second credit-consuming feature
  on this install (after `TRACK_PRODUCT`). Each user-added monitor
  costs 1 credit (recorded as amount=-1, source=MONITOR_TIKTOK).
  Removing the monitor within 24 h refunds the credit (amount=+1,
  source=MONITOR_TIKTOK_REFUND). The Python enum
  `domain.entities.billing_models.LedgerSource` was extended in the
  same commit; this migration teaches the DB-side enum about the new
  members so SQLAlchemy can write them.

Schema change:
  ALTER TYPE ledgersource ADD VALUE IF NOT EXISTS 'MONITOR_TIKTOK';
  ALTER TYPE ledgersource ADD VALUE IF NOT EXISTS 'MONITOR_TIKTOK_REFUND';

`ADD VALUE IF NOT EXISTS` is the idempotent form — re-running this
migration on a DB that already has the values is a no-op.

SQLite: no enum type — Python-side enum is enforced by the model.
This script is a no-op for SQLite installs.
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
    if engine.dialect.name != "postgresql":
        logger.info(
            "Dialect is %s — no enum type, nothing to migrate.",
            engine.dialect.name,
        )
        return

    # `ALTER TYPE ... ADD VALUE` cannot run inside a transaction block
    # in older Postgres; AUTOCOMMIT bypasses that.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for name in ("MONITOR_TIKTOK", "MONITOR_TIKTOK_REFUND"):
            c.execute(text(
                f"ALTER TYPE ledgersource ADD VALUE IF NOT EXISTS '{name}'"
            ))
            logger.info("ledgersource has %s (added or already present).", name)

    logger.info("add_ledger_source_monitor_tiktok: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

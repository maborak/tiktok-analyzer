"""Add `tiktok_viewers.enigma_aliases` — every distinct Enigma alias
ever observed for a given user_id.

Idempotent. Safe to re-run.

Why:
  `is_enigma` is a sticky boolean — it tells us "this user has been
  seen anonymous at least once" but loses the placeholder string
  itself. Operators want to recognise specific placeholders
  ("Enigma 24048" = this whale) without re-reading the event log.
  This column persists the set so the profile modal can render each
  alias as a small badge alongside the real identity.

Schema change:
  ALTER TABLE tiktok_viewers
    ADD COLUMN enigma_aliases JSONB NOT NULL DEFAULT '[]';

Backfill:
  For each is_enigma viewer, collect distinct Enigma-shaped nicknames
  from `tiktok_events.payload` for the same user_id.
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
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        if _column_exists(engine, "tiktok_viewers", "enigma_aliases"):
            logger.info(
                "tiktok_viewers.enigma_aliases already exists — skipping ADD COLUMN."
            )
        else:
            if dialect == "postgresql":
                c.execute(text(
                    "ALTER TABLE tiktok_viewers "
                    "ADD COLUMN enigma_aliases JSONB NOT NULL DEFAULT '[]'::jsonb"
                ))
            else:  # SQLite — JSON1 extension stores as TEXT under the hood
                c.execute(text(
                    "ALTER TABLE tiktok_viewers "
                    "ADD COLUMN enigma_aliases TEXT NOT NULL DEFAULT '[]'"
                ))
            logger.info("Added tiktok_viewers.enigma_aliases column.")

        if dialect != "postgresql":
            logger.info("Backfill skipped (SQLite — JSONB aggregate not supported).")
            return

        # Backfill (union-based, masked-only): for each is_enigma
        # viewer, take the UNION of any aliases already on the row
        # PLUS every distinct Enigma placeholder from event payloads
        # where BOTH the payload nickname AND unique_id are the
        # masked string. The `unique_id` predicate filters out
        # vanity users — someone who chose "Enigma 89757" as their
        # display name still has a real `@handle` in unique_id, so
        # that event won't qualify.
        res = c.execute(text("""
            UPDATE tiktok_viewers v
            SET enigma_aliases = (
              SELECT jsonb_agg(DISTINCT nick ORDER BY nick)
              FROM (
                SELECT jsonb_array_elements_text(v.enigma_aliases) AS nick
                UNION
                SELECT e.payload->'user'->>'nickname' AS nick
                FROM tiktok_events e
                WHERE e.user_id = v.user_id
                  AND e.payload->'user'->>'nickname'  ~* '^Enigma\\s+\\d+$'
                  AND e.payload->'user'->>'unique_id' ~* '^Enigma\\s+\\d+$'
              ) all_aliases
              WHERE nick IS NOT NULL
            )
            WHERE v.is_enigma = TRUE
        """))
        flipped = getattr(res, "rowcount", -1)
        if flipped > 0:
            logger.info("Backfill: union-populated enigma_aliases on %d row(s).", flipped)
        else:
            logger.info("Backfill: no rows needed seeding.")

    logger.info("add_viewer_enigma_aliases: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

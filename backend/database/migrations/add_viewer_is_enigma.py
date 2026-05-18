"""Add `tiktok_viewers.is_enigma` — sticky flag for users we've seen
gift under TikTok's Enigma anonymity mask.

Idempotent. Safe to re-run.

Why:
  TikTok's anonymous-gifting ("Enigma") mode replaces the gifter's
  display name with `"Enigma <NNN>"` placeholders in gift events
  while leaving the real `user_id` intact. The placeholder isn't
  stable across rooms / sessions, so it pollutes the gifter ledger
  (every Enigma sighting looks like a one-off whale). We mark the
  underlying user_id once and surface a badge wherever their real
  profile renders — the operator can spot a known gifter who's
  trying to go quiet.

Schema change:
  ALTER TABLE tiktok_viewers
    ADD COLUMN is_enigma BOOLEAN NOT NULL DEFAULT FALSE;

Backfill:
  UPDATE tiktok_viewers
    SET is_enigma = TRUE
    WHERE nickname ~* '^Enigma\\s+\\d+$';
  (Postgres regex match — case-insensitive. SQLite uses LIKE.)
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
        if _column_exists(engine, "tiktok_viewers", "is_enigma"):
            logger.info("tiktok_viewers.is_enigma already exists — skipping ADD COLUMN.")
        else:
            if dialect == "postgresql":
                c.execute(text(
                    "ALTER TABLE tiktok_viewers "
                    "ADD COLUMN is_enigma BOOLEAN NOT NULL DEFAULT FALSE"
                ))
            else:  # SQLite
                c.execute(text(
                    "ALTER TABLE tiktok_viewers "
                    "ADD COLUMN is_enigma BOOLEAN NOT NULL DEFAULT 0"
                ))
            logger.info("Added tiktok_viewers.is_enigma column.")

        # Backfill pass A: viewers whose CURRENT row's BOTH nickname
        # AND unique_id are Enigma placeholders. Requires both
        # fields to match — TikTok masks them identically. A viewer
        # whose nickname is "Enigma 89757" but whose unique_id is a
        # real handle (e.g. "dayan.turcios") is a VANITY user, not
        # an anonymous gifter, and must NOT be flagged.
        if dialect == "postgresql":
            res_a = c.execute(text(
                "UPDATE tiktok_viewers "
                "SET is_enigma = TRUE "
                "WHERE is_enigma = FALSE "
                "  AND nickname  ~* '^Enigma\\s+\\d+$' "
                "  AND unique_id ~* '^Enigma\\s+\\d+$'"
            ))
        else:  # SQLite — glob-based equivalents.
            res_a = c.execute(text(
                "UPDATE tiktok_viewers "
                "SET is_enigma = 1 "
                "WHERE is_enigma = 0 "
                "  AND nickname LIKE 'Enigma %' "
                "  AND nickname  GLOB 'Enigma [0-9]*' "
                "  AND unique_id GLOB 'Enigma [0-9]*'"
            ))
        flipped_a = getattr(res_a, "rowcount", -1)
        if flipped_a > 0:
            logger.info("Backfill A (current-row both-fields match): flipped %d row(s).", flipped_a)

        # Backfill pass B: any user_id whose EVENT HISTORY contains a
        # truly-masked event (both payload fields are the placeholder)
        # gets flagged, even when their viewer row now carries a real
        # name. This is the deanonymisation gold case.
        if dialect == "postgresql":
            res_b = c.execute(text("""
                UPDATE tiktok_viewers v
                SET is_enigma = TRUE
                WHERE v.is_enigma = FALSE
                  AND EXISTS (
                    SELECT 1
                    FROM tiktok_events e
                    WHERE e.user_id = v.user_id
                      AND e.payload->'user'->>'nickname'  ~* '^Enigma\\s+\\d+$'
                      AND e.payload->'user'->>'unique_id' ~* '^Enigma\\s+\\d+$'
                  )
            """))
            flipped_b = getattr(res_b, "rowcount", -1)
            if flipped_b > 0:
                logger.info(
                    "Backfill B (event-payload both-fields match): flipped %d row(s).",
                    flipped_b,
                )
        else:
            logger.info(
                "Backfill B skipped (SQLite — JSONB extract path not available)."
            )
            flipped_b = 0

        # Backfill pass C: DEMOTE vanity false-positives. Any viewer
        # currently flagged TRUE but with NO truly-masked event in
        # history is a vanity user whose display name just happened to
        # match the placeholder pattern. Pre-tightening logic that
        # checked nickname only would flag them; this pass corrects
        # the record. Resets `enigma_aliases` too when that column
        # exists (added by a later migration; defensive check here).
        flipped_c = 0
        if dialect == "postgresql":
            has_aliases = _column_exists(engine, "tiktok_viewers", "enigma_aliases")
            extra_set = ", enigma_aliases = '[]'::jsonb" if has_aliases else ""
            res_c = c.execute(text(f"""
                UPDATE tiktok_viewers v
                SET is_enigma = FALSE{extra_set}
                WHERE v.is_enigma = TRUE
                  AND NOT EXISTS (
                    SELECT 1
                    FROM tiktok_events e
                    WHERE e.user_id = v.user_id
                      AND e.payload->'user'->>'nickname'  ~* '^Enigma\\s+\\d+$'
                      AND e.payload->'user'->>'unique_id' ~* '^Enigma\\s+\\d+$'
                  )
            """))
            flipped_c = getattr(res_c, "rowcount", -1)
            if flipped_c > 0:
                logger.info(
                    "Backfill C (demote vanity false-positives): flipped %d row(s).",
                    flipped_c,
                )

        if (flipped_a or 0) + (flipped_b or 0) + (flipped_c or 0) == 0:
            logger.info("Backfill: no rows needed adjustment.")

    logger.info("add_viewer_is_enigma: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

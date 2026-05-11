"""One-shot cleanup of duplicate `tiktok_events` rows that pre-date the
`message_id` capture + partial unique index. Future duplicates can't be
inserted (the index blocks them); this script handles the legacy tail.

Strategy:
  Two passes — one for events that share message_id (post-capture; can
  happen during a brief window where the index hasn't been backfilled
  yet), one for events that share a heuristic identity within a tight
  time window (pre-capture, sub-second only — anything wider would
  collapse legitimate user repetition).

Idempotent. Reports per-room + per-type stats. Always commits in a
single transaction so partial failures don't half-clean a table.

Usage:
    python database/migrations/dedupe_existing_events.py            # dry run
    python database/migrations/dedupe_existing_events.py --apply    # commit
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text  # noqa: E402

from database.core.connection import create_database_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _scan_message_id_dups(c) -> list[dict]:
    """Rows that share (room_id, message_id) — should be impossible
    once the unique index is in place, but we run the pass anyway in
    case rows landed before the index was built."""
    rows = c.execute(text("""
        SELECT room_id, message_id, type, COUNT(*) AS n,
               MIN(id) AS keep_id, MAX(id) AS sample_dup_id
        FROM tiktok_events
        WHERE message_id IS NOT NULL
        GROUP BY room_id, message_id, type
        HAVING COUNT(*) > 1
    """)).mappings().all()
    return [dict(r) for r in rows]


def _scan_payload_dups(c) -> dict[str, int]:
    """Pre-capture heuristic dedup. Tight (<500ms for comments,
    <200ms for gifts) — anything wider would catch legitimate user
    repetition (people genuinely re-post the same emoji). Returns a
    summary dict, not the row list, since the delete is performed
    by id-range in the caller."""
    summary = {"comment_extras": 0, "gift_extras": 0, "like_extras": 0}
    summary["comment_extras"] = c.execute(text("""
        SELECT COALESCE(SUM(n - 1), 0) FROM (
          SELECT COUNT(*) AS n
          FROM tiktok_events
          WHERE type='comment' AND user_id IS NOT NULL
            AND payload->>'text' IS NOT NULL
            AND message_id IS NULL
          GROUP BY room_id, user_id, payload->>'text'
          HAVING COUNT(*) > 1
             AND EXTRACT(EPOCH FROM MAX(ts) - MIN(ts)) < 0.5
        ) d
    """)).scalar() or 0
    summary["gift_extras"] = c.execute(text("""
        SELECT COALESCE(SUM(n - 1), 0) FROM (
          SELECT COUNT(*) AS n
          FROM tiktok_events
          WHERE type='gift' AND user_id IS NOT NULL
            AND message_id IS NULL
          GROUP BY room_id, user_id, payload->>'gift_id', payload->>'repeat_count'
          HAVING COUNT(*) > 1
             AND EXTRACT(EPOCH FROM MAX(ts) - MIN(ts)) < 0.2
        ) d
    """)).scalar() or 0
    return summary


def _delete_payload_dups(c, *, type: str, key_cols: list[str], window_s: float) -> int:
    """Delete duplicate rows of one event type, keeping MIN(id) per group."""
    keys_sql = ", ".join(key_cols)
    deleted = c.execute(text(f"""
        WITH groups AS (
          SELECT array_agg(id ORDER BY id) AS ids,
                 COUNT(*) AS n,
                 EXTRACT(EPOCH FROM MAX(ts) - MIN(ts)) AS span_s
          FROM tiktok_events
          WHERE type = :type
            AND message_id IS NULL
            AND user_id IS NOT NULL
            {('AND payload->>\'text\' IS NOT NULL' if type == 'comment' else '')}
          GROUP BY {keys_sql}
          HAVING COUNT(*) > 1 AND EXTRACT(EPOCH FROM MAX(ts) - MIN(ts)) < :win
        )
        DELETE FROM tiktok_events
        WHERE id IN (
          SELECT unnest(ids[2:]) FROM groups
        )
        RETURNING id
    """), {"type": type, "win": window_s}).rowcount
    return int(deleted or 0)


def main(apply: bool) -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.error("This cleanup is Postgres-only (dev sqlite uses no JSONB ops).")
        sys.exit(2)

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        # Pass 1: message_id duplicates. Should be 0 once the unique
        # index is in place; report any anyway.
        msg_dups = _scan_message_id_dups(c)
        logger.info("(room_id, message_id) duplicate groups: %d", len(msg_dups))
        for d in msg_dups[:10]:
            logger.info(
                "  room=%s msg_id=%s type=%s rows=%d  keep=%s",
                d["room_id"], d["message_id"], d["type"], d["n"], d["keep_id"],
            )

        # Pass 2: pre-capture heuristic dedup.
        summary = _scan_payload_dups(c)
        logger.info(
            "Pre-capture dup candidates — comments: %d  gifts: %d",
            summary["comment_extras"], summary["gift_extras"],
        )

        if not apply:
            logger.info("Dry run only. Re-run with --apply to delete.")
            return

        # Apply.
        if msg_dups:
            for d in msg_dups:
                c.execute(text("""
                    DELETE FROM tiktok_events
                    WHERE room_id = :rid AND message_id = :mid AND id <> :keep
                """), {"rid": d["room_id"], "mid": d["message_id"], "keep": d["keep_id"]})
            logger.info("Removed message_id-dup rows.")

        comment_deleted = _delete_payload_dups(
            c, type="comment",
            key_cols=["room_id", "user_id", "(payload->>'text')"],
            window_s=0.5,
        )
        logger.info("Deleted %d duplicate comment rows", comment_deleted)

        gift_deleted = _delete_payload_dups(
            c, type="gift",
            key_cols=[
                "room_id", "user_id",
                "(payload->>'gift_id')", "(payload->>'repeat_count')",
            ],
            window_s=0.2,
        )
        logger.info("Deleted %d duplicate gift rows", gift_deleted)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Actually delete rows.")
    args = p.parse_args()
    main(apply=args.apply)

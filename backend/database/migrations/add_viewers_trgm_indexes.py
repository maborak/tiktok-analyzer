"""Trigram GIN indexes on `tiktok_viewers` for instant ILIKE search.

Idempotent. Safe to re-run. PostgreSQL only — no-op on SQLite (dev).

Powers the search inputs on:
  - /admin/tiktok ?tab=common      (TikTokCommonGiftersTable)
  - /admin/tiktok ?tab=favorites   (TikTokFavoriteGiftersTable)
  - /admin/tiktok/<handle>  Cross-live tab  (TikTokRoomCrossLiveGiftersTable)

Every per-keystroke query in the admin UI runs

    WHERE COALESCE(v.nickname,'') ILIKE :needle
       OR COALESCE(v.unique_id,'') ILIKE :needle

against `tiktok_viewers`. `ILIKE '%x%'` cannot use a btree index — so
without trigram indexes, each keystroke is a full table scan over
viewers (~100k rows today, growing). At ~500k rows the per-keystroke
cost crosses 200ms and the input feels broken.

`pg_trgm` is a built-in Postgres extension; the GIN indexes it
enables turn the `ILIKE '%x%'` predicate into a fast trigram lookup
(typically <10ms even at millions of rows).

Note: the existing query wraps each column in `COALESCE(..., '')`
which DEFEATS trigram index usage (the index is on the bare column,
not the COALESCE expression). The fix is either to drop the COALESCE
(since `NULL ILIKE :needle` is just `NULL`/false — same as the
COALESCE'd version) or to rewrite to `(v.nickname ILIKE :needle OR
v.unique_id ILIKE :needle) AND NOT :q_is_null`. That's a small
follow-up in `tiktok_persistence.py:common_gifters`,
`count_common_gifters`, `cross_live_gifters_for_host`,
`count_cross_live_gifters_for_host`, and `list_favorite_gifters_enriched`.

Run:
    python database/migrations/add_viewers_trgm_indexes.py
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


def _ensure_extension(engine) -> bool:
    """CREATE EXTENSION pg_trgm — idempotent. Requires superuser on
    most managed Postgres providers, but `pg_trgm` is one of the
    'trusted' extensions in PG 13+ so it works without superuser on
    RDS / Cloud SQL / Supabase. Returns True if the extension is
    available after this call, False if creation failed (the indexes
    below will then fail loudly with a clear error)."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        try:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            logger.info("pg_trgm extension present.")
            return True
        except Exception:
            logger.exception(
                "CREATE EXTENSION pg_trgm failed — "
                "ask a Postgres admin to enable it, then re-run."
            )
            return False


def _create_indexes(engine) -> None:
    """Create the GIN trigram indexes CONCURRENTLY so existing writes
    on `tiktok_viewers` aren't blocked during the build. CONCURRENTLY
    can't run inside a transaction → AUTOCOMMIT."""
    indexes = [
        (
            "ix_tiktok_viewers_nickname_trgm",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_tiktok_viewers_nickname_trgm "
            "ON tiktok_viewers USING gin (nickname gin_trgm_ops)",
        ),
        (
            "ix_tiktok_viewers_unique_id_trgm",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_tiktok_viewers_unique_id_trgm "
            "ON tiktok_viewers USING gin (unique_id gin_trgm_ops)",
        ),
    ]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        for name, ddl in indexes:
            try:
                c.execute(text(ddl))
                logger.info("Created (or already present): %s", name)
            except Exception:
                logger.exception("CREATE INDEX %s failed (continuing).", name)


def migrate() -> None:
    engine = create_database_engine()
    if engine.dialect.name != "postgresql":
        logger.info(
            "add_viewers_trgm_indexes: dialect=%s — skipping (Postgres only).",
            engine.dialect.name,
        )
        return

    if not _ensure_extension(engine):
        logger.warning(
            "Aborting: pg_trgm extension is required. Re-run after enabling it."
        )
        return
    _create_indexes(engine)
    logger.info("add_viewers_trgm_indexes: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

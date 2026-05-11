"""Create TikTok-bot tables (idempotent)."""

import logging
import sys
from pathlib import Path

# Make sure project root is importable when run standalone.
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text

from database.core.connection import create_database_engine
from database import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _drop_implicit_pg_sequences(engine) -> None:
    """SQLAlchemy auto-creates SERIAL/sequence on integer PKs in Postgres
    unless `autoincrement=False` is set. Earlier versions of these models
    didn't set that flag, so deployments that ran the migration before the
    fix have lingering nextval() defaults + sequences on natural-id PKs.
    Drop them defensively. No-op on SQLite and on already-fixed databases.
    """
    if engine.dialect.name != "postgresql":
        return

    targets = [
        ("tiktok_rooms", "room_id", "tiktok_rooms_room_id_seq"),
        ("tiktok_viewers", "user_id", "tiktok_viewers_user_id_seq"),
    ]
    with engine.begin() as conn:
        for table, column, seq in targets:
            exists = conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"),
                {"t": table},
            ).scalar()
            if not exists:
                continue
            conn.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP DEFAULT'))
            conn.execute(text(f'DROP SEQUENCE IF EXISTS "{seq}"'))
            logger.info("Dropped implicit sequence for %s.%s", table, column)


_PROFILE_COLUMNS_PG: list[tuple[str, str]] = [
    ("profile_user_id", "BIGINT"),
    ("sec_uid", "TEXT"),
    ("nickname", "TEXT"),
    ("avatar_url", "TEXT"),
    ("bio", "TEXT"),
    ("verified", "BOOLEAN"),
    ("private", "BOOLEAN"),
    ("follower_count", "INTEGER"),
    ("following_count", "INTEGER"),
    ("video_count", "INTEGER"),
    ("like_count", "BIGINT"),
    ("profile_refreshed_at", "TIMESTAMP"),
    ("profile_error", "TEXT"),
]


def _add_subscription_profile_columns(engine) -> None:
    """Add public-profile cache columns to tiktok_subscriptions when
    upgrading existing deployments. create_all only creates *new* tables,
    not new columns."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            for name, sql_type in _PROFILE_COLUMNS_PG:
                conn.execute(text(
                    f'ALTER TABLE "tiktok_subscriptions" '
                    f'ADD COLUMN IF NOT EXISTS {name} {sql_type}'
                ))
        logger.info("Ensured profile-cache columns on tiktok_subscriptions.")
    elif engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            existing = {
                r[1]
                for r in conn.execute(
                    text("PRAGMA table_info('tiktok_subscriptions')")
                ).all()
            }
            type_map = {"BIGINT": "INTEGER", "INTEGER": "INTEGER", "BOOLEAN": "INTEGER",
                        "TEXT": "TEXT", "TIMESTAMP": "TIMESTAMP"}
            for name, sql_type in _PROFILE_COLUMNS_PG:
                if name in existing:
                    continue
                conn.execute(text(
                    f"ALTER TABLE tiktok_subscriptions ADD COLUMN {name} {type_map.get(sql_type, sql_type)}"
                ))
            logger.info("Ensured profile-cache columns on tiktok_subscriptions (SQLite).")


def _add_match_settings_column(engine) -> None:
    """Add tiktok_matches.settings (jsonb) on databases where it doesn't
    exist yet. Stores BattleSetting fields for countdown UI."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(
                'ALTER TABLE "tiktok_matches" '
                'ADD COLUMN IF NOT EXISTS settings JSONB'
            ))
        logger.info("Ensured tiktok_matches.settings column.")
    elif engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info('tiktok_matches')")).all()]
            if "settings" not in cols:
                conn.execute(text("ALTER TABLE tiktok_matches ADD COLUMN settings TEXT"))
                logger.info("Added tiktok_matches.settings column (SQLite).")


def _add_match_id_column(engine) -> None:
    """Add tiktok_events.match_id (nullable FK) on databases where the
    column doesn't exist yet. create_all() doesn't ALTER existing tables.
    """
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(
                'ALTER TABLE "tiktok_events" '
                'ADD COLUMN IF NOT EXISTS match_id INTEGER '
                'REFERENCES tiktok_matches(id) ON DELETE SET NULL'
            ))
            conn.execute(text(
                'CREATE INDEX IF NOT EXISTS tiktok_events_match_idx '
                'ON tiktok_events (match_id)'
            ))
        logger.info("Ensured tiktok_events.match_id column + index.")
    elif engine.dialect.name == "sqlite":
        # SQLite ALTER ADD COLUMN is supported and tolerates "IF NOT EXISTS"
        # only since 3.35; use a guarded check.
        with engine.begin() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info('tiktok_events')")).all()]
            if "match_id" not in cols:
                conn.execute(text("ALTER TABLE tiktok_events ADD COLUMN match_id INTEGER"))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS tiktok_events_match_idx ON tiktok_events (match_id)"
                ))
                logger.info("Added tiktok_events.match_id column (SQLite).")


def migrate():
    logger.info("Creating TikTok-bot tables if they don't exist…")
    engine = create_database_engine()

    # Import all models so they register with Base.
    import database  # noqa: F401

    # create_all is idempotent — only creates tables that don't exist yet.
    Base.metadata.create_all(engine)

    # Repair: strip implicit PG sequences from natural-id PKs.
    _drop_implicit_pg_sequences(engine)

    # Add match_id column to tiktok_events on existing deployments.
    _add_match_id_column(engine)

    # Add settings column to tiktok_matches on existing deployments.
    _add_match_settings_column(engine)

    # Add profile-cache columns to tiktok_subscriptions.
    _add_subscription_profile_columns(engine)

    logger.info("TikTok-bot tables creation successful.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)

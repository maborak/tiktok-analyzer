"""Add `tiktok_subscriptions.owner_user_id` + `added_at` — first step
in the monetised-monitoring product pivot.

Idempotent. Safe to re-run.

Why:
  Until now every `tiktok_subscriptions` row was system-owned: admin
  added handles via `/admin/tiktok/subscriptions`, the listener pool
  monitored them globally, and the same view was admin-only. The new
  shape is per-user: any registered user with credits can add a
  monitor (costs 1 credit, refundable within 24h), and only the
  admin sees the cross-user list at `/admin/tiktok/all-subscriptions`.

  This migration introduces:
    - owner_user_id  → FK to `users.id`. Every read scoped to the
                       caller's id. Admin sees all via the new admin
                       route.
    - added_at       → TIMESTAMPTZ stamping when the sub was added.
                       Used by the 24h refund window on remove.

Backfill rule (decided 2026-05-18 in plan session):
  Every pre-existing sub belongs to admin user (wilmer@maborak.com,
  user_id=1 on this install). The admin then sees them in the user
  view AND the admin all-subs view — simplest migration that doesn't
  break the current workflow.

Indexes:
  - (owner_user_id, enabled): the common user-scoped read predicate.

Schema:
  ALTER TABLE tiktok_subscriptions
    ADD COLUMN owner_user_id INTEGER REFERENCES users(id),
    ADD COLUMN added_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
  -- Backfill admin
  UPDATE tiktok_subscriptions SET owner_user_id = <admin_id>
    WHERE owner_user_id IS NULL;
  -- Now-required
  ALTER TABLE tiktok_subscriptions ALTER COLUMN owner_user_id SET NOT NULL;

  CREATE INDEX ix_tiktok_subscriptions_owner_enabled
    ON tiktok_subscriptions (owner_user_id, enabled);
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

TABLE = "tiktok_subscriptions"


def _column_exists(engine, table: str, column: str) -> bool:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _index_exists(engine, table: str, name: str) -> bool:
    try:
        return any(ix["name"] == name for ix in inspect(engine).get_indexes(table))
    except Exception:
        return False


def _resolve_admin_user_id(c) -> int | None:
    """Resolve the admin user we'll backfill to. Strategy:
      1. JOIN users → roles WHERE role.name = 'admin' (RBAC source
         of truth — `users.role_id` FKs to the `roles` table).
      2. Fall back to lowest user_id (the first registered user,
         which on a fresh install is the admin who ran the seed).
    Returns None if no users exist at all — caller logs + skips backfill."""
    row = c.execute(text(
        "SELECT u.id FROM users u JOIN roles r ON u.role_id = r.id "
        "WHERE r.name = 'admin' ORDER BY u.id ASC LIMIT 1"
    )).first()
    if row:
        return int(row[0])
    row = c.execute(text("SELECT MIN(id) FROM users")).first()
    if row and row[0] is not None:
        return int(row[0])
    return None


def migrate() -> None:
    engine = create_database_engine()
    dialect = engine.dialect.name

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        # ── owner_user_id ────────────────────────────────────────────
        if _column_exists(engine, TABLE, "owner_user_id"):
            logger.info("%s.owner_user_id already exists — skipping ADD COLUMN.", TABLE)
        else:
            if dialect == "postgresql":
                c.execute(text(
                    f"ALTER TABLE {TABLE} "
                    "ADD COLUMN owner_user_id INTEGER REFERENCES users(id)"
                ))
            else:  # SQLite — no inline FK on ALTER; declarative anyway.
                c.execute(text(
                    f"ALTER TABLE {TABLE} ADD COLUMN owner_user_id INTEGER"
                ))
            logger.info("Added %s.owner_user_id column (nullable for backfill).", TABLE)

        # ── added_at ─────────────────────────────────────────────────
        if _column_exists(engine, TABLE, "added_at"):
            logger.info("%s.added_at already exists — skipping ADD COLUMN.", TABLE)
        else:
            if dialect == "postgresql":
                c.execute(text(
                    f"ALTER TABLE {TABLE} "
                    "ADD COLUMN added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                ))
            else:
                c.execute(text(
                    f"ALTER TABLE {TABLE} "
                    "ADD COLUMN added_at TEXT NOT NULL DEFAULT (datetime('now'))"
                ))
            logger.info("Added %s.added_at column.", TABLE)

        # ── backfill owner_user_id → admin ───────────────────────────
        # Only fires if there are still NULL rows. Idempotent — second
        # run picks up zero rows.
        admin_id = _resolve_admin_user_id(c)
        if admin_id is None:
            logger.warning(
                "No users in DB — skipping owner_user_id backfill. "
                "Re-run this migration AFTER an admin user exists, or set "
                "owner_user_id manually."
            )
        else:
            res = c.execute(text(
                f"UPDATE {TABLE} SET owner_user_id = :uid "
                "WHERE owner_user_id IS NULL"
            ), {"uid": admin_id})
            flipped = getattr(res, "rowcount", -1)
            if flipped > 0:
                logger.info(
                    "Backfilled owner_user_id=%d on %d existing row(s).",
                    admin_id, flipped,
                )
            else:
                logger.info("No rows needed owner_user_id backfill.")

        # ── promote owner_user_id to NOT NULL ────────────────────────
        # Only safe after the backfill above. On a no-users install we
        # leave it nullable so first-boot doesn't crash.
        if admin_id is not None:
            try:
                if dialect == "postgresql":
                    c.execute(text(
                        f"ALTER TABLE {TABLE} "
                        "ALTER COLUMN owner_user_id SET NOT NULL"
                    ))
                    logger.info("Promoted %s.owner_user_id to NOT NULL.", TABLE)
                # SQLite ignores SET NOT NULL ALTERs — model declarative
                # enforces it on new inserts.
            except Exception as e:
                # If already NOT NULL, Postgres raises — that's fine.
                if "is already" not in str(e).lower():
                    logger.warning(
                        "Could not promote owner_user_id to NOT NULL: %s", e,
                    )

        # ── index ────────────────────────────────────────────────────
        idx_name = "ix_tiktok_subscriptions_owner_enabled"
        if _index_exists(engine, TABLE, idx_name):
            logger.info("Index %s already exists.", idx_name)
        else:
            c.execute(text(
                f"CREATE INDEX {idx_name} ON {TABLE} (owner_user_id, enabled)"
            ))
            logger.info("Created index %s.", idx_name)

    logger.info("add_tiktok_subscription_ownership: done.")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)

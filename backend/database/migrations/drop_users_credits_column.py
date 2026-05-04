"""
Migration: Drop stale 'credits' column from users table.

The authoritative credit balance is computed from credit_ledgers:
  SUM(amount) FROM credit_ledgers WHERE user_id = ? AND expires_at > NOW()

The users.credits column was never updated during normal operation and
has been stale since the credit ledger system was introduced.
"""

import os
import sys
from sqlalchemy import text, inspect

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def migrate():
    from utils.database.database_session import get_write_engine

    engine = get_write_engine()
    print("Running migration to drop users.credits column...")

    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('users')]

    if 'credits' not in columns:
        print("users.credits column does not exist, skipping.")
        return

    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "sqlite":
            # SQLite doesn't support DROP COLUMN before 3.35.0
            # For older versions, we'd need to recreate the table.
            # SQLite 3.35.0+ supports ALTER TABLE DROP COLUMN.
            try:
                conn.execute(text("ALTER TABLE users DROP COLUMN credits"))
            except Exception as e:
                print(f"SQLite DROP COLUMN not supported on this version: {e}")
                print("Column will be ignored by the application. No action needed.")
                return
        else:
            conn.execute(text("ALTER TABLE users DROP COLUMN credits"))

    print("Migration completed: users.credits column dropped.")


if __name__ == "__main__":
    migrate()

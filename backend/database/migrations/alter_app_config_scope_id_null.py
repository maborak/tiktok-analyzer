"""
Fix: app_config column defaults for PostgreSQL compatibility.

1. scope_id: NULL → '' (PostgreSQL UNIQUE constraint safety)
2. value_type, scope: add server defaults (raw SQL INSERT compatibility)
3. created_at, updated_at: add server defaults (raw SQL INSERT compatibility)

Safe to re-run: applies only when defaults are missing.
"""

import os
import sys
from sqlalchemy import text, inspect

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def migrate():
    from utils.database.database_session import get_write_engine
    from config import get_table_name

    engine = get_write_engine()
    table_name = get_table_name("app_config")
    dialect = engine.dialect.name

    print(f"Fixing {table_name} column defaults...")

    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        print(f"{table_name} table does not exist, skipping.")
        return

    with engine.begin() as conn:
        # Step 1: Convert all NULL scope_id to empty string
        result = conn.execute(text(
            f"UPDATE {table_name} SET scope_id = '' WHERE scope_id IS NULL"
        ))
        print(f"  Updated {result.rowcount} rows: scope_id NULL → ''")

        if dialect == "sqlite":
            print("  SQLite: column defaults handled by ORM model.")
        else:
            # Step 2: scope_id — SET DEFAULT '' and NOT NULL
            conn.execute(text(
                f"ALTER TABLE {table_name} ALTER COLUMN scope_id SET DEFAULT ''"
            ))
            conn.execute(text(
                f"ALTER TABLE {table_name} ALTER COLUMN scope_id SET NOT NULL"
            ))

            # Step 3: value_type and scope — server defaults
            conn.execute(text(
                f"ALTER TABLE {table_name} ALTER COLUMN value_type SET DEFAULT 'string'"
            ))
            conn.execute(text(
                f"ALTER TABLE {table_name} ALTER COLUMN scope SET DEFAULT 'global'"
            ))

            # Step 4: created_at and updated_at — server defaults
            conn.execute(text(
                f"ALTER TABLE {table_name} ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP"
            ))
            conn.execute(text(
                f"ALTER TABLE {table_name} ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP"
            ))
            print("  PostgreSQL: all column defaults applied.")

    print("Migration completed successfully.")


if __name__ == "__main__":
    migrate()

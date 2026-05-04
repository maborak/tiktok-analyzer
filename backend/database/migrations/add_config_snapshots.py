import os
import sys
from sqlalchemy import text, inspect

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def migrate():
    from utils.database.database_session import get_write_engine
    from config import get_table_name

    engine = get_write_engine()
    table_name = get_table_name("config_snapshots")
    print(f"Running migration to add {table_name} table...")

    inspector = inspect(engine)
    if table_name in inspector.get_table_names():
        print(f"{table_name} table already exists, skipping.")
        return

    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL,
                description VARCHAR(1000),
                trigger VARCHAR(32) NOT NULL DEFAULT 'manual',
                payload TEXT NOT NULL,
                key_count INTEGER NOT NULL DEFAULT 0,
                parent_snapshot_id INTEGER,
                created_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            """))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description VARCHAR(1000),
                trigger VARCHAR(32) NOT NULL DEFAULT 'manual',
                payload TEXT NOT NULL,
                key_count INTEGER NOT NULL DEFAULT 0,
                parent_snapshot_id INTEGER,
                created_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            """))

        conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_config_snapshots_created_at ON {table_name}(created_at);"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_config_snapshots_trigger ON {table_name}(trigger);"))

    print("Migration completed successfully.")


if __name__ == "__main__":
    migrate()

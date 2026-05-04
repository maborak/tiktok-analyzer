import os
import sys
from sqlalchemy import text, inspect

# Add the project root to the path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def migrate():
    from utils.database.database_session import get_write_engine
    from config import get_table_name

    engine = get_write_engine()
    table_name = get_table_name("event_configs")
    print(f"Running migration to add {table_name} table...")

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if table_name in existing_tables:
        print(f"{table_name} table already exists, skipping.")
        return

    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type VARCHAR(100) NOT NULL,
                handler_name VARCHAR(100) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(event_type, handler_name)
            );
            """))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
                event_type VARCHAR(100) NOT NULL,
                handler_name VARCHAR(100) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(event_type, handler_name)
            );
            """))

        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_event_type ON {table_name}(event_type);"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_handler_name ON {table_name}(handler_name);"))

    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()

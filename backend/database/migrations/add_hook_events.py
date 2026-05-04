import os
import sys
from sqlalchemy import text, inspect

# Add the project root to the path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def migrate():
    from utils.database.database_session import get_write_engine
    from config import get_table_name

    engine = get_write_engine()
    table_name = get_table_name("hook_events")
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
                source VARCHAR(100),
                data_json TEXT,
                metadata_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            """))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
                event_type VARCHAR(100) NOT NULL,
                source VARCHAR(100),
                data_json TEXT,
                metadata_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            """))

        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_event_type ON {table_name}(event_type);"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_source ON {table_name}(source);"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_created_at ON {table_name}(created_at);"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_type_created ON {table_name}(event_type, created_at);"))

    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()

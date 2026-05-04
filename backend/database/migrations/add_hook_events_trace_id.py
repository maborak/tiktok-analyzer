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
    print(f"Running migration to add trace_id column to {table_name}...")

    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns(table_name)]

        if "trace_id" not in columns:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN trace_id VARCHAR(36);"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_trace_id ON {table_name}(trace_id);"))
            print("Added trace_id column and index.")
        else:
            print("trace_id column already exists, skipping.")

    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()

import os
import sys
from sqlalchemy import text, inspect

# Add the project root to the path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def migrate():
    from utils.database.database_session import get_write_engine

    engine = get_write_engine()
    table_name = "oauth_accounts"
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
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider VARCHAR(50) NOT NULL,
                provider_user_id VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                name VARCHAR(255),
                avatar_url VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(provider, provider_user_id)
            );
            """))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider VARCHAR(50) NOT NULL,
                provider_user_id VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                name VARCHAR(255),
                avatar_url VARCHAR(500),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(provider, provider_user_id)
            );
            """))

        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_oauth_accounts_user_id ON {table_name}(user_id);"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_oauth_provider_email ON {table_name}(provider, email);"))

    print("Migration completed successfully.")


if __name__ == "__main__":
    migrate()

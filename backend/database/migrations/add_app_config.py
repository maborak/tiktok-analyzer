import os
import sys
from sqlalchemy import text, inspect

# Add the project root to the path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def migrate():
    from utils.database.database_session import get_write_engine
    from config import get_table_name

    engine = get_write_engine()
    table_name = get_table_name("app_config")
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
                namespace VARCHAR(100) NOT NULL,
                key VARCHAR(100) NOT NULL,
                value VARCHAR(500) NOT NULL,
                value_type VARCHAR(20) NOT NULL DEFAULT 'string',
                scope VARCHAR(20) NOT NULL DEFAULT 'global',
                scope_id VARCHAR(50) NOT NULL DEFAULT '',
                updated_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(namespace, key, scope, scope_id)
            );
            """))
        else:
            conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
                namespace VARCHAR(100) NOT NULL,
                key VARCHAR(100) NOT NULL,
                value VARCHAR(500) NOT NULL,
                value_type VARCHAR(20) NOT NULL DEFAULT 'string',
                scope VARCHAR(20) NOT NULL DEFAULT 'global',
                scope_id VARCHAR(50) NOT NULL DEFAULT '',
                updated_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(namespace, key, scope, scope_id)
            );
            """))

        conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_app_config_namespace ON {table_name}(namespace);"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_app_config_scope ON {table_name}(scope, scope_id);"))

        # Seed queue namespace with production defaults
        conn.execute(text(f"""
        INSERT INTO {table_name} (namespace, key, value, value_type, scope, scope_id, updated_by) VALUES
            ('queue', 'BATCH_COOLDOWN', '3600', 'int', 'global', '', 'system_seed'),
            ('queue', 'ASIN_COOLDOWN', '0', 'int', 'global', '', 'system_seed'),
            ('queue', 'COUNTRY_COOLDOWN', '0', 'int', 'global', '', 'system_seed'),
            ('queue', 'COUNTRY_CONCURRENCY', '0', 'int', 'global', '', 'system_seed'),
            ('queue', 'ASIN_CONCURRENCY', '1', 'int', 'global', '', 'system_seed'),
            ('queue', 'QUEUE_SIZE', '1', 'int', 'global', '', 'system_seed'),
            ('queue', 'PAUSED', 'false', 'boolean', 'global', '', 'system_seed'),
            ('queue', 'SCREENSHOT_TRIGGER', 'on-change', 'string', 'global', '', 'system_seed'),
            ('queue', 'SCREENSHOT_SERVICE_URL', '', 'string', 'global', '', 'system_seed'),
            ('queue', 'HTML_MODE', 'cleaned', 'string', 'global', '', 'system_seed');
        """))

    print("Migration completed successfully.")


if __name__ == "__main__":
    migrate()

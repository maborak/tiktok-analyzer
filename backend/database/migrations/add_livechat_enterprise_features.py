"""
Migration script to add enterprise LiveChat features (context, CSAT, SLA, Macros)
"""

import sys
import os
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from database.core.connection import create_database_engine
from sqlalchemy import inspect, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate(engine):
    inspector = inspect(engine)
    
    with engine.connect() as conn:
        # 1. Add columns to livechat_sessions
        columns_sessions = [col['name'] for col in inspector.get_columns('livechat_sessions')]
        
        session_columns_to_add = [
            ("initial_context", "JSONB", "NULL"),
            ("initial_message", "TEXT", "NULL"),
            ("typing_status", "JSONB", "NULL"),
            ("first_response_at", "TIMESTAMP", "NULL"),
            ("resolution_time_seconds", "INTEGER", "NULL"),
            ("csat_score", "INTEGER", "NULL"),
            ("csat_comment", "TEXT", "NULL"),
            ("is_proactive", "BOOLEAN", "NOT NULL DEFAULT FALSE")
        ]
        
        for col_name, col_type, constraints in session_columns_to_add:
            if col_name not in columns_sessions:
                logger.info(f"➕ Adding {col_name} column to livechat_sessions table...")
                conn.execute(text(f"ALTER TABLE livechat_sessions ADD COLUMN {col_name} {col_type} {constraints}"))
                logger.info(f"✅ {col_name} column added.")
        
        # 2. Add columns to livechat_messages
        columns_messages = [col['name'] for col in inspector.get_columns('livechat_messages')]
        
        message_columns_to_add = [
            ("context", "JSONB", "NULL"),
            ("read_at", "TIMESTAMP", "NULL")
        ]
        
        for col_name, col_type, constraints in message_columns_to_add:
            if col_name not in columns_messages:
                logger.info(f"➕ Adding {col_name} column to livechat_messages table...")
                conn.execute(text(f"ALTER TABLE livechat_messages ADD COLUMN {col_name} {col_type} {constraints}"))
                logger.info(f"✅ {col_name} column added.")
        
        conn.commit()

if __name__ == "__main__":
    try:
        engine = create_database_engine()
        migrate(engine)
        logger.info("✅ Migration completed successfully")
    except Exception as e:
        logger.error(f"❌ Migration error: {e}", exc_info=True)
        sys.exit(1)

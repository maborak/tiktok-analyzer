"""
Migration script to add livechat_attachments table and is_authenticated_user column to livechat_sessions
"""

import sys
import os
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from database.core.connection import create_database_engine
from database.tickets.models import LiveChatAttachmentModel, LiveChatSessionModel
from sqlalchemy import inspect, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate(engine):
    inspector = inspect(engine)
    
    with engine.connect() as conn:
        # 1. Add column to livechat_sessions if it doesn't exist
        columns = [col['name'] for col in inspector.get_columns('livechat_sessions')]
        if 'is_authenticated_user' not in columns:
            logger.info("➕ Adding is_authenticated_user column to livechat_sessions table...")
            conn.execute(text("ALTER TABLE livechat_sessions ADD COLUMN is_authenticated_user BOOLEAN NOT NULL DEFAULT FALSE"))
            conn.commit()
            logger.info("✅ Column added successfully.")
        else:
            logger.info("✅ is_authenticated_user column already exists.")

        # 2. Add livechat_attachments table
        table_name = LiveChatAttachmentModel.__tablename__
        tables = inspector.get_table_names()
        
        if table_name not in tables:
            logger.info(f"➕ Adding {table_name} table...")
            LiveChatAttachmentModel.__table__.create(engine, checkfirst=True)
            logger.info(f"✅ {table_name} table created successfully.")
        else:
            logger.info(f"✅ {table_name} table already exists.")

if __name__ == "__main__":
    try:
        engine = create_database_engine()
        migrate(engine)
        logger.info("✅ Migration completed successfully")
    except Exception as e:
        logger.error(f"❌ Migration error: {e}", exc_info=True)
        sys.exit(1)

"""
Add credits column to users table and set default value to 10.
"""
import sys
import os
import logging
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Database connection
if os.getenv("PHOVEU_BACKEND_DATABASE_URL"):
    DATABASE_URL = os.getenv("PHOVEU_BACKEND_DATABASE_URL")
elif os.getenv("DATABASE_URL"):
    DATABASE_URL = os.getenv("DATABASE_URL")
else:
    DB_USER = os.getenv("POSTGRES_USER", "postgres")
    DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
    DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
    DB_PORT = os.getenv("POSTGRES_PORT", "5432")
    DB_NAME = os.getenv("POSTGRES_DB", "maborak")
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def migrate():
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('users')]
        
        if 'credits' not in columns:
            logger.info("Adding 'credits' column to 'users' table...")
            conn.execute(text("ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 10 NOT NULL;"))
            conn.commit()
            logger.info("Migration successful: 'credits' column added.")
        else:
            logger.info("'credits' column already exists on 'users' table.")

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)

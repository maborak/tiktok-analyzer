"""
Create billing and ledger tables.
"""
import sys
import os
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from database.core.connection import create_database_engine
from database import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    logger.info("Creating billing tables if they don't exist...")
    engine = create_database_engine()
    
    # Import all models to ensure they are registered with Base
    import database
    
    Base.metadata.create_all(engine)
    logger.info("Billing tables creation successful.")

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)

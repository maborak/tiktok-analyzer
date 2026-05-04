"""
Migration script to add AWAITING_PAYMENT to the paymentstatus ENUM.
"""
import os
import sys

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

from sqlalchemy import text
from utils.database.database_session import get_write_engine

def migrate():
    """Add AWAITING_PAYMENT to paymentstatus enum if it doesn't exist."""
    print("Initializing write engine...")
    engine = get_write_engine()
    
    try:
        with engine.connect() as conn:
            # Check if AWAITING_PAYMENT already exists in the enum
            result = conn.execute(text("""
                SELECT 1 
                FROM pg_enum 
                WHERE enumlabel = 'AWAITING_PAYMENT' 
                AND enumtypid = (
                    SELECT oid FROM pg_type WHERE typname = 'paymentstatus'
                )
            """))
            exists = result.fetchone()

            if not exists:
                print("Adding AWAITING_PAYMENT to paymentstatus ENUM...")
                # In postgres, ALTER TYPE ADD VALUE cannot run inside a transaction block
                # SQLAlchemy runs in transactions by default, so we use execution_options(isolation_level="AUTOCOMMIT")
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as autocommit_conn:
                    autocommit_conn.execute(text("ALTER TYPE paymentstatus ADD VALUE 'AWAITING_PAYMENT' BEFORE 'PENDING'"))
                print("Successfully added AWAITING_PAYMENT to paymentstatus.")
            else:
                print("AWAITING_PAYMENT already exists in paymentstatus ENUM. Skipping.")

    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(project_root, '.env'))
    migrate()

"""
Migration: add note column to credit_ledgers

Adds a nullable VARCHAR(500) note column to store human-readable context
(e.g. "B0F6NYKCFR/US") for track_product deductions and renewals.

Run once against the target database:
    conda activate amazon && python database/migrations/add_credit_ledger_note.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from utils.database.database_session import get_write_engine
engine = get_write_engine()


def run():
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE credit_ledgers ADD COLUMN IF NOT EXISTS note VARCHAR(500) NULL"
            ))
            conn.commit()
            print("✅ Migration complete: credit_ledgers.note added")
        except Exception as e:
            # SQLite doesn't support IF NOT EXISTS on ADD COLUMN
            try:
                conn.execute(text(
                    "ALTER TABLE credit_ledgers ADD COLUMN note VARCHAR(500) NULL"
                ))
                conn.commit()
                print("✅ Migration complete: credit_ledgers.note added")
            except Exception as e2:
                if "duplicate column" in str(e2).lower() or "already exists" in str(e2).lower():
                    print("ℹ️  Column already exists, skipping.")
                else:
                    print(f"❌ Migration failed: {e2}")
                    raise


if __name__ == "__main__":
    run()

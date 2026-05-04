#!/usr/bin/env python3
"""
Migration script to drop the deprecated line_item_description column from invoices table.
This column has been replaced by the line_items JSON column.
"""

import os
import sys
import psycopg2
from psycopg2 import sql

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import CONFIG

def get_db_connection():
    """Get database connection using config"""
    db_url = CONFIG.get("DATABASE_URL") or os.getenv("PHOVEU_BACKEND_DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not configured")
    return psycopg2.connect(db_url)

def migrate():
    """Drop line_item_description column from invoices table"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'invoices' AND column_name = 'line_item_description'
    """)
    
    if not cursor.fetchone():
        print("  ⚠️  Column 'line_item_description' does not exist, nothing to drop")
        cursor.close()
        conn.close()
        return False
    
    # Drop the column
    cursor.execute("""
        ALTER TABLE invoices DROP COLUMN line_item_description
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print("  ✅ Dropped column 'line_item_description'")
    return True

if __name__ == "__main__":
    print("🔧 Drop Deprecated Column Migration")
    print("=" * 50)
    
    try:
        migrated = migrate()
        if migrated:
            print("\n✅ Migration completed successfully!")
            print("\n📝 The 'line_item_description' column has been removed.")
            print("   The 'line_items' JSON column is now used instead.")
        else:
            print("\n✅ Column already removed, no migration needed.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

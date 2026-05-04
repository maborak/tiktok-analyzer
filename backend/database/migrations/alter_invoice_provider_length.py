#!/usr/bin/env python3
"""
Migration: Update Invoice Provider Column Length

This migration updates the invoices.provider column from VARCHAR(10) to VARCHAR(20)
to accommodate longer provider names like 'BANK_TRANSFER' (13 chars).
"""

import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, '.env'))

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config import settings

def get_db_connection():
    """Get database connection using settings"""
    db_url = settings("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set in environment")
    return psycopg2.connect(db_url)

def migrate():
    """Update invoices.provider column length"""
    conn = get_db_connection()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    
    print("🔧 Invoice Provider Column Length Migration")
    print("=" * 50)
    
    try:
        # Check current column type
        print("  📝 Checking current column type...")
        cur.execute("""
            SELECT data_type, character_maximum_length 
            FROM information_schema.columns 
            WHERE table_name = 'invoices' AND column_name = 'provider';
        """)
        result = cur.fetchone()
        if result:
            data_type, max_length = result
            print(f"  Current: {data_type}({max_length})")
            
            if max_length and max_length >= 20:
                print("  ✅ Column already has sufficient length")
                return
        
        # Update column length
        print("  📝 Updating invoices.provider to VARCHAR(20)...")
        cur.execute("""
            ALTER TABLE invoices 
            ALTER COLUMN provider TYPE VARCHAR(20);
        """)
        print("  ✅ Updated invoices.provider to VARCHAR(20)")
        
        # Also update payment_transactions.provider if needed
        print("  📝 Checking payment_transactions.provider...")
        cur.execute("""
            SELECT data_type, character_maximum_length 
            FROM information_schema.columns 
            WHERE table_name = 'payment_transactions' AND column_name = 'provider';
        """)
        result = cur.fetchone()
        if result:
            data_type, max_length = result
            if max_length and max_length < 20:
                print("  📝 Updating payment_transactions.provider to VARCHAR(20)...")
                cur.execute("""
                    ALTER TABLE payment_transactions 
                    ALTER COLUMN provider TYPE VARCHAR(20);
                """)
                print("  ✅ Updated payment_transactions.provider to VARCHAR(20)")
            else:
                print("  ✅ payment_transactions.provider already has sufficient length")
        
        print("\n📊 Migration Summary:")
        print("   - Updated invoices.provider to VARCHAR(20)")
        print("   - Updated payment_transactions.provider to VARCHAR(20) (if needed)")
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

#!/usr/bin/env python3
"""
Migration script to add enterprise invoice fields to the invoices table.
Run this to upgrade existing database schema with new columns.
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
    """Add enterprise invoice fields to invoices table"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Columns to add with their types
    new_columns = [
        ("provider", "VARCHAR(10)"),
        ("provider_transaction_id", "VARCHAR(255)"),
        ("subtotal_amount", "FLOAT"),
        ("tax_amount", "FLOAT DEFAULT 0.0"),
        ("billing_address_line1", "VARCHAR(255)"),
        ("billing_address_line2", "VARCHAR(255)"),
        ("billing_city", "VARCHAR(100)"),
        ("billing_state", "VARCHAR(100)"),
        ("billing_postal_code", "VARCHAR(20)"),
        ("billing_country", "VARCHAR(2)"),
        ("line_items", "TEXT"),
        ("tax_rate", "FLOAT"),
        ("tax_id", "VARCHAR(50)"),
        ("status", "VARCHAR(20) DEFAULT 'paid'"),
        ("invoice_date", "TIMESTAMP"),
        ("due_date", "TIMESTAMP"),
        ("paid_at", "TIMESTAMP"),
        ("notes", "VARCHAR(1000)"),
    ]
    
    added_columns = []
    skipped_columns = []
    
    for column_name, column_type in new_columns:
        # Check if column already exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'invoices' AND column_name = %s
        """, (column_name,))
        
        if cursor.fetchone():
            skipped_columns.append(column_name)
            print(f"  ⚠️  Column '{column_name}' already exists, skipping")
            continue
        
        # Add the column
        alter_sql = sql.SQL("ALTER TABLE invoices ADD COLUMN {} {}").format(
            sql.Identifier(column_name),
            sql.SQL(column_type)
        )
        cursor.execute(alter_sql)
        added_columns.append(column_name)
        print(f"  ✅ Added column '{column_name}' ({column_type})")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print(f"\n📊 Migration Summary:")
    print(f"   Added: {len(added_columns)} columns")
    print(f"   Skipped: {len(skipped_columns)} columns (already existed)")
    
    if added_columns:
        print(f"\n   New columns: {', '.join(added_columns)}")
    
    return len(added_columns) > 0

if __name__ == "__main__":
    print("🔧 Enterprise Invoice Migration")
    print("=" * 50)
    
    try:
        migrated = migrate()
        if migrated:
            print("\n✅ Migration completed successfully!")
            print("\n📝 Note: Existing invoices will have NULL values for new fields.")
            print("   New invoices will populate all fields automatically.")
        else:
            print("\n✅ All columns already exist, no migration needed.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)

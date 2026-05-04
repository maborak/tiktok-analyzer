#!/usr/bin/env python3
"""
Migration: Update Payment Gateway Configuration - Replace OTHER with BITCOIN and BANK_TRANSFER

This migration:
1. Adds BITCOIN and BANK_TRANSFER to paymentprovider enum
2. Removes OTHER from enum (if exists)
3. Updates default configurations
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
    """Update payment gateway configuration"""
    conn = get_db_connection()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    
    print("🔧 Payment Gateway Configuration Update (v2)")
    print("=" * 50)
    
    try:
        # Add BITCOIN to enum if not exists
        print("  📝 Checking BITCOIN in paymentprovider enum...")
        cur.execute("""
            SELECT enumlabel FROM pg_enum 
            WHERE enumtypid = 'paymentprovider'::regtype 
            AND enumlabel = 'BITCOIN';
        """)
        if not cur.fetchone():
            cur.execute("ALTER TYPE paymentprovider ADD VALUE 'BITCOIN';")
            print("  ✅ Added 'BITCOIN' to paymentprovider enum")
        else:
            print("  ✅ 'BITCOIN' already exists in enum")
        
        # Add BANK_TRANSFER to enum if not exists
        print("  📝 Checking BANK_TRANSFER in paymentprovider enum...")
        cur.execute("""
            SELECT enumlabel FROM pg_enum 
            WHERE enumtypid = 'paymentprovider'::regtype 
            AND enumlabel = 'BANK_TRANSFER';
        """)
        if not cur.fetchone():
            cur.execute("ALTER TYPE paymentprovider ADD VALUE 'BANK_TRANSFER';")
            print("  ✅ Added 'BANK_TRANSFER' to paymentprovider enum")
        else:
            print("  ✅ 'BANK_TRANSFER' already exists in enum")
        
        # Remove OTHER config if exists
        print("  📝 Removing OTHER configuration...")
        cur.execute("""
            DELETE FROM payment_gateway_configs WHERE provider = 'OTHER';
        """)
        if cur.rowcount > 0:
            print("  ✅ Removed OTHER configuration")
        else:
            print("  ⚠️  No OTHER configuration to remove")
        
        # Insert BITCOIN default config
        print("  📝 Adding BITCOIN configuration...")
        cur.execute("""
            INSERT INTO payment_gateway_configs 
            (provider, is_enabled, display_name, mode, config_json, created_at, updated_at)
            VALUES ('BITCOIN', %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (provider) DO NOTHING;
        """, (False, 'Bitcoin', 'live', '{"description": "Pay with Bitcoin (BTC)", "instructions": "Send BTC to the wallet address and contact support with your transaction ID"}'))
        if cur.rowcount > 0:
            print("  ✅ Inserted default config for BITCOIN")
        else:
            print("  ⚠️  BITCOIN config already exists")
        
        # Insert BANK_TRANSFER default config
        print("  📝 Adding BANK_TRANSFER configuration...")
        cur.execute("""
            INSERT INTO payment_gateway_configs 
            (provider, is_enabled, display_name, mode, config_json, created_at, updated_at)
            VALUES ('BANK_TRANSFER', %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (provider) DO NOTHING;
        """, (False, 'Bank Transfer', 'live', '{"description": "Pay via bank transfer", "instructions": "Transfer the amount to our bank account and upload the receipt"}'))
        if cur.rowcount > 0:
            print("  ✅ Inserted default config for BANK_TRANSFER")
        else:
            print("  ⚠️  BANK_TRANSFER config already exists")
        
        print("\n📊 Migration Summary:")
        print("   - Added BITCOIN to paymentprovider enum")
        print("   - Added BANK_TRANSFER to paymentprovider enum")
        print("   - Removed OTHER configuration")
        print("   - Added BITCOIN default config")
        print("   - Added BANK_TRANSFER default config")
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

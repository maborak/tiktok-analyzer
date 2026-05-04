#!/usr/bin/env python3
"""
Migration: Create Payment Gateway Configuration Table

This migration creates the payment_gateway_configs table to store
payment gateway settings (PayPal, Stripe, Other) including:
- Enable/disable status
- API keys and secrets
- Webhook secrets
- Mode (sandbox/live)
- Additional JSON configuration
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
    """Create payment_gateway_configs table"""
    conn = get_db_connection()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    
    print("🔧 Payment Gateway Configuration Migration")
    print("=" * 50)
    
    try:
        # First, ensure OTHER is in the paymentprovider enum
        print("  📝 Checking paymentprovider enum...")
        cur.execute("""
            SELECT enumlabel FROM pg_enum 
            WHERE enumtypid = 'paymentprovider'::regtype 
            AND enumlabel = 'OTHER';
        """)
        other_exists = cur.fetchone()
        
        if not other_exists:
            cur.execute("ALTER TYPE paymentprovider ADD VALUE 'OTHER';")
            conn.commit()
            print("  ✅ Added 'OTHER' to paymentprovider enum")
        else:
            print("  ✅ 'OTHER' already exists in enum")
        
        # Check if table already exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'payment_gateway_configs'
            );
        """)
        table_exists = cur.fetchone()[0]
        
        if table_exists:
            print("  ⚠️  Table 'payment_gateway_configs' already exists")
            print("  📝 Checking for missing default configurations...")
        else:
            # Create the payment_gateway_configs table
            cur.execute("""
                CREATE TABLE payment_gateway_configs (
                    id SERIAL PRIMARY KEY,
                    provider VARCHAR(20) NOT NULL UNIQUE,
                    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    display_name VARCHAR(100),
                    api_key VARCHAR(500),
                    api_secret VARCHAR(500),
                    webhook_secret VARCHAR(500),
                    mode VARCHAR(20) NOT NULL DEFAULT 'sandbox',
                    config_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            print("  ✅ Created table 'payment_gateway_configs'")
            
            # Create index on provider for faster lookups
            cur.execute("""
                CREATE INDEX idx_payment_gateway_configs_provider 
                ON payment_gateway_configs(provider);
            """)
            print("  ✅ Created index on 'provider' column")
            
            # Create index on is_enabled for filtering active gateways
            cur.execute("""
                CREATE INDEX idx_payment_gateway_configs_is_enabled 
                ON payment_gateway_configs(is_enabled);
            """)
            print("  ✅ Created index on 'is_enabled' column")
            
            # Create trigger to auto-update updated_at timestamp
            cur.execute("""
                CREATE OR REPLACE FUNCTION update_payment_gateway_configs_timestamp()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            cur.execute("""
                DROP TRIGGER IF EXISTS update_payment_gateway_configs_timestamp 
                ON payment_gateway_configs;
                
                CREATE TRIGGER update_payment_gateway_configs_timestamp
                BEFORE UPDATE ON payment_gateway_configs
                FOR EACH ROW
                EXECUTE FUNCTION update_payment_gateway_configs_timestamp();
            """)
            print("  ✅ Created auto-update trigger for 'updated_at'")
        
        # Insert default configurations for each provider (disabled by default)
        # This runs regardless of whether table was just created or already existed
        default_providers = [
            ('PAYPAL', 'PayPal', 'sandbox'),
            ('STRIPE', 'Stripe', 'sandbox'),
            ('OTHER', 'Other', 'sandbox')
        ]
        
        inserted_count = 0
        for provider, display_name, mode in default_providers:
            cur.execute("""
                INSERT INTO payment_gateway_configs 
                (provider, is_enabled, display_name, mode, config_json, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (provider) DO NOTHING;
            """, (provider, False, display_name, mode, '{}'))
            if cur.rowcount > 0:
                print(f"  ✅ Inserted default config for {provider}")
                inserted_count += 1
            else:
                print(f"  ⚠️  Config for {provider} already exists, skipped")
        
        print("\n📊 Migration Summary:")
        if table_exists:
            print("   - Table already existed: payment_gateway_configs")
        else:
            print("   - Created table: payment_gateway_configs")
            print("   - Added indexes: provider, is_enabled")
            print("   - Created auto-update timestamp trigger")
        print(f"   - Default configs inserted: {inserted_count}/3 (PAYPAL, STRIPE, OTHER)")
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

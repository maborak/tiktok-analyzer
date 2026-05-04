"""
Database Operations

Centralized database management operations including clearing, seeding, and initialization.
"""

from typing import Optional, Dict, Any


def clear_database() -> bool:
    """Clear all data from the database while keeping schema intact"""
    try:
        from adapters.database_persistence import DatabaseDataPersistenceAdapter
        db_adapter = DatabaseDataPersistenceAdapter(auto_init=True)
        deleted_counts = db_adapter.purge_all_data()

        print("🧹 Cleared data from all tables")
        total_deleted = sum(deleted_counts.values()) if isinstance(deleted_counts, dict) else 0
        print(f"  • Total records deleted: {total_deleted}")
        print("\n✅ Database clear completed successfully!")
        return True

    except Exception as e:
        print(f"\n❌ Error during database clear: {e}")
        return False


def init_database() -> bool:
    """Initialize the database by creating all tables and seeding default data"""
    try:
        # Import all models first to ensure SQLAlchemy knows about all relationships
        # This is crucial for proper dependency resolution
        from database import (
            Base,
            User, UserSession, ApiKey, PasswordReset,
        )
        from database.core.connection import create_database_engine
        from sqlalchemy import MetaData
        
        # Create engine
        engine = create_database_engine()
        
        # First, reflect the database to get all existing tables (including ones not in ORM)
        # This ensures we know about all tables and their dependencies
        reflected_metadata = MetaData()
        reflected_metadata.reflect(bind=engine)
        
        # Drop all reflected tables first (existing tables in database)
        # This handles tables that might not be in our ORM models
        reflected_metadata.drop_all(bind=engine, checkfirst=True)
        
        # Drop all tables defined in Base.metadata (our ORM models)
        # SQLAlchemy automatically handles dependency order based on foreign keys
        Base.metadata.drop_all(bind=engine, checkfirst=True)
        
        print("🗑️  Dropped all database tables")
        
        # Ensure pg_trgm extension exists for GIN trgm indexes
        # Only for PostgreSQL
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
                conn.commit()
            print("🧱 Enabled 'pg_trgm' extension")
            
        # Recreate all tables using ORM
        Base.metadata.create_all(bind=engine)
        print("🏗️  Created fresh database tables")
        
        # Seed default data using the adapter (includes countries, currencies, and states)
        from adapters.database_persistence import DatabaseDataPersistenceAdapter
        db_adapter = DatabaseDataPersistenceAdapter(auto_init=True)
        success = db_adapter.seed_database()
        
        if success:
            print("🌱 Auto-seeded default data (RBAC and defaults)")
            print("\n✅ Database initialization completed successfully!")
            return True
        else:
            print("❌ Failed to seed database")
            return False
        
    except Exception as e:
        print(f"\n❌ Error during database initialization: {e}")
        import traceback
        traceback.print_exc()
        return False


def seed_database() -> bool:
    """Seed the database with default data"""
    try:
        from adapters.database_persistence import DatabaseDataPersistenceAdapter
        db_adapter = DatabaseDataPersistenceAdapter(auto_init=True)
        success = db_adapter.seed_database()
        
        if success:
            print("\n✅ Database seeding completed successfully!")
            return True
        else:
            print("\n❌ Database seeding failed!")
            return False
            
    except Exception as e:
        print(f"\n❌ Error during database seeding: {e}")
        return False


def reset_database() -> bool:
    """Reset the entire database by dropping all tables and recreating them"""
    try:
        from adapters.database_persistence import DatabaseDataPersistenceAdapter
        db_adapter = DatabaseDataPersistenceAdapter(auto_init=True)
        success = db_adapter.reset_database()
        
        if success:
            print("\n✅ Database reset completed successfully!")
            return True
        else:
            print("\n❌ Database reset failed!")
            return False
        
    except Exception as e:
        print(f"\n❌ Error during database reset: {e}")
        return False


 
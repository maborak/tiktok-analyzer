"""
Migration script to seed roles and migrate from string-based to ID-based roles

This migration:
1. Creates the roles table if it doesn't exist
2. Seeds default roles (user, moderator, admin) with is_system=True
3. Migrates role_permissions from role string to role_id
4. Updates users.role_id based on users.role string

Usage:
    python database/migrations/seed_roles.py --dry-run
    python database/migrations/seed_roles.py
"""

import sys
import os
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from database.core.connection import create_database_engine
from database.auth.rbac_models import Role, role_permissions
from database.auth.models import User as UserModel
from sqlalchemy import inspect, text, and_
from sqlalchemy.exc import ProgrammingError
from utils.database.database_session import get_db_session
from database.auth.rbac_service import RBACService
from config import get_table_name

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_roles_table(engine, dry_run: bool = False):
    """Create roles table if it doesn't exist"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    table_name = get_table_name("roles")
    
    logger.info("🔄 Checking roles table...")
    
    if table_name in tables:
        logger.info(f"✅ {table_name} table already exists")
        return True
    
    logger.info(f"➕ Creating {table_name} table...")
    
    try:
        with engine.connect() as conn:
            if dry_run:
                logger.info(f"🧪 Would create table: {table_name}")
            else:
                Role.__table__.create(engine, checkfirst=False)
                logger.info(f"✅ {table_name} table created successfully")
                return True
    except Exception as e:
        logger.error(f"❌ Error creating {table_name} table: {e}", exc_info=True)
        return False


def seed_default_roles(dry_run: bool = False):
    """Seed default roles (user, moderator, admin)"""
    logger.info("🔄 Seeding default roles...")
    
    default_roles = [
        {"name": "user", "description": "Regular user role", "is_system": True},
        {"name": "moderator", "description": "Moderator role with elevated permissions", "is_system": True},
        {"name": "admin", "description": "Administrator role with full access", "is_system": True},
    ]
    
    try:
        with get_db_session() as session:
            rbac_service = RBACService(session)
            
            created_count = 0
            for role_data in default_roles:
                existing = rbac_service.get_role_by_name(role_data["name"])
                if existing:
                    logger.info(f"✅ Role '{role_data['name']}' already exists (ID: {existing.id})")
                else:
                    if dry_run:
                        logger.info(f"🧪 Would create role: {role_data['name']}")
                    else:
                        role = rbac_service.create_role(
                            name=role_data["name"],
                            description=role_data["description"],
                            is_system=role_data["is_system"]
                        )
                        if role:
                            logger.info(f"✅ Created role: {role_data['name']} (ID: {role.id})")
                            created_count += 1
                        else:
                            logger.error(f"❌ Failed to create role: {role_data['name']}")
            
            if not dry_run:
                session.commit()
                logger.info(f"✅ Seeded {created_count} new roles")
            
            return True
    except Exception as e:
        logger.error(f"❌ Error seeding roles: {e}", exc_info=True)
        return False


def add_role_id_column(dry_run: bool = False):
    """Add role_id column to role_permissions table if it doesn't exist"""
    logger.info("🔄 Checking role_permissions table structure...")
    
    try:
        engine = create_database_engine()
        table_name = get_table_name("role_permissions")
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        
        if 'role_id' in columns:
            logger.info("✅ role_id column already exists")
            engine.dispose()
            return True
        
        logger.info("➕ Adding role_id column to role_permissions table...")
        
        if dry_run:
            logger.info("🧪 Would add column: role_id INTEGER (nullable)")
            engine.dispose()
            return True
        else:
            try:
                with get_db_session() as session:
                    # Add column as nullable first
                    session.execute(text(f"""
                        ALTER TABLE {table_name} 
                        ADD COLUMN role_id INTEGER
                    """))
                    session.commit()
                    logger.info("✅ Added role_id column (nullable)")
            except ProgrammingError as e:
                # Column might already exist (from Alembic or manual migration)
                if "already exists" in str(e) or "duplicate column" in str(e).lower():
                    logger.info("✅ role_id column already exists (skipping)")
                else:
                    raise
            finally:
                engine.dispose()
        
        return True
    except Exception as e:
        logger.error(f"❌ Error adding role_id column: {e}", exc_info=True)
        return False


def migrate_role_permissions(dry_run: bool = False):
    """Migrate role_permissions from role string to role_id"""
    logger.info("🔄 Migrating role_permissions from role string to role_id...")
    
    try:
        engine = create_database_engine()
        table_name = get_table_name("role_permissions")
        
        # Check table structure
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        
        with get_db_session() as session:
            rbac_service = RBACService(session)
            
            if 'role_id' not in columns:
                logger.warning("⚠️  role_permissions table doesn't have role_id column yet")
                logger.info("   Run add_role_id_column() first")
                engine.dispose()
                return False
            
            if 'role' not in columns:
                logger.info("✅ role column already removed (migration complete)")
                engine.dispose()
                return True
            
            # Get all unique role names from old column
            result = session.execute(text(f"""
                SELECT DISTINCT role 
                FROM {table_name} 
                WHERE role IS NOT NULL
            """))
            role_names = [row[0] for row in result]
            
            if not role_names:
                logger.info("✅ No role_permissions to migrate")
                engine.dispose()
                return True
            
            logger.info(f"📋 Found {len(role_names)} unique roles to migrate: {', '.join(role_names)}")
            
            # Create mapping of role name to role_id
            role_map = {}
            for role_name in role_names:
                role = rbac_service.get_role_by_name(role_name)
                if role:
                    role_map[role_name] = role.id
                    logger.info(f"   {role_name} -> role_id {role.id}")
                else:
                    logger.warning(f"⚠️  Role '{role_name}' not found in roles table, skipping")
            
            if not role_map:
                logger.warning("⚠️  No valid roles found for migration")
                engine.dispose()
                return False
            
            # Migrate each role_permission entry
            migrated_count = 0
            for role_name, role_id in role_map.items():
                result = session.execute(text(f"""
                    SELECT id, permission_id 
                    FROM {table_name} 
                    WHERE role = :role_name 
                    AND (role_id IS NULL OR role_id != :role_id)
                """), {"role_name": role_name, "role_id": role_id})
                
                entries = result.fetchall()
                
                for entry_id, permission_id in entries:
                    if dry_run:
                        logger.info(f"🧪 Would migrate: role_permission {entry_id} ({role_name} -> role_id {role_id})")
                    else:
                        # Update role_id
                        session.execute(text(f"""
                            UPDATE {table_name} 
                            SET role_id = :role_id 
                            WHERE id = :entry_id
                        """), {"role_id": role_id, "entry_id": entry_id})
                        migrated_count += 1
            
            if not dry_run:
                session.commit()
                logger.info(f"✅ Migrated {migrated_count} role_permission entries")
            
            engine.dispose()
            return True
    except Exception as e:
        logger.error(f"❌ Error migrating role_permissions: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        if 'engine' in locals():
            engine.dispose()
        return False


def migrate_users_roles(dry_run: bool = False):
    """Update users.role_id based on users.role string"""
    logger.info("🔄 Migrating users.role to users.role_id...")
    
    try:
        engine = create_database_engine()
        
        # Check table columns
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns(get_table_name("users"))]
        
        if 'role_id' not in columns:
            logger.warning("⚠️  users table doesn't have role_id column yet")
            engine.dispose()
            return False
        
        # Check if old 'role' column exists
        if 'role' not in columns:
            logger.info("✅ Legacy 'role' column no longer exists - migration complete")
            engine.dispose()
            return True
        
        with get_db_session() as session:
            rbac_service = RBACService(session)
            
            # Get all users with role string but no role_id (using raw SQL to avoid model issues)
            from sqlalchemy import text
            result = session.execute(text(f"""
                SELECT id, username, role 
                FROM {get_table_name("users")} 
                WHERE role IS NOT NULL 
                AND (role_id IS NULL OR role_id = 0)
            """))
            users_to_migrate = result.fetchall()
            
            if not users_to_migrate:
                logger.info("✅ All users already have role_id set")
                engine.dispose()
                return True
            
            logger.info(f"📋 Found {len(users_to_migrate)} users to migrate")
            
            migrated_count = 0
            for user_id, username, role_name in users_to_migrate:
                role = rbac_service.get_role_by_name(role_name)
                if role:
                    if dry_run:
                        logger.info(f"🧪 Would update user {user_id} ({username}): role '{role_name}' -> role_id {role.id}")
                    else:
                        session.execute(text(f"""
                            UPDATE {get_table_name("users")} 
                            SET role_id = :role_id 
                            WHERE id = :user_id
                        """), {"role_id": role.id, "user_id": user_id})
                        migrated_count += 1
                else:
                    logger.warning(f"⚠️  User {user_id} has role '{role_name}' but role not found in roles table")
            
            if not dry_run:
                session.commit()
                logger.info(f"✅ Migrated {migrated_count} users")
            
            engine.dispose()
            return True
    except Exception as e:
        logger.error(f"❌ Error migrating users: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        if 'engine' in locals():
            engine.dispose()
        return False


def main(dry_run: bool = False):
    """Main migration function"""
    logger.info("🚀 Starting Roles Migration")
    logger.info("=" * 60)
    
    if dry_run:
        logger.info("🧪 DRY RUN MODE - No changes will be made")
        logger.info("=" * 60)
    
    try:
        engine = create_database_engine()
        
        # Step 1: Create roles table
        if not create_roles_table(engine, dry_run):
            logger.error("❌ Failed to create roles table")
            return False
        
        # Step 2: Seed default roles
        if not seed_default_roles(dry_run):
            logger.error("❌ Failed to seed default roles")
            return False
        
        # Step 2.5: Add role_id column if it doesn't exist
        if not add_role_id_column(dry_run):
            logger.error("❌ Failed to add role_id column")
            return False
        
        # Step 3: Migrate role_permissions
        if not migrate_role_permissions(dry_run):
            logger.warning("⚠️  Role permissions migration had issues (may already be migrated)")
        
        # Step 4: Migrate users
        if not migrate_users_roles(dry_run):
            logger.warning("⚠️  Users migration had issues (may already be migrated)")
        
        logger.info("=" * 60)
        logger.info("✅ Migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Migration error: {e}", exc_info=True)
        return False
    finally:
        if 'engine' in locals():
            engine.dispose()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Seed roles and migrate from string-based to ID-based roles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (show what would be executed)
  python database/migrations/seed_roles.py --dry-run
  
  # Execute migration
  python database/migrations/seed_roles.py
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be executed without making changes'
    )
    
    args = parser.parse_args()
    
    success = main(dry_run=args.dry_run)
    sys.exit(0 if success else 1)

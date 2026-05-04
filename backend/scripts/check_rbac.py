#!/usr/bin/env python3
"""
Check RBAC System Status

Verifies that RBAC tables exist and permissions are loaded correctly.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.core.connection import create_database_engine
from sqlalchemy import inspect, text
from config import get_table_name
from utils.database.database_session import get_db_session
from database.auth.rbac_service import RBACService

def check_rbac_tables():
    """Check if RBAC tables exist"""
    print("🔍 Checking RBAC Tables...")
    print("=" * 60)
    
    engine = create_database_engine()
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    required_tables = [
        get_table_name("permissions"),
        get_table_name("role_permissions"),
        get_table_name("user_permissions"),
    ]
    
    all_exist = True
    for table in required_tables:
        if table in tables:
            print(f"✅ {table} exists")
        else:
            print(f"❌ {table} MISSING")
            all_exist = False
    
    return all_exist, engine

def check_permissions():
    """Check if permissions are seeded"""
    print("\n🔍 Checking Permissions...")
    print("=" * 60)
    
    with get_db_session() as session:
        rbac_service = RBACService(session)
        permissions = rbac_service.get_all_permissions()
        
        if permissions:
            print(f"✅ Found {len(permissions)} permissions:")
            for perm in permissions[:10]:  # Show first 10
                print(f"   • {perm.name} ({perm.category})")
            if len(permissions) > 10:
                print(f"   ... and {len(permissions) - 10} more")
        else:
            print("❌ No permissions found. Run: python database/migrations/seed_rbac_permissions.py")
            return False
    
    return True

def check_role_permissions():
    """Check role-permission mappings"""
    print("\n🔍 Checking Role-Permission Mappings...")
    print("=" * 60)
    
    with get_db_session() as session:
        rbac_service = RBACService(session)
        
        roles = ["user", "moderator", "admin"]
        for role in roles:
            perms = rbac_service.get_role_permissions(role)
            if perms:
                print(f"✅ {role}: {len(perms)} permissions")
                print(f"   {', '.join(perms[:5])}{'...' if len(perms) > 5 else ''}")
            else:
                print(f"⚠️  {role}: No permissions assigned")
    
    return True

def check_user_permissions():
    """Check if any users have direct permissions"""
    print("\n🔍 Checking User Direct Permissions...")
    print("=" * 60)
    
    with get_db_session() as session:
        from database.auth.models import User as UserModel
        rbac_service = RBACService(session)
        
        users = session.query(UserModel).limit(5).all()
        if not users:
            print("⚠️  No users found in database")
            return True
        
        for user in users:
            direct_perms = rbac_service.get_user_direct_permissions(user.id)
            all_perms = rbac_service.get_user_all_permissions(user.id, user.role_name)
            
            print(f"👤 User {user.id} ({user.username}, role: {user.role_name}):")
            print(f"   Direct permissions: {len(direct_perms)}")
            print(f"   Total permissions: {len(all_perms)}")
            if all_perms:
                print(f"   Sample: {', '.join(all_perms[:3])}{'...' if len(all_perms) > 3 else ''}")
    
    return True

def main():
    """Main entry point"""
    print("🔐 RBAC System Status Check")
    print("=" * 60)
    
    try:
        # Check tables
        tables_exist, engine = check_rbac_tables()
        
        if not tables_exist:
            print("\n❌ RBAC tables are missing!")
            print("   Run: python database/migrations/add_rbac_tables.py")
            return 1
        
        # Check permissions
        if not check_permissions():
            return 1
        
        # Check role mappings
        check_role_permissions()
        
        # Check user permissions
        check_user_permissions()
        
        print("\n" + "=" * 60)
        print("✅ RBAC system appears to be properly configured!")
        print("=" * 60)
        
        return 0
    
    except Exception as e:
        print(f"\n❌ Error checking RBAC: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    finally:
        if 'engine' in locals():
            engine.dispose()

if __name__ == "__main__":
    sys.exit(main())

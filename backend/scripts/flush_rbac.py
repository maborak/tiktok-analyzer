#!/usr/bin/env python3
"""
Flush RBAC Tables and Users

This script clears all RBAC data (permissions, roles, role-permission mappings, user-permission mappings)
and all users from the database. Useful for testing RBAC seeding.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.auth.rbac_models import Permission, Role, role_permissions, user_permissions
from database.auth.models import User, EmailVerification, PasswordReset, UserSession, ApiKey
from utils.database.database_session import get_db_session
from sqlalchemy import delete

def flush_rbac_and_users():
    """Flush all RBAC tables and users"""
    print("🗑️  Flushing RBAC tables and users...")
    
    with get_db_session() as session:
        try:
            # Step 1: Delete all user-permission mappings first (due to foreign keys)
            user_perm_count = session.execute(
                delete(user_permissions)
            ).rowcount
            print(f"   ✓ Deleted {user_perm_count} user-permission mappings")
            
            # Step 2: Delete all role-permission mappings
            role_perm_count = session.execute(
                delete(role_permissions)
            ).rowcount
            print(f"   ✓ Deleted {role_perm_count} role-permission mappings")
            
            # Step 3: Delete all user-related records first (due to foreign keys)
            # Delete email verifications
            email_verif_count = session.query(EmailVerification).count()
            session.query(EmailVerification).delete()
            print(f"   ✓ Deleted {email_verif_count} email verifications")
            
            # Delete password resets
            password_reset_count = session.query(PasswordReset).count()
            session.query(PasswordReset).delete()
            print(f"   ✓ Deleted {password_reset_count} password resets")
            
            # Delete user sessions
            user_session_count = session.query(UserSession).count()
            session.query(UserSession).delete()
            print(f"   ✓ Deleted {user_session_count} user sessions")
            
            # Delete API keys
            api_key_count = session.query(ApiKey).count()
            session.query(ApiKey).delete()
            print(f"   ✓ Deleted {api_key_count} API keys")
            
            # Step 4: Now delete all users (user_permissions already deleted in Step 1)
            user_count = session.query(User).count()
            session.query(User).delete()
            print(f"   ✓ Deleted {user_count} users")
            
            # Step 5: Delete all roles
            role_count = session.query(Role).count()
            session.query(Role).delete()
            print(f"   ✓ Deleted {role_count} roles")
            
            # Step 6: Delete all permissions
            perm_count = session.query(Permission).count()
            session.query(Permission).delete()
            print(f"   ✓ Deleted {perm_count} permissions")
            
            session.commit()
            print("\n✅ All RBAC data and users flushed successfully!")
            
            # Verify flush
            remaining_perms = session.query(Permission).count()
            remaining_roles = session.query(Role).count()
            remaining_users = session.query(User).count()
            remaining_user_perms = session.execute(delete(user_permissions)).rowcount
            remaining_role_perms = session.execute(delete(role_permissions)).rowcount
            session.rollback()  # Rollback the verification deletes
            
            if remaining_perms == 0 and remaining_roles == 0 and remaining_users == 0:
                print("✅ Verification: All RBAC data and users cleared")
            else:
                print(f"⚠️  Warning: Some data still remains:")
                if remaining_perms > 0:
                    print(f"   • {remaining_perms} permissions")
                if remaining_roles > 0:
                    print(f"   • {remaining_roles} roles")
                if remaining_users > 0:
                    print(f"   • {remaining_users} users")
            
            return True
            
        except Exception as e:
            session.rollback()
            print(f"❌ Error flushing RBAC tables and users: {e}")
            import traceback
            traceback.print_exc()
            return False

def flush_rbac():
    """Flush all RBAC tables (keeps users) - for backward compatibility"""
    print("🗑️  Flushing RBAC tables (keeping users)...")
    
    with get_db_session() as session:
        try:
            # Delete all user-permission mappings first (due to foreign keys)
            user_perm_count = session.execute(
                delete(user_permissions)
            ).rowcount
            print(f"   Deleted {user_perm_count} user-permission mappings")
            
            # Delete all role-permission mappings
            role_perm_count = session.execute(
                delete(role_permissions)
            ).rowcount
            print(f"   Deleted {role_perm_count} role-permission mappings")
            
            # Delete all permissions
            perm_count = session.execute(
                delete(Permission)
            ).rowcount
            print(f"   Deleted {perm_count} permissions")
            
            session.commit()
            print("✅ RBAC tables flushed successfully!")
            
            # Verify flush
            remaining_perms = session.query(Permission).count()
            if remaining_perms == 0:
                print("✅ Verification: All RBAC data cleared")
            else:
                print(f"⚠️  Warning: {remaining_perms} permissions still remain")
            
            return True
            
        except Exception as e:
            session.rollback()
            print(f"❌ Error flushing RBAC tables: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Flush RBAC tables and optionally users")
    parser.add_argument(
        "--include-users",
        action="store_true",
        help="Also delete all users (default: False, only deletes RBAC data)"
    )
    args = parser.parse_args()
    
    print("=" * 60)
    if args.include_users:
        print("RBAC Tables and Users Flush Script")
    else:
        print("RBAC Tables Flush Script")
    print("=" * 60)
    print()
    
    if args.include_users:
        success = flush_rbac_and_users()
    else:
        success = flush_rbac()
    
    print()
    if success:
        print("💡 Tip: Run 'python cli.py system db seed' to reseed RBAC data")
        sys.exit(0)
    else:
        sys.exit(1)

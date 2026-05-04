import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from database import get_session_maker
from database.auth.models import User
from database.shared.enums import UserRole
from database.auth.utils import generate_salt, hash_password
from sqlalchemy.exc import IntegrityError

from database.auth.rbac_models import Role

from database import get_session_maker, create_database_engine

def create_user():
    engine = create_database_engine()
    SessionLocal = get_session_maker(engine)
    session = SessionLocal()
    
    email = "test_user_credits@example.com"
    password = "TestPassword123!"
    
    try:
        # Get Role ID
        role = session.query(Role).filter(Role.name == UserRole.USER.value).first()
        if not role:
            print("Role 'user' not found. Creating it...")
            role = Role(name=UserRole.USER.value, description="Standard user")
            session.add(role)
            session.flush()
            
        role_id = role.id

        # Check if exists
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            print(f"User {email} already exists. Updating password.")
            salt = generate_salt()
            pwd_hash = hash_password(password, salt)
            existing.password_hash = pwd_hash
            existing.salt = salt
            existing.is_active = True
            existing.is_verified = True
            existing.role_id = role_id
            existing.credits = 5
            session.commit()
            print("Password updated.")
            return

        print(f"Creating user {email}...")
        salt = generate_salt()
        pwd_hash = hash_password(password, salt)
        
        user = User(
            username=email, # Use email as username
            email=email,
            password_hash=pwd_hash,
            salt=salt,
            first_name="Test",
            last_name="Credits",
            role_id=role_id,
            is_active=True,
            is_verified=True,
            credits=5  # Use small number for faster testing
        )
        
        # Need to handle Role foreign key. 
        # Usually checking Role table first.
        # But let's assume standard roles exist.
        # Or check `role_id` mapping.
        # `User` model uses `role_id = Column(Integer, ForeignKey...`
        # `UserRole` enum usually maps to ID?
        # Let's check `database/auth/rbac_models.py` or similar if needed.
        # For now, try hardcoding 1 or 2.
        
        session.add(user)
        session.commit()
        print(f"User {email} created successfully.")
        
    except Exception as e:
        session.rollback()
        print(f"Error creating user: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    create_user()

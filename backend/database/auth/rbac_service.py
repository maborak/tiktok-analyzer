"""
RBAC Service

Service for managing permissions, role-permission mappings, and user permissions.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
import logging

from database.auth.rbac_models import Permission, Role, role_permissions, user_permissions
from domain.entities.rbac_models import Permission as DomainPermission
from domain.entities.auth_models import UserRole

logger = logging.getLogger(__name__)


class RBACService:
    """Service for RBAC operations"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_permission_by_name(self, name: str) -> Optional[Permission]:
        """Get permission by name"""
        return self.session.query(Permission).filter(
            and_(
                Permission.name == name,
                Permission.is_active == True
            )
        ).first()
    
    def get_permission_by_id(self, permission_id: int) -> Optional[Permission]:
        """Get permission by ID"""
        return self.session.query(Permission).filter(
            and_(
                Permission.id == permission_id,
                Permission.is_active == True
            )
        ).first()
    
    def get_all_permissions(self, category: Optional[str] = None) -> List[Permission]:
        """Get all active permissions, optionally filtered by category"""
        query = self.session.query(Permission).filter(Permission.is_active == True)
        if category:
            query = query.filter(Permission.category == category)
        return query.all()
    
    def get_role_permissions(self, role: str) -> List[str]:
        """
        Get all permission names for a given role.
        
        Args:
            role: Role name (user, moderator, admin)
            
        Returns:
            List of permission names
        """
        # Look up role_id from role name
        role_obj = self.get_role_by_name(role)
        if not role_obj:
            return []
        
        # Query role_permissions table to get permission IDs for the role
        from sqlalchemy import select
        
        stmt = select(role_permissions.c.permission_id).where(
            role_permissions.c.role_id == role_obj.id
        )
        permission_ids = [row[0] for row in self.session.execute(stmt).fetchall()]
        
        if not permission_ids:
            return []
        
        # Get permission names
        permissions = self.session.query(Permission).filter(
            and_(
                Permission.id.in_(permission_ids),
                Permission.is_active == True
            )
        ).all()
        
        return [perm.name for perm in permissions]
    
    def get_user_direct_permissions(self, user_id: int) -> List[str]:
        """
        Get direct permissions for a user (not from role).
        
        Args:
            user_id: User ID
            
        Returns:
            List of permission names
        """
        # Query user_permissions table
        from sqlalchemy import select
        
        stmt = select(user_permissions.c.permission_id).where(
            user_permissions.c.user_id == user_id
        )
        permission_ids = [row[0] for row in self.session.execute(stmt).fetchall()]
        
        if not permission_ids:
            return []
        
        # Get permission names
        permissions = self.session.query(Permission).filter(
            and_(
                Permission.id.in_(permission_ids),
                Permission.is_active == True
            )
        ).all()
        
        return [perm.name for perm in permissions]
    
    def get_user_all_permissions(self, user_id: int, role: str) -> List[str]:
        """
        Get all permissions for a user (role permissions + direct permissions).
        
        Args:
            user_id: User ID
            role: User's role
            
        Returns:
            List of all permission names
        """
        # Get role permissions
        role_perms = self.get_role_permissions(role)
        
        # Get direct user permissions
        direct_perms = self.get_user_direct_permissions(user_id)
        
        # Combine and deduplicate (direct permissions take precedence, but we include both)
        all_perms = list(set(role_perms + direct_perms))
        
        return all_perms
    
    def create_permission(self, name: str, description: Optional[str] = None, 
                        category: Optional[str] = None) -> Permission:
        """Create a new permission"""
        permission = Permission(
            name=name,
            description=description,
            category=category,
            is_active=True
        )
        self.session.add(permission)
        self.session.flush()
        return permission
    
    def assign_permission_to_role(self, role: str, permission_id: int) -> bool:
        """
        Assign a permission to a role (by role name).
        
        Args:
            role: Role name
            permission_id: Permission ID
            
        Returns:
            True if assigned, False if already exists or role not found
        """
        # Look up role_id from role name
        role_obj = self.get_role_by_name(role)
        if not role_obj:
            return False
        
        # Use the role_id based method
        return self.assign_permission_to_role_by_id(role_obj.id, permission_id)
    
    def remove_permission_from_role(self, role: str, permission_id: int) -> bool:
        """Remove a permission from a role (by role name)"""
        # Look up role_id from role name
        role_obj = self.get_role_by_name(role)
        if not role_obj:
            return False
        
        # Use the role_id based method
        return self.remove_permission_from_role_by_id(role_obj.id, permission_id)
    
    def assign_permission_to_user(self, user_id: int, permission_id: int) -> bool:
        """
        Assign a direct permission to a user (overrides role permissions).
        
        Args:
            user_id: User ID
            permission_id: Permission ID
            
        Returns:
            True if assigned, False if already exists
        """
        # Check if already assigned
        from sqlalchemy import select
        
        stmt = select(user_permissions).where(
            and_(
                user_permissions.c.user_id == user_id,
                user_permissions.c.permission_id == permission_id
            )
        )
        existing = self.session.execute(stmt).first()
        
        if existing:
            return False
        
        # Insert new assignment
        from sqlalchemy import insert
        stmt = insert(user_permissions).values(
            user_id=user_id,
            permission_id=permission_id
        )
        self.session.execute(stmt)
        return True
    
    def remove_permission_from_user(self, user_id: int, permission_id: int) -> bool:
        """Remove a direct permission from a user"""
        stmt = user_permissions.delete().where(
            and_(
                user_permissions.c.user_id == user_id,
                user_permissions.c.permission_id == permission_id
            )
        )
        result = self.session.execute(stmt)
        return result.rowcount > 0
    
    # Role Management Methods
    
    def get_role_by_id(self, role_id: int) -> Optional[Role]:
        """Get role by ID"""
        return self.session.query(Role).filter(
            and_(
                Role.id == role_id,
                Role.is_active == True
            )
        ).first()
    
    def get_role_by_name(self, name: str) -> Optional[Role]:
        """Get role by name"""
        return self.session.query(Role).filter(
            and_(
                Role.name == name,
                Role.is_active == True
            )
        ).first()
    
    def get_all_roles(self, include_inactive: bool = False) -> List[Role]:
        """Get all roles, optionally including inactive ones"""
        query = self.session.query(Role)
        if not include_inactive:
            query = query.filter(Role.is_active == True)
        return query.order_by(Role.name).all()
    
    def create_role(self, name: str, description: Optional[str] = None, is_system: bool = False) -> Optional[Role]:
        """Create a new role"""
        # Check if role already exists
        existing = self.get_role_by_name(name)
        if existing:
            return None
        
        role = Role(
            name=name,
            description=description,
            is_system=is_system,
            is_active=True
        )
        self.session.add(role)
        self.session.flush()
        return role
    
    def update_role(self, role_id: int, name: Optional[str] = None, description: Optional[str] = None, 
                   is_active: Optional[bool] = None) -> Optional[Role]:
        """Update a role"""
        role = self.get_role_by_id(role_id)
        if not role:
            return None
        
        if name is not None:
            # Check if new name conflicts with existing role
            existing = self.get_role_by_name(name)
            if existing and existing.id != role_id:
                return None
            role.name = name
        
        if description is not None:
            role.description = description
        
        if is_active is not None:
            role.is_active = is_active
        
        self.session.flush()
        return role
    
    def delete_role(self, role_id: int) -> bool:
        """Delete a role (only if not system role)"""
        role = self.get_role_by_id(role_id)
        if not role or role.is_system:
            return False
        
        # Soft delete by setting is_active to False
        role.is_active = False
        self.session.flush()
        return True
    
    def get_role_permissions_by_id(self, role_id: int) -> List[str]:
        """
        Get all permission names for a role by role_id.
        
        Args:
            role_id: Role ID
            
        Returns:
            List of permission names
        """
        from sqlalchemy import select
        
        stmt = select(role_permissions.c.permission_id).where(
            role_permissions.c.role_id == role_id
        )
        permission_ids = [row[0] for row in self.session.execute(stmt).fetchall()]
        
        if not permission_ids:
            return []
        
        # Get permission names
        permissions = self.session.query(Permission).filter(
            and_(
                Permission.id.in_(permission_ids),
                Permission.is_active == True
            )
        ).all()
        
        return [perm.name for perm in permissions]
    
    def assign_permission_to_role_by_id(self, role_id: int, permission_id: int) -> bool:
        """Assign a permission to a role by role_id"""
        from sqlalchemy import select, insert
        from sqlalchemy.exc import IntegrityError
        
        # Check if already exists
        stmt = select(role_permissions).where(
            and_(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == permission_id
            )
        )
        existing = self.session.execute(stmt).first()
        
        if existing:
            return False
        
        # Use insert() function
        stmt = insert(role_permissions).values(
            role_id=role_id,
            permission_id=permission_id
        )
        try:
            # Use the session directly - it should handle RetrySession wrapper automatically
            self.session.execute(stmt)
            return True
        except IntegrityError:
            # Duplicate entry - already exists
            return False
        except Exception as e:
            # Re-raise other errors
            raise
    
    def remove_permission_from_role_by_id(self, role_id: int, permission_id: int) -> bool:
        """Remove a permission from a role by role_id"""
        stmt = role_permissions.delete().where(
            and_(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == permission_id
            )
        )
        result = self.session.execute(stmt)
        return result.rowcount > 0

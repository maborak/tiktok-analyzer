"""
RBAC (Role-Based Access Control) Database Models

Defines permissions, roles, role-permission mappings, and user-permission overrides.
"""

from ..core.base import Base
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Table, Text, func, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from config import get_table_name


# Junction table for role-permission many-to-many relationship
# Uses role_id foreign key to roles table
# Defined before Role class to avoid circular reference
role_permissions = Table(
    get_table_name("role_permissions"),
    Base.metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('role_id', Integer, ForeignKey(f'{get_table_name("roles")}.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('permission_id', Integer, ForeignKey(f'{get_table_name("permissions")}.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('created_at', DateTime, default=func.current_timestamp(), nullable=False),
    UniqueConstraint('role_id', 'permission_id', name='uq_role_permission'),
    Index('idx_role_permissions_role', 'role_id'),
    Index('idx_role_permissions_permission', 'permission_id')
)


class Role(Base):
    """
    SQLAlchemy model for roles
    
    Stores roles that can be assigned to users and linked to permissions.
    """
    __tablename__ = get_table_name("roles")
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Role identification
    name = Column(String(50), nullable=False, unique=True, index=True)  # e.g., "user", "admin", "moderator", "viewer"
    description = Column(Text, nullable=True)  # Human-readable description
    is_system = Column(Boolean, default=False, nullable=False, index=True)  # System roles cannot be deleted
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Relationships
    permissions = relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles"
    )
    
    def __repr__(self):
        return f"<Role(id={self.id}, name='{self.name}', is_system={self.is_system})>"
    
    def __str__(self):
        return f"Role: {self.name}"


# Junction table for user-permission many-to-many relationship (for direct user permissions)
user_permissions = Table(
    get_table_name("user_permissions"),
    Base.metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('user_id', Integer, ForeignKey(f'{get_table_name("users")}.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('permission_id', Integer, ForeignKey(f'{get_table_name("permissions")}.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('created_at', DateTime, default=func.current_timestamp(), nullable=False),
    UniqueConstraint('user_id', 'permission_id', name='uq_user_permission'),
    Index('idx_user_permissions_user', 'user_id'),
    Index('idx_user_permissions_permission', 'permission_id')
)


class Permission(Base):
    """
    SQLAlchemy model for permissions
    
    Stores individual permissions that can be assigned to roles or users.
    """
    __tablename__ = get_table_name("permissions")
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Permission identification
    name = Column(String(100), nullable=False, unique=True, index=True)  # e.g., "admin:read", "products:write"
    description = Column(Text, nullable=True)  # Human-readable description
    category = Column(String(50), nullable=True, index=True)  # e.g., "admin", "products", "monitoring"
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Relationships
    # Direct user permissions (many-to-many)
    users = relationship(
        "User",
        secondary=user_permissions,
        back_populates="direct_permissions"
    )
    # Roles that have this permission (many-to-many)
    roles = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions"
    )
    
    def __repr__(self):
        return f"<Permission(id={self.id}, name='{self.name}', category='{self.category}')>"
    
    def __str__(self):
        return f"Permission: {self.name}"


# Note: We'll need to update the User model in models.py to add the relationships
# This will be done in a separate step to avoid circular imports

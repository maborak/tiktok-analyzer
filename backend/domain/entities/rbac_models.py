"""
RBAC Domain Models

Domain entities for Role-Based Access Control system.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List


@dataclass
class Permission:
    """Domain model for permissions"""
    id: int
    name: str  # e.g., "admin:read", "products:write", "monitoring:view"
    description: Optional[str] = None
    category: Optional[str] = None  # e.g., "admin", "products", "monitoring"
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __str__(self):
        return f"Permission: {self.name}"


@dataclass
class RolePermission:
    """Domain model for role-permission mapping"""
    id: int
    role: str  # "user", "moderator", "admin"
    permission_id: int
    permission: Optional[Permission] = None
    created_at: Optional[datetime] = None


@dataclass
class UserPermission:
    """Domain model for direct user-permission mapping (overrides role permissions)"""
    id: int
    user_id: int
    permission_id: int
    permission: Optional[Permission] = None
    created_at: Optional[datetime] = None

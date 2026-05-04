"""
RBAC Port (Interface)

Defines the abstract interface for Role-Based Access Control operations.
Follows hexagonal architecture — routes call this port, adapters implement it.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class RBACPort(ABC):
    """Abstract interface for RBAC operations.

    All methods manage their own sessions and transactions internally.
    Callers never see SQLAlchemy models — only plain dicts are returned.
    """

    # ── Permission CRUD ──────────────────────────────────────────────

    @abstractmethod
    def get_permission_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get an active permission by name.

        Returns:
            Dict with keys: id, name, description, category, is_active,
            created_at, updated_at — or None.
        """
        ...

    @abstractmethod
    def get_permission_by_id(self, permission_id: int) -> Optional[Dict[str, Any]]:
        """Get an active permission by ID.

        Returns:
            Dict with same keys as get_permission_by_name, or None.
        """
        ...

    @abstractmethod
    def get_all_permissions(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all active permissions, optionally filtered by category."""
        ...

    @abstractmethod
    def list_permissions(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> Dict[str, Any]:
        """Paginated permission listing with filtering and sorting.

        Returns:
            Dict with keys: total, page, page_size, total_pages, permissions (list of dicts).
        """
        ...

    @abstractmethod
    def create_permission(
        self,
        name: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and persist a new permission. Returns the created permission dict."""
        ...

    @abstractmethod
    def update_permission(
        self,
        permission_id: int,
        *,
        description: Optional[str] = None,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update an existing permission. Returns updated dict or None if not found."""
        ...

    @abstractmethod
    def delete_permission(self, permission_id: int) -> bool:
        """Delete a permission and all its role/user mappings.

        Returns:
            True if deleted, False if not found.
        """
        ...

    # ── Role CRUD ────────────────────────────────────────────────────

    @abstractmethod
    def get_role_by_id(self, role_id: int) -> Optional[Dict[str, Any]]:
        """Get an active role by ID.

        Returns:
            Dict with keys: id, name, description, is_system, is_active,
            created_at, updated_at — or None.
        """
        ...

    @abstractmethod
    def get_role_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get an active role by name."""
        ...

    @abstractmethod
    def get_all_roles(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """Get all roles."""
        ...

    @abstractmethod
    def list_roles(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        is_active: Optional[bool] = None,
        is_system: Optional[bool] = None,
        search: Optional[str] = None,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> Dict[str, Any]:
        """Paginated role listing with filtering and sorting.

        Returns:
            Dict with keys: total, page, page_size, total_pages, roles (list of dicts).
        """
        ...

    @abstractmethod
    def create_role(
        self,
        name: str,
        description: Optional[str] = None,
        is_system: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Create a new role. Returns created dict or None if name already exists."""
        ...

    @abstractmethod
    def update_role(
        self,
        role_id: int,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update a role. Returns updated dict or None if not found / name conflict."""
        ...

    @abstractmethod
    def delete_role(self, role_id: int) -> bool:
        """Soft-delete a role (set is_active=False). System roles cannot be deleted."""
        ...

    # ── Role-Permission mappings ─────────────────────────────────────

    @abstractmethod
    def get_role_permissions(self, role: str) -> List[str]:
        """Get permission names for a role (by role name)."""
        ...

    @abstractmethod
    def get_role_permissions_by_id(self, role_id: int) -> List[str]:
        """Get permission names for a role (by role ID)."""
        ...

    @abstractmethod
    def assign_permission_to_role(self, role: str, permission_id: int) -> bool:
        """Assign a permission to a role by role name."""
        ...

    @abstractmethod
    def assign_permission_to_role_by_id(self, role_id: int, permission_id: int) -> bool:
        """Assign a permission to a role by role ID."""
        ...

    @abstractmethod
    def remove_permission_from_role(self, role: str, permission_id: int) -> bool:
        """Remove a permission from a role by role name."""
        ...

    @abstractmethod
    def remove_permission_from_role_by_id(self, role_id: int, permission_id: int) -> bool:
        """Remove a permission from a role by role ID."""
        ...

    # ── User-Permission mappings ─────────────────────────────────────

    @abstractmethod
    def get_user_direct_permissions(self, user_id: int) -> List[str]:
        """Get direct permission names for a user (not from role)."""
        ...

    @abstractmethod
    def get_user_all_permissions(self, user_id: int, role: str) -> List[str]:
        """Get all permissions for a user (role + direct)."""
        ...

    @abstractmethod
    def assign_permission_to_user(self, user_id: int, permission_id: int) -> bool:
        """Assign a direct permission to a user."""
        ...

    @abstractmethod
    def remove_permission_from_user(self, user_id: int, permission_id: int) -> bool:
        """Remove a direct permission from a user."""
        ...

    # ── User existence check ─────────────────────────────────────────

    @abstractmethod
    def user_exists(self, user_id: int) -> bool:
        """Check whether a user with the given ID exists."""
        ...

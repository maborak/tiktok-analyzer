"""
RBAC Adapter

Implements RBACPort by wrapping the existing database-level RBACService.
Each method opens its own session via the injected session factory,
delegates to RBACService, commits if needed, and returns plain dicts.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from contextlib import contextmanager

from ports.rbac import RBACPort

logger = logging.getLogger(__name__)


def _permission_to_dict(perm) -> Dict[str, Any]:
    """Convert a Permission SQLAlchemy model to a plain dict."""
    return {
        "id": perm.id,
        "name": perm.name,
        "description": perm.description,
        "category": perm.category,
        "is_active": perm.is_active,
        "created_at": perm.created_at,
        "updated_at": perm.updated_at,
    }


def _role_to_dict(role) -> Dict[str, Any]:
    """Convert a Role SQLAlchemy model to a plain dict."""
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "is_active": role.is_active,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }


class RBACAdapter(RBACPort):
    """Adapter that implements RBACPort using the database-level RBACService.

    Args:
        session_factory: A callable that returns a context-manager yielding
            a SQLAlchemy Session (e.g. ``get_db_session``).
    """

    def __init__(self, session_factory: Callable):
        self._session_factory = session_factory

    @contextmanager
    def _service(self, *, commit: bool = False):
        """Yield an RBACService bound to a fresh session.

        If *commit* is True the session is committed before closing.
        """
        from database.auth.rbac_service import RBACService

        with self._session_factory() as session:
            svc = RBACService(session)
            yield svc
            if commit:
                session.commit()

    # ── Permission CRUD ──────────────────────────────────────────────

    def get_permission_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        with self._service() as svc:
            perm = svc.get_permission_by_name(name)
            return _permission_to_dict(perm) if perm else None

    def get_permission_by_id(self, permission_id: int) -> Optional[Dict[str, Any]]:
        with self._service() as svc:
            perm = svc.get_permission_by_id(permission_id)
            return _permission_to_dict(perm) if perm else None

    def get_all_permissions(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._service() as svc:
            perms = svc.get_all_permissions(category=category)
            return [_permission_to_dict(p) for p in perms]

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
        from database.auth.rbac_models import Permission as PermissionModel
        from sqlalchemy import or_, asc as sa_asc, desc as sa_desc

        with self._service() as svc:
            query = svc.session.query(PermissionModel)

            if category:
                query = query.filter(PermissionModel.category == category)
            if is_active is not None:
                query = query.filter(PermissionModel.is_active == is_active)
            if search:
                term = f"%{search}%"
                query = query.filter(
                    or_(
                        PermissionModel.name.ilike(term),
                        PermissionModel.description.ilike(term),
                    )
                )

            total = query.count()

            sort_columns = {
                "id": PermissionModel.id,
                "name": PermissionModel.name,
                "category": PermissionModel.category,
                "created_at": PermissionModel.created_at,
                "updated_at": PermissionModel.updated_at,
            }
            col = sort_columns.get(sort_by, PermissionModel.name)
            order_fn = sa_asc if sort_order.lower() == "asc" else sa_desc
            query = query.order_by(order_fn(col))

            permissions = query.offset((page - 1) * page_size).limit(page_size).all()
            total_pages = (total + page_size - 1) // page_size

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "permissions": [_permission_to_dict(p) for p in permissions],
            }

    def create_permission(
        self,
        name: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._service(commit=True) as svc:
            perm = svc.create_permission(name=name, description=description, category=category)
            svc.session.flush()
            svc.session.refresh(perm)
            return _permission_to_dict(perm)

    def update_permission(
        self,
        permission_id: int,
        *,
        description: Optional[str] = None,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._service(commit=True) as svc:
            perm = svc.get_permission_by_id(permission_id)
            if not perm:
                return None

            if description is not None:
                perm.description = description
            if category is not None:
                perm.category = category
            if is_active is not None:
                perm.is_active = is_active

            perm.updated_at = datetime.now(timezone.utc)
            svc.session.flush()
            svc.session.refresh(perm)
            return _permission_to_dict(perm)

    def delete_permission(self, permission_id: int) -> bool:
        from database.auth.rbac_models import role_permissions, user_permissions

        with self._service(commit=True) as svc:
            perm = svc.get_permission_by_id(permission_id)
            if not perm:
                return False

            # Remove role-permission mappings
            svc.session.execute(
                role_permissions.delete().where(role_permissions.c.permission_id == permission_id)
            )
            # Remove user-permission mappings
            svc.session.execute(
                user_permissions.delete().where(user_permissions.c.permission_id == permission_id)
            )
            svc.session.delete(perm)
            return True

    # ── Role CRUD ────────────────────────────────────────────────────

    def get_role_by_id(self, role_id: int) -> Optional[Dict[str, Any]]:
        with self._service() as svc:
            role = svc.get_role_by_id(role_id)
            return _role_to_dict(role) if role else None

    def get_role_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        with self._service() as svc:
            role = svc.get_role_by_name(name)
            return _role_to_dict(role) if role else None

    def get_all_roles(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        with self._service() as svc:
            roles = svc.get_all_roles(include_inactive=include_inactive)
            return [_role_to_dict(r) for r in roles]

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
        from database.auth.rbac_models import Role as RoleModel
        from sqlalchemy import or_, asc as sa_asc, desc as sa_desc

        with self._service() as svc:
            query = svc.session.query(RoleModel)

            if is_active is not None:
                query = query.filter(RoleModel.is_active == is_active)
            if is_system is not None:
                query = query.filter(RoleModel.is_system == is_system)
            if search:
                term = f"%{search}%"
                query = query.filter(
                    or_(
                        RoleModel.name.ilike(term),
                        RoleModel.description.ilike(term),
                    )
                )

            total = query.count()

            sort_columns = {
                "id": RoleModel.id,
                "name": RoleModel.name,
                "created_at": RoleModel.created_at,
                "updated_at": RoleModel.updated_at,
            }
            col = sort_columns.get(sort_by, RoleModel.name)
            order_fn = sa_asc if sort_order.lower() == "asc" else sa_desc
            query = query.order_by(order_fn(col))

            roles = query.offset((page - 1) * page_size).limit(page_size).all()
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "roles": [_role_to_dict(r) for r in roles],
            }

    def create_role(
        self,
        name: str,
        description: Optional[str] = None,
        is_system: bool = False,
    ) -> Optional[Dict[str, Any]]:
        with self._service(commit=True) as svc:
            role = svc.create_role(name=name, description=description, is_system=is_system)
            if not role:
                return None
            svc.session.flush()
            svc.session.refresh(role)
            return _role_to_dict(role)

    def update_role(
        self,
        role_id: int,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._service(commit=True) as svc:
            updated = svc.update_role(
                role_id=role_id,
                name=name,
                description=description,
                is_active=is_active,
            )
            if not updated:
                return None
            svc.session.flush()
            svc.session.refresh(updated)
            return _role_to_dict(updated)

    def delete_role(self, role_id: int) -> bool:
        with self._service(commit=True) as svc:
            return svc.delete_role(role_id)

    # ── Role-Permission mappings ─────────────────────────────────────

    def get_role_permissions(self, role: str) -> List[str]:
        with self._service() as svc:
            return svc.get_role_permissions(role)

    def get_role_permissions_by_id(self, role_id: int) -> List[str]:
        with self._service() as svc:
            return svc.get_role_permissions_by_id(role_id)

    def assign_permission_to_role(self, role: str, permission_id: int) -> bool:
        with self._service(commit=True) as svc:
            return svc.assign_permission_to_role(role, permission_id)

    def assign_permission_to_role_by_id(self, role_id: int, permission_id: int) -> bool:
        with self._service(commit=True) as svc:
            return svc.assign_permission_to_role_by_id(role_id, permission_id)

    def remove_permission_from_role(self, role: str, permission_id: int) -> bool:
        with self._service(commit=True) as svc:
            return svc.remove_permission_from_role(role, permission_id)

    def remove_permission_from_role_by_id(self, role_id: int, permission_id: int) -> bool:
        with self._service(commit=True) as svc:
            return svc.remove_permission_from_role_by_id(role_id, permission_id)

    # ── User-Permission mappings ─────────────────────────────────────

    def get_user_direct_permissions(self, user_id: int) -> List[str]:
        with self._service() as svc:
            return svc.get_user_direct_permissions(user_id)

    def get_user_all_permissions(self, user_id: int, role: str) -> List[str]:
        with self._service() as svc:
            return svc.get_user_all_permissions(user_id, role)

    def assign_permission_to_user(self, user_id: int, permission_id: int) -> bool:
        with self._service(commit=True) as svc:
            return svc.assign_permission_to_user(user_id, permission_id)

    def remove_permission_from_user(self, user_id: int, permission_id: int) -> bool:
        with self._service(commit=True) as svc:
            return svc.remove_permission_from_user(user_id, permission_id)

    # ── User existence check ─────────────────────────────────────────

    def user_exists(self, user_id: int) -> bool:
        from database.auth.models import User as UserModel

        with self._service() as svc:
            return svc.session.query(UserModel).filter(UserModel.id == user_id).first() is not None

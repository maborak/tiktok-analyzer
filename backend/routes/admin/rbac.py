"""
Admin RBAC Routes

Routes for managing Role-Based Access Control (permissions, role-permissions, user-permissions).

Architecture note: This module uses an injected RBACPort (set by setup_routes)
instead of importing database models or services directly.
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from typing import List, Optional
from datetime import datetime
import logging

from domain.entities.auth_models import AuthContext, UserRole
from domain.services.auth_service import AuthService
from utils.database.force_write import require_read_db, require_write_db
from pydantic import BaseModel, Field, ConfigDict
from routes.auth import get_auth_service
from utils.database.force_write import consistency_context
from ports.rbac import RBACPort

logger = logging.getLogger(__name__)

router = APIRouter()

# Injected by setup_routes() — see routes/main.py
rbac_port: Optional[RBACPort] = None


def _get_rbac_port() -> RBACPort:
    """FastAPI dependency that returns the injected RBACPort."""
    if rbac_port is None:
        raise RuntimeError("RBACPort has not been injected — check setup_routes()")
    return rbac_port


# OAuth2 scheme for Swagger UI compatibility
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/token",
    auto_error=False,
    scopes={
        "read": "Read access",
        "write": "Write access",
        "admin": "Administrative access"
    }
)

# Bearer token for programmatic access
bearer_security = HTTPBearer(auto_error=False)


async def get_admin_write_permission(
    request: Request,
    oauth2_token: Optional[str] = Depends(oauth2_scheme),
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_security),
    auth_service: AuthService = Depends(get_auth_service)
) -> AuthContext:
    """
    Dependency to get admin user - requires admin:write permission.
    Supports both OAuth2 (Swagger UI) and Bearer token authentication.
    """
    token = None

    # Try OAuth2 token first (from Swagger UI)
    if oauth2_token:
        token = oauth2_token
    # Fall back to Bearer token (for programmatic access)
    elif bearer_credentials:
        token = bearer_credentials.credentials

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Get auth context from token
    auth_context = auth_service.get_auth_context(token)

    if not auth_context:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Check if user has admin:write permission (using RBAC)
    if not auth_context.has_permission("admin:write"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin:write permission required"
        )

    # Explicitly verify user role is admin (only admins can access /admin/* routes)
    if auth_context.user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to access admin routes"
        )

    return auth_context


async def get_admin_write_permission_read_only(
    request: Request,
    oauth2_token: Optional[str] = Depends(oauth2_scheme),
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_security),
    auth_service: AuthService = Depends(get_auth_service)
) -> AuthContext:
    """
    Dependency to get admin user - requires admin:write permission (read-only mode).
    Uses read replica for auth checks.
    """
    token = None

    # Try OAuth2 token first (from Swagger UI)
    if oauth2_token:
        token = oauth2_token
    # Fall back to Bearer token (for programmatic access)
    elif bearer_credentials:
        token = bearer_credentials.credentials

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Get auth context from token (using read replica)
    with consistency_context("read"):
        auth_context = auth_service.get_auth_context(token)

    if not auth_context:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Check if user has admin:write permission (using RBAC)
    if not auth_context.has_permission("admin:write"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin:write permission required"
        )

    # Explicitly verify user role is admin (only admins can access /admin/* routes)
    if auth_context.user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to access admin routes"
        )

    return auth_context




# Pydantic Models for Request/Response

class PermissionResponse(BaseModel):
    """Permission response model"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PermissionCreateRequest(BaseModel):
    """Request model for creating a permission"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "products:read",
                "description": "Read access to products",
                "category": "products"
            }
        }
    )

    name: str = Field(..., min_length=1, max_length=100, description="Permission name (e.g., 'admin:read', 'products:write')")
    description: Optional[str] = Field(None, description="Human-readable description")
    category: Optional[str] = Field(None, max_length=50, description="Permission category (e.g., 'admin', 'products', 'monitoring')")


class PermissionUpdateRequest(BaseModel):
    """Request model for updating a permission"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "description": "Updated description",
                "category": "products",
                "is_active": True
            }
        }
    )

    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None


class PermissionsListResponse(BaseModel):
    """Response model for permissions list"""
    total: int
    page: int
    page_size: int
    total_pages: int
    permissions: List[PermissionResponse]


class RolePermissionResponse(BaseModel):
    """Response model for role-permission mapping"""
    id: int
    role: str
    permission_id: int
    permission: Optional[PermissionResponse] = None
    created_at: datetime


class UserPermissionResponse(BaseModel):
    """Response model for user-permission mapping"""
    id: int
    user_id: int
    permission_id: int
    permission: Optional[PermissionResponse] = None
    created_at: datetime


class RolePermissionsResponse(BaseModel):
    """Response model for role permissions list"""
    role: str
    permissions: List[PermissionResponse]


class UserPermissionsResponse(BaseModel):
    """Response model for user permissions list"""
    user_id: int
    permissions: List[PermissionResponse]


class AssignPermissionRequest(BaseModel):
    """Request model for assigning permission to role or user"""
    permission_id: int = Field(..., ge=1, description="Permission ID to assign")


# Role Pydantic Models

class RoleResponse(BaseModel):
    """Role response model"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    is_system: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoleCreateRequest(BaseModel):
    """Request model for creating a role"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "viewer",
                "description": "View-only access role",
                "is_system": False
            }
        }
    )

    name: str = Field(..., min_length=1, max_length=50, description="Role name (e.g., 'user', 'admin', 'viewer')")
    description: Optional[str] = Field(None, description="Human-readable description")
    is_system: bool = Field(default=False, description="System role (cannot be deleted)")


class RoleUpdateRequest(BaseModel):
    """Request model for updating a role"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "viewer_updated",
                "description": "Updated description",
                "is_active": True
            }
        }
    )

    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RolesListResponse(BaseModel):
    """Response model for roles list"""
    total: int
    page: int
    page_size: int
    total_pages: int
    roles: List[RoleResponse]


def _dict_to_permission_response(d: dict) -> PermissionResponse:
    """Convert a permission dict (from RBACPort) to PermissionResponse."""
    return PermissionResponse(**d)


def _dict_to_role_response(d: dict) -> RoleResponse:
    """Convert a role dict (from RBACPort) to RoleResponse."""
    return RoleResponse(**d)


# Permissions CRUD Endpoints

@router.get("/rbac/permissions",
         tags=["Admin"],
         summary="List Permissions",
         description="Get a paginated list of permissions with filtering and sorting. Requires admin:write permission.",
         response_model=PermissionsListResponse)
@require_read_db
async def list_permissions(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    category: Optional[str] = Query(None, max_length=50, description="Filter by category"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, max_length=100, description="Search by name or description"),
    sort_by: str = Query("name", description="Sort by field: id, name, category, created_at, updated_at"),
    sort_order: str = Query("asc", description="Sort order: asc or desc"),
    current_user: AuthContext = Depends(get_admin_write_permission_read_only),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## List Permissions

    Returns a paginated list of permissions with filtering and sorting.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `page`: Page number (default: 1, min: 1)
    - `page_size`: Items per page (default: 10, min: 1, max: 100)
    - `category`: Optional category filter (e.g., admin, products, monitoring)
    - `is_active`: Optional filter by active status (true/false)
    - `search`: Optional search term (searches name and description)
    - `sort_by`: Field to sort by (id, name, category, created_at, updated_at)
    - `sort_order`: Sort direction (asc or desc, default: asc)

    **Returns:**
    - Paginated list of permissions with metadata
    """
    try:
        # Validate sort_by field
        valid_sort_fields = ["id", "name", "category", "created_at", "updated_at"]
        if sort_by not in valid_sort_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort_by field: {sort_by}. Must be one of: {', '.join(valid_sort_fields)}"
            )

        # Validate sort_order
        if sort_order.lower() not in ["asc", "desc"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort_order: {sort_order}. Must be 'asc' or 'desc'"
            )

        result = port.list_permissions(
            page=page,
            page_size=page_size,
            category=category,
            is_active=is_active,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return PermissionsListResponse(
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"],
            permissions=[_dict_to_permission_response(p) for p in result["permissions"]],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing permissions: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list permissions"
        ) from e


@router.get("/rbac/permissions/{permission_id}",
         tags=["Admin"],
         summary="Get Permission by ID",
         description="Get detailed information about a specific permission. Requires admin:write permission.",
         response_model=PermissionResponse)
@require_read_db
async def get_permission(
    permission_id: int,
    current_user: AuthContext = Depends(get_admin_write_permission_read_only),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Get Permission by ID

    Returns detailed information about a specific permission.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `permission_id`: The ID of the permission to retrieve

    **Returns:**
    - Complete permission information
    """
    try:
        perm = port.get_permission_by_id(permission_id)

        if not perm:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission with ID {permission_id} not found"
            )

        return _dict_to_permission_response(perm)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting permission %d: %s", permission_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get permission {permission_id}"
        ) from e


@router.post("/rbac/permissions",
          tags=["Admin"],
          summary="Create Permission",
          description="Create a new permission. Requires admin:write permission.",
          response_model=PermissionResponse,
          status_code=status.HTTP_201_CREATED)
@require_write_db
async def create_permission(
    permission_data: PermissionCreateRequest,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Create Permission

    Creates a new permission with the specified information.

    **Authentication:** Required (Admin only with admin:write permission)

    **Request Body:**
    - `name`: Permission name (required, e.g., "admin:read", "products:write")
    - `description`: Optional human-readable description
    - `category`: Optional category (e.g., "admin", "products", "monitoring")

    **Returns:**
    - Created permission information
    """
    try:
        # Check if permission name already exists
        existing = port.get_permission_by_name(permission_data.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Permission with name '{permission_data.name}' already exists"
            )

        perm = port.create_permission(
            name=permission_data.name,
            description=permission_data.description,
            category=permission_data.category,
        )

        return _dict_to_permission_response(perm)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating permission: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create permission"
        ) from e


@router.put("/rbac/permissions/{permission_id}",
         tags=["Admin"],
         summary="Update Permission",
         description="Update an existing permission. Requires admin:write permission.",
         response_model=PermissionResponse)
@require_write_db
async def update_permission(
    permission_id: int,
    permission_data: PermissionUpdateRequest,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Update Permission

    Updates an existing permission. Only provided fields will be updated.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `permission_id`: The ID of the permission to update

    **Request Body:**
    - All fields are optional - only provided fields will be updated
    - `description`: New description
    - `category`: New category
    - `is_active`: New active status

    **Returns:**
    - Updated permission information
    """
    try:
        updated = port.update_permission(
            permission_id,
            description=permission_data.description,
            category=permission_data.category,
            is_active=permission_data.is_active,
        )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission with ID {permission_id} not found"
            )

        return _dict_to_permission_response(updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating permission %d: %s", permission_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update permission {permission_id}"
        ) from e


@router.delete("/rbac/permissions/{permission_id}",
            tags=["Admin"],
            summary="Delete Permission",
            description="Delete a permission. Requires admin:write permission.",
            status_code=status.HTTP_204_NO_CONTENT)
@require_write_db
async def delete_permission(
    permission_id: int,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Delete Permission

    Permanently deletes a permission. This will also remove all role-permission and user-permission mappings.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `permission_id`: The ID of the permission to delete

    **Returns:**
    - 204 No Content on success
    """
    try:
        success = port.delete_permission(permission_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission with ID {permission_id} not found"
            )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting permission %d: %s", permission_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete permission {permission_id}"
        ) from e


# Roles CRUD Endpoints

@router.get("/rbac/roles",
         tags=["Admin"],
         summary="List Roles",
         description="Get a paginated list of roles with filtering and sorting. Requires admin:write permission.",
         response_model=RolesListResponse)
@require_read_db
async def list_roles(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    is_system: Optional[bool] = Query(None, description="Filter by system role status"),
    search: Optional[str] = Query(None, max_length=100, description="Search by name or description"),
    sort_by: str = Query("name", description="Sort by field: id, name, created_at, updated_at"),
    sort_order: str = Query("asc", description="Sort order: asc or desc"),
    current_user: AuthContext = Depends(get_admin_write_permission_read_only),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## List Roles

    Returns a paginated list of roles with filtering and sorting.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `page`: Page number (default: 1, min: 1)
    - `page_size`: Items per page (default: 10, min: 1, max: 100)
    - `is_active`: Optional filter by active status (true/false)
    - `is_system`: Optional filter by system role status (true/false)
    - `search`: Optional search term (searches name and description)
    - `sort_by`: Field to sort by (id, name, created_at, updated_at)
    - `sort_order`: Sort direction (asc or desc, default: asc)

    **Returns:**
    - Paginated list of roles with metadata
    """
    try:
        # Validate sort_by field
        valid_sort_fields = ["id", "name", "created_at", "updated_at"]
        if sort_by not in valid_sort_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort_by field: {sort_by}. Must be one of: {', '.join(valid_sort_fields)}"
            )

        # Validate sort_order
        if sort_order.lower() not in ["asc", "desc"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort_order: {sort_order}. Must be 'asc' or 'desc'"
            )

        result = port.list_roles(
            page=page,
            page_size=page_size,
            is_active=is_active,
            is_system=is_system,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return RolesListResponse(
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"],
            roles=[_dict_to_role_response(r) for r in result["roles"]],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing roles: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list roles"
        ) from e


@router.get("/rbac/roles/{role_id}",
         tags=["Admin"],
         summary="Get Role by ID",
         description="Get detailed information about a specific role. Requires admin:write permission.",
         response_model=RoleResponse)
@require_read_db
async def get_role(
    role_id: int,
    current_user: AuthContext = Depends(get_admin_write_permission_read_only),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Get Role by ID

    Returns detailed information about a specific role.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `role_id`: The ID of the role to retrieve

    **Returns:**
    - Complete role information
    """
    try:
        role = port.get_role_by_id(role_id)

        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role with ID {role_id} not found"
            )

        return _dict_to_role_response(role)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting role %d: %s", role_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get role {role_id}"
        ) from e


@router.post("/rbac/roles",
          tags=["Admin"],
          summary="Create Role",
          description="Create a new role. Requires admin:write permission.",
          response_model=RoleResponse,
          status_code=status.HTTP_201_CREATED)
@require_write_db
async def create_role(
    role_data: RoleCreateRequest,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Create Role

    Creates a new role.

    **Authentication:** Required (Admin only with admin:write permission)

    **Request Body:**
    - `name`: Role name (required, unique, min: 1, max: 50)
    - `description`: Human-readable description (optional)
    - `is_system`: Whether this is a system role (default: false)

    **Returns:**
    - Created role information
    """
    try:
        # Check if role name already exists
        existing = port.get_role_by_name(role_data.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Role with name '{role_data.name}' already exists"
            )

        role = port.create_role(
            name=role_data.name,
            description=role_data.description,
            is_system=role_data.is_system,
        )

        if not role:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create role"
            )

        return _dict_to_role_response(role)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating role: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create role"
        ) from e


@router.put("/rbac/roles/{role_id}",
         tags=["Admin"],
         summary="Update Role",
         description="Update an existing role. Requires admin:write permission.",
         response_model=RoleResponse)
@require_write_db
async def update_role(
    role_id: int,
    role_data: RoleUpdateRequest,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Update Role

    Updates an existing role. Only provided fields will be updated.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `role_id`: The ID of the role to update

    **Request Body:** (all fields optional)
    - `name`: New role name
    - `description`: New description
    - `is_active`: New active status

    **Returns:**
    - Updated role information
    """
    try:
        # Check if role exists
        existing = port.get_role_by_id(role_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role with ID {role_id} not found"
            )

        updated = port.update_role(
            role_id,
            name=role_data.name,
            description=role_data.description,
            is_active=role_data.is_active,
        )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Role name already exists or update failed"
            )

        return _dict_to_role_response(updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating role %d: %s", role_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update role {role_id}"
        ) from e


@router.delete("/rbac/roles/{role_id}",
            tags=["Admin"],
            summary="Delete Role",
            description="Delete a role (soft delete). System roles cannot be deleted. Requires admin:write permission.",
            status_code=status.HTTP_204_NO_CONTENT)
@require_write_db
async def delete_role(
    role_id: int,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Delete Role

    Soft deletes a role (sets is_active=False). System roles cannot be deleted.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `role_id`: The ID of the role to delete

    **Returns:**
    - 204 No Content on success
    """
    try:
        # Check if role exists
        existing = port.get_role_by_id(role_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role with ID {role_id} not found"
            )

        success = port.delete_role(role_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete system role"
            )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting role %d: %s", role_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete role {role_id}"
        ) from e


# Role-Permission Management Endpoints (Updated to use role_id)

@router.get("/rbac/roles/{role_id}/permissions",
         tags=["Admin"],
         summary="Get Role Permissions by ID",
         description="Get all permissions assigned to a role by role_id. Requires admin:write permission.",
         response_model=RolePermissionsResponse)
@require_read_db
async def get_role_permissions_by_id(
    role_id: int,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Get Role Permissions by ID

    Returns all permissions assigned to a specific role.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `role_id`: Role ID

    **Returns:**
    - List of permissions assigned to the role
    """
    try:
        # Check if role exists
        role = port.get_role_by_id(role_id)
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role with ID {role_id} not found"
            )

        permission_names = port.get_role_permissions_by_id(role_id)

        # Get permission objects
        permissions = []
        for perm_name in permission_names:
            perm = port.get_permission_by_name(perm_name)
            if perm:
                permissions.append(_dict_to_permission_response(perm))

        return RolePermissionsResponse(
            role=role["name"],
            permissions=permissions,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting role permissions for role_id %d: %s", role_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get role permissions for role_id {role_id}"
        ) from e


@router.post("/rbac/roles/{role_id}/permissions",
          tags=["Admin"],
          summary="Assign Permission to Role by ID",
          description="Assign a permission to a role by role_id. Requires admin:write permission.",
          status_code=status.HTTP_201_CREATED)
@require_write_db
async def assign_permission_to_role_by_id(
    role_id: int,
    request: AssignPermissionRequest,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Assign Permission to Role by ID

    Assigns a permission to a role.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `role_id`: Role ID

    **Request Body:**
    - `permission_id`: Permission ID to assign

    **Returns:**
    - 201 Created on success
    """
    try:
        # Check if role exists
        role = port.get_role_by_id(role_id)
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role with ID {role_id} not found"
            )

        # Check if permission exists
        permission = port.get_permission_by_id(request.permission_id)
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission with ID {request.permission_id} not found"
            )

        success = port.assign_permission_to_role_by_id(role_id, request.permission_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Permission {request.permission_id} is already assigned to role {role['name']}"
            )

        return {"message": f"Permission {request.permission_id} assigned to role {role['name']}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error assigning permission to role: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign permission to role"
        ) from e


@router.delete("/rbac/roles/{role_id}/permissions/{permission_id}",
            tags=["Admin"],
            summary="Remove Permission from Role by ID",
            description="Remove a permission from a role by role_id. Requires admin:write permission.",
            status_code=status.HTTP_204_NO_CONTENT)
@require_write_db
async def remove_permission_from_role_by_id(
    role_id: int,
    permission_id: int,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Remove Permission from Role by ID

    Removes a permission from a role.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `role_id`: Role ID
    - `permission_id`: Permission ID to remove

    **Returns:**
    - 204 No Content on success
    """
    try:
        # Check if role exists
        role = port.get_role_by_id(role_id)
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role with ID {role_id} not found"
            )

        # Check if permission exists
        permission = port.get_permission_by_id(permission_id)
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission with ID {permission_id} not found"
            )

        success = port.remove_permission_from_role_by_id(role_id, permission_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission {permission_id} is not assigned to role {role['name']}"
            )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error removing permission from role: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove permission from role"
        ) from e


# User-Permission Management Endpoints

@router.get("/rbac/users/{user_id}/permissions",
         tags=["Admin"],
         summary="Get User Permissions",
         description="Get all direct permissions assigned to a user (not from role). Requires admin:write permission.",
         response_model=UserPermissionsResponse)
@require_read_db
async def get_user_permissions(
    user_id: int,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Get User Permissions

    Returns all direct permissions assigned to a user (overrides role permissions).

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `user_id`: User ID

    **Returns:**
    - List of direct permissions assigned to the user
    """
    try:
        # Check if user exists
        if not port.user_exists(user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )

        permission_names = port.get_user_direct_permissions(user_id)

        # Get permission objects
        permissions = []
        for perm_name in permission_names:
            perm = port.get_permission_by_name(perm_name)
            if perm:
                permissions.append(_dict_to_permission_response(perm))

        return UserPermissionsResponse(
            user_id=user_id,
            permissions=permissions,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting user permissions for %d: %s", user_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user permissions for {user_id}"
        ) from e


@router.post("/rbac/users/{user_id}/permissions",
          tags=["Admin"],
          summary="Assign Permission to User",
          description="Assign a direct permission to a user (overrides role permissions). Requires admin:write permission.",
          status_code=status.HTTP_201_CREATED)
@require_write_db
async def assign_permission_to_user(
    user_id: int,
    request: AssignPermissionRequest,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Assign Permission to User

    Assigns a direct permission to a user (overrides role permissions).

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `user_id`: User ID

    **Request Body:**
    - `permission_id`: Permission ID to assign

    **Returns:**
    - 201 Created on success
    """
    try:
        # Check if user exists
        if not port.user_exists(user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )

        # Check if permission exists
        permission = port.get_permission_by_id(request.permission_id)
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission with ID {request.permission_id} not found"
            )

        success = port.assign_permission_to_user(user_id, request.permission_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Permission {request.permission_id} is already assigned to user {user_id}"
            )

        return {"message": f"Permission {request.permission_id} assigned to user {user_id}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error assigning permission to user: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign permission to user"
        ) from e


@router.delete("/rbac/users/{user_id}/permissions/{permission_id}",
            tags=["Admin"],
            summary="Remove Permission from User",
            description="Remove a direct permission from a user. Requires admin:write permission.",
            status_code=status.HTTP_204_NO_CONTENT)
@require_write_db
async def remove_permission_from_user(
    user_id: int,
    permission_id: int,
    current_user: AuthContext = Depends(get_admin_write_permission),  # noqa: ARG001
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Remove Permission from User

    Removes a direct permission from a user.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `user_id`: User ID
    - `permission_id`: Permission ID to remove

    **Returns:**
    - 204 No Content on success
    """
    try:
        # Check if user exists
        if not port.user_exists(user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )

        # Check if permission exists
        permission = port.get_permission_by_id(permission_id)
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission with ID {permission_id} not found"
            )

        success = port.remove_permission_from_user(user_id, permission_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission {permission_id} is not assigned to user {user_id}"
            )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error removing permission from user: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove permission from user"
        ) from e

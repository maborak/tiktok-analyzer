"""
Admin Users Routes

Routes for managing users (CRUD operations).
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import List, Optional
from datetime import datetime
import logging

from domain.entities.auth_models import AuthContext, UserRole, User
from domain.services.auth_service import AuthService
from ports.auth import UserManagementPort
from utils.database.force_write import require_read_db, require_write_db
from utils.security.rbac import rbac
from ports.rbac import RBACPort
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from routes.auth import get_auth_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Injected by setup_routes() — see routes/main.py
rbac_port: Optional[RBACPort] = None


def _get_rbac_port() -> RBACPort:
    """FastAPI dependency that returns the injected RBACPort."""
    if rbac_port is None:
        raise RuntimeError("RBACPort has not been injected — check setup_routes()")
    return rbac_port


def get_user_management_port(
    auth_service: AuthService = Depends(get_auth_service)
) -> UserManagementPort:
    """Dependency to get user management port"""
    return auth_service.user_management_port


# Pydantic Models for Request/Response

class UserResponse(BaseModel):
    """User response model"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role_id: int  # Foreign key to roles table
    role: str  # Role name (for display)
    is_active: bool
    is_verified: bool
    max_products: int
    api_rate_limit: int
    failed_login_attempts: int
    locked_until: Optional[datetime] = None
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @property
    def full_name(self) -> str:
        """Get user's full name"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        return self.username


class UserCreateRequest(BaseModel):
    """Request model for creating a user"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "johndoe",
                "email": "john.doe@example.com",
                "password": "SecurePassword123!",
                "first_name": "John",
                "last_name": "Doe",
                "role_id": 1,
                "is_active": True,
                "is_verified": False,
                "max_products": 100,
                "api_rate_limit": 1000
            }
        }
    )
    
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    role_id: int = Field(..., ge=1, description="Role ID (foreign key to roles table)")
    is_active: bool = True
    is_verified: bool = False
    max_products: int = Field(default=100, ge=1, description="Maximum products user can monitor")
    api_rate_limit: int = Field(default=1000, ge=1, description="API rate limit per hour")


class UserUpdateRequest(BaseModel):
    """Request model for updating a user"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "johndoe_updated",
                "email": "john.doe.new@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "role_id": 3,
                "is_active": True,
                "is_verified": True,
                "max_products": 200,
                "api_rate_limit": 2000
            }
        }
    )
    
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    role_id: Optional[int] = Field(None, ge=1, description="Role ID (foreign key to roles table)")
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    max_products: Optional[int] = Field(None, ge=1)
    api_rate_limit: Optional[int] = Field(None, ge=1)


class UsersListResponse(BaseModel):
    """Response model for users list"""
    total: int
    page: int
    page_size: int
    total_pages: int
    users: List[UserResponse]


def _user_to_response(user: User) -> UserResponse:
    """Convert domain User to UserResponse"""
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role_id=user.role_id,  # Foreign key to roles table
        role=user.role.value if isinstance(user.role, UserRole) else user.role,  # Role name for display
        is_active=user.is_active,
        is_verified=user.is_verified,
        max_products=user.max_products,
        api_rate_limit=user.api_rate_limit,
        failed_login_attempts=user.failed_login_attempts,
        locked_until=user.locked_until,
        last_login=user.last_login,
        created_at=user.created_at,
        updated_at=user.updated_at
    )


# CRUD Endpoints

@router.get("/users",
         tags=["Admin"],
         summary="List Users",
         description="Get a paginated list of users with filtering and sorting. Requires admin:write permission.",
         response_model=UsersListResponse)
@require_read_db
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    role_id: Optional[int] = Query(None, ge=1, description="Filter by role ID"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    is_verified: Optional[bool] = Query(None, description="Filter by verified status"),
    search: Optional[str] = Query(None, max_length=100, description="Search by username, email, first_name, or last_name"),
    sort_by: str = Query("created_at", description="Sort by field: id, username, email, created_at, updated_at, last_login"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    current_user: AuthContext = Depends(rbac.require_any_read_only(["admin:write"])),
    user_port: UserManagementPort = Depends(get_user_management_port),
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## List Users

    Returns a paginated list of users with filtering and sorting.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `page`: Page number (default: 1, min: 1)
    - `page_size`: Items per page (default: 10, min: 1, max: 100)
    - `role_id`: Optional role ID filter
    - `is_active`: Optional filter by active status (true/false)
    - `is_verified`: Optional filter by verified status (true/false)
    - `search`: Optional search term (searches username, email, first_name, last_name)
    - `sort_by`: Field to sort by (id, username, email, created_at, updated_at, last_login)
    - `sort_order`: Sort direction (asc or desc, default: desc)

    **Returns:**
    - Paginated list of users with metadata
    """
    try:
        # Validate sort_by field
        valid_sort_fields = ["id", "username", "email", "created_at", "updated_at", "last_login"]
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

        # Validate role_id exists in database
        if role_id:
            db_role = port.get_role_by_id(role_id)
            if not db_role:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid role_id: {role_id}. Role not found in database."
                )
        
        # Get users from port with filters and sorting
        result = user_port.list_users(
            page=page, 
            page_size=page_size, 
            role_id=role_id,
            is_active=is_active,
            is_verified=is_verified,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        # Convert to response models
        users = [_user_to_response(user) for user in result["users"]]
        
        return UsersListResponse(
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"],
            users=users
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing users: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list users"
        ) from e


@router.get("/users/{user_id}",
         tags=["Admin"],
         summary="Get User by ID",
         description="Get detailed information about a specific user. Requires admin:write permission.",
         response_model=UserResponse)
@require_read_db
async def get_user(
    user_id: int,
    current_user: AuthContext = Depends(rbac.require("admin:write")),
    user_port: UserManagementPort = Depends(get_user_management_port)
):
    """
    ## Get User by ID 🔍
    
    Returns detailed information about a specific user.
    
    **Authentication:** Required (Admin only with admin:write permission)
    
    **Parameters:**
    - `user_id`: The ID of the user to retrieve
    
    **Returns:**
    - Complete user information
    """
    try:
        user = user_port.get_user_by_id(user_id)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )
        
        return _user_to_response(user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting user %d: %s", user_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user {user_id}"
        ) from e


@router.post("/users",
          tags=["Admin"],
          summary="Create User",
          description="Create a new user account. Requires admin:write permission.",
          response_model=UserResponse,
          status_code=status.HTTP_201_CREATED)
@require_write_db
async def create_user(
    user_data: UserCreateRequest,
    current_user: AuthContext = Depends(rbac.require("admin:write")),
    user_port: UserManagementPort = Depends(get_user_management_port),
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Create User

    Creates a new user account with the specified information.

    **Authentication:** Required (Admin only with admin:write permission)

    **Request Body:**
    - `username`: Optional username (auto-generated from email if not provided)
    - `email`: User's email address (required, must be unique)
    - `password`: User's password (required, min 8 characters)
    - `first_name`: Optional first name
    - `last_name`: Optional last name
    - `role_id`: Role ID (required, foreign key to roles table)
    - `is_active`: Whether user is active (default: true)
    - `is_verified`: Whether email is verified (default: false)
    - `max_products`: Maximum products user can monitor (default: 100)
    - `api_rate_limit`: API rate limit per hour (default: 1000)

    **Returns:**
    - Created user information
    """
    try:
        # Check if email already exists
        existing_user = user_port.get_user_by_email(user_data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User with email {user_data.email} already exists"
            )

        # Check if username already exists (if provided)
        if user_data.username:
            existing_username = user_port.get_user_by_username(user_data.username)
            if existing_username:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with username {user_data.username} already exists"
                )

        # Validate role_id exists in database and get role name
        user_role = UserRole.USER  # Default
        db_role = port.get_role_by_id(user_data.role_id)
        if not db_role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role_id: {user_data.role_id}. Role not found in database."
            )

        # Try to convert to UserRole enum for domain model
        try:
            user_role = UserRole(db_role["name"])
        except ValueError:
            # Role not in enum, default to USER (domain model uses enum)
            user_role = UserRole.USER
        
        # Create domain user object
        user = User(
            id=0,  # Will be set by database
            username=user_data.username or "",  # Empty string will trigger auto-generation
            email=user_data.email,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            role_id=user_data.role_id,  # Pass role_id directly
            role=user_role,
            is_active=user_data.is_active,
            is_verified=user_data.is_verified,
            max_products=user_data.max_products,
            api_rate_limit=user_data.api_rate_limit
        )
        
        # Create user via port
        created_user = user_port.create_user(user, user_data.password)
        
        if not created_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user"
            )
        
        return _user_to_response(created_user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating user: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        ) from e


@router.put("/users/{user_id}",
         tags=["Admin"],
         summary="Update User",
         description="Update an existing user's information. Requires admin:write permission.",
         response_model=UserResponse)
@require_write_db
async def update_user(
    user_id: int,
    user_data: UserUpdateRequest,
    current_user: AuthContext = Depends(rbac.require("admin:write")),
    user_port: UserManagementPort = Depends(get_user_management_port),
    port: RBACPort = Depends(_get_rbac_port),
):
    """
    ## Update User

    Updates an existing user's information. Only provided fields will be updated.

    **Authentication:** Required (Admin only with admin:write permission)

    **Parameters:**
    - `user_id`: The ID of the user to update

    **Request Body:**
    - All fields are optional - only provided fields will be updated
    - `username`: New username (must be unique if changed)
    - `email`: New email address (must be unique if changed)
    - `first_name`: New first name
    - `last_name`: New last name
    - `role_id`: New role ID (foreign key to roles table)
    - `is_active`: New active status
    - `is_verified`: New verification status
    - `max_products`: New max products limit
    - `api_rate_limit`: New API rate limit

    **Returns:**
    - Updated user information
    """
    try:
        # Check if user exists
        existing_user = user_port.get_user_by_id(user_id)
        if not existing_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )
        
        # Check if email is being changed and already exists
        if user_data.email and user_data.email != existing_user.email:
            email_user = user_port.get_user_by_email(user_data.email)
            if email_user and email_user.id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email {user_data.email} already exists"
                )
        
        # Check if username is being changed and already exists
        if user_data.username and user_data.username != existing_user.username:
            username_user = user_port.get_user_by_username(user_data.username)
            if username_user and username_user.id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with username {user_data.username} already exists"
                )
        
        # Build updates dict (only include non-None values)
        updates = {}
        if user_data.username is not None:
            updates["username"] = user_data.username
        if user_data.email is not None:
            updates["email"] = user_data.email
        if user_data.first_name is not None:
            updates["first_name"] = user_data.first_name
        if user_data.last_name is not None:
            updates["last_name"] = user_data.last_name
        if user_data.role_id is not None:
            # Validate role_id exists in database
            db_role = port.get_role_by_id(user_data.role_id)
            if not db_role:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid role_id: {user_data.role_id}. Role not found in database."
                )
            updates["role_id"] = user_data.role_id
        if user_data.is_active is not None:
            updates["is_active"] = user_data.is_active
        if user_data.is_verified is not None:
            updates["is_verified"] = user_data.is_verified
        if user_data.max_products is not None:
            updates["max_products"] = user_data.max_products
        if user_data.api_rate_limit is not None:
            updates["api_rate_limit"] = user_data.api_rate_limit
        
        # If no updates provided, return current user
        if not updates:
            return _user_to_response(existing_user)
        
        # Update user via port
        updated_user = user_port.update_user(user_id, updates)
        
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user"
            )
        
        return _user_to_response(updated_user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating user %d: %s", user_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user {user_id}"
        ) from e


@router.delete("/users/{user_id}",
            tags=["Admin"],
            summary="Delete User",
            description="Delete a user account. Requires admin:write permission. Cannot delete yourself.",
            status_code=status.HTTP_204_NO_CONTENT)
@require_write_db
async def delete_user(
    user_id: int,
    current_user: AuthContext = Depends(rbac.require("admin:write")),
    user_port: UserManagementPort = Depends(get_user_management_port)
):
    """
    ## Delete User 🗑️
    
    Permanently deletes a user account and all associated data.
    
    **Authentication:** Required (Admin only with admin:write permission)
    
    **Parameters:**
    - `user_id`: The ID of the user to delete
    
    **Security:**
    - Cannot delete your own account (prevents self-lockout)
    
    **Returns:**
    - 204 No Content on success
    """
    try:
        # Prevent users from deleting themselves
        if current_user.user.id == user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot delete your own account. Please ask another admin to delete it."
            )
        
        # Check if user exists
        existing_user = user_port.get_user_by_id(user_id)
        if not existing_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )
        
        # Delete user via port
        success = user_port.delete_user(user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user"
            )
        
        return None  # 204 No Content
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting user %d: %s", user_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user {user_id}"
        ) from e


@router.post("/users/{user_id}/login-as",
          tags=["Admin"],
          summary="Login as User (Impersonation)",
          description="Generate a valid login token for a specific user without knowing their password. Requires admin:write permission.",
          response_model=dict)
@require_write_db
async def login_as_user_endpoint(
    user_id: int,
    current_user: AuthContext = Depends(rbac.require("admin:write")),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    ## Login as User (Impersonation) 🕵️
    
    Allows an administrator to log in as another user. 
    Returns valid access/refresh tokens for the target user.
    
    **Authentication:** Required (Admin only with admin:write permission)
    
    **Parameters:**
    - `user_id`: The ID of the user to impersonate
    
    **Returns:**
    - Login response with access_token and refresh_token
    """
    from domain.entities.auth_models import AuthStatus
    
    try:
        # Prevent admins from impersonating themselves (not useful)
        if current_user.user.id == user_id:
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You do not need to impersonate yourself."
            )
            
        # Call service to login as user
        result = auth_service.login_as_user(user_id)
        
        if result.status == AuthStatus.SUCCESS:
            return {
                "access_token": result.access_token,
                "refresh_token": result.refresh_token,
                "token_type": "bearer",
                "expires_in": result.expires_in,
                "user": _user_to_response(result.user)
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error logging in as user %d: %s", user_id, e, exc_info=True)

class LoginAsRequest(BaseModel):
    email: EmailStr

@router.post("/users/login-as",
          tags=["Admin"],
          summary="Login as User by Email (Impersonation)",
          description="Generate a valid login token for a specific user using their email. Requires admin:write permission.",
          response_model=dict)
@require_write_db
async def login_as_user_by_email_endpoint(
    request: LoginAsRequest,
    current_user: AuthContext = Depends(rbac.require("admin:write")),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    ## Login as User by Email (Impersonation) 🕵️
    
    Allows an administrator to log in as another user using their email address.
    Returns valid access/refresh tokens for the target user.
    
    **Authentication:** Required (Admin only with admin:write permission)
    
    **Body:**
    - `email`: The email of the user to impersonate
    
    **Returns:**
    - Login response with access_token and refresh_token
    """
    from domain.entities.auth_models import AuthStatus
    
    try:
        # Prevent admins from impersonating themselves (not useful)
        if current_user.user.email == request.email:
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You do not need to impersonate yourself."
            )
            
        # Call service to login as user
        result = auth_service.login_as_user_by_email(request.email)
        
        if result.status == AuthStatus.SUCCESS:
            return {
                "access_token": result.access_token,
                "refresh_token": result.refresh_token,
                "token_type": "bearer",
                "expires_in": result.expires_in,
                "user": _user_to_response(result.user)
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error logging in as user %s: %s", request.email, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to login as user {request.email}"
        ) from e

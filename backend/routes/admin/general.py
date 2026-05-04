"""
Admin General Routes

Root admin endpoint for access verification.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from datetime import datetime
from typing import Optional

from domain.entities.auth_models import AuthContext, UserRole
from domain.services.auth_service import AuthService
from utils.database.force_write import require_read_db
from routes.auth import get_auth_service

router = APIRouter()

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


async def get_admin_user_dependency(
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

    return auth_context


@router.get("/",
         tags=["Admin"],
         summary="Admin Root",
         description="Admin endpoint - requires admin authentication")
@require_read_db
async def admin_root(
    current_user: AuthContext = Depends(get_admin_user_dependency)
):
    """
    ## Admin Root Endpoint 🔐
    
    This endpoint verifies admin access.
    Only users with admin role can access this endpoint.
    
    **Authentication:** Required (Admin only)
    """
    return {
        "message": "Admin access granted",
        "user": {
            "id": current_user.user.id,
            "username": current_user.user.username,
            "email": current_user.user.email,
            "role": current_user.user.role.value if current_user.user.role else None
        },
        "timestamp": datetime.now().isoformat()
    }

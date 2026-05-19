"""
RBAC Permission Utilities

Reusable FastAPI dependencies for permission-based access control.
Compatible with OAuth2 (Swagger UI) and Bearer token authentication.

Usage:
    from utils.security.rbac import rbac
    
    # Single permission
    current_user: AuthContext = Depends(rbac.require("admin:write"))
    
    # Multiple permissions (AND - all required)
    current_user: AuthContext = Depends(rbac.require(["admin:write", "users:manage"]))
    
    # Multiple permissions (OR - any one is sufficient)
    current_user: AuthContext = Depends(rbac.require_any(["admin:read", "users:read"]))
"""

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from typing import Optional, Union, List
import logging

from domain.entities.auth_models import AuthContext
from domain.services.auth_service import AuthService
from utils.auth_provider import get_auth_service

logger = logging.getLogger(__name__)

# OAuth2 scheme for Swagger UI compatibility
_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/token",
    auto_error=False,
    scopes={
        "read": "Read access",
        "write": "Write access",
        "admin": "Administrative access"
    }
)

# Bearer token for programmatic access
_bearer_security = HTTPBearer(auto_error=False)


class RBACDependency:
    """
    RBAC Permission Dependency Factory
    
    Creates FastAPI dependencies for permission-based access control.
    """
    
    def _get_token(
        self,
        oauth2_token: Optional[str],
        bearer_credentials: Optional[HTTPAuthorizationCredentials]
    ) -> Optional[str]:
        """Extract token from OAuth2 or Bearer credentials"""
        if oauth2_token:
            return oauth2_token
        if bearer_credentials:
            return bearer_credentials.credentials
        return None
    
    def _get_auth_context(
        self,
        token: str,
        auth_service: AuthService
    ) -> AuthContext:
        """Validate token and return auth context"""
        auth_context = auth_service.get_auth_context(token)
        
        if not auth_context:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        return auth_context
    
    def require(self, permissions: Union[str, List[str]]):
        """
        Require permission(s) - AND logic.
        
        If multiple permissions are provided, ALL must be satisfied.
        
        Args:
            permissions: Single permission string or list of permissions
        
        Returns:
            FastAPI dependency that returns AuthContext
        
        Examples:
            # Single permission
            Depends(rbac.require("admin:write"))
            
            # Multiple permissions (user must have ALL)
            Depends(rbac.require(["admin:write", "users:manage"]))
        """
        # Normalize to list
        perm_list = [permissions] if isinstance(permissions, str) else permissions
        
        async def _require_all(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> AuthContext:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Validate token
            auth_context = self._get_auth_context(token, auth_service)
            
            # Check ALL permissions (AND logic)
            missing_permissions = [
                perm for perm in perm_list 
                if not auth_context.has_permission(perm)
            ]
            
            if missing_permissions:
                if len(missing_permissions) == 1:
                    detail = f"Permission required: {missing_permissions[0]}"
                else:
                    detail = f"Permissions required: {', '.join(missing_permissions)}"
                
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=detail
                )
            
            return auth_context
        
        return _require_all
    
    def require_any(self, permissions: Union[str, List[str]]):
        """
        Require any permission - OR logic.
        
        If multiple permissions are provided, at least ONE must be satisfied.
        
        Args:
            permissions: Single permission string or list of permissions
        
        Returns:
            FastAPI dependency that returns AuthContext
        
        Examples:
            # Single permission (same as require)
            Depends(rbac.require_any("admin:read"))
            
            # Multiple permissions (user must have AT LEAST ONE)
            Depends(rbac.require_any(["admin:read", "users:read", "viewer"]))
        """
        # Normalize to list
        perm_list = [permissions] if isinstance(permissions, str) else permissions
        
        async def _require_any(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> AuthContext:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Validate token
            auth_context = self._get_auth_context(token, auth_service)
            
            # Check ANY permission (OR logic)
            has_any = any(
                auth_context.has_permission(perm) 
                for perm in perm_list
            )
            
            if not has_any:
                if len(perm_list) == 1:
                    detail = f"Permission required: {perm_list[0]}"
                else:
                    detail = f"One of these permissions required: {', '.join(perm_list)}"
                
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=detail
                )
            
            return auth_context
        
        return _require_any
    
    def require_read_only(self, permissions: Union[str, List[str]]):
        """
        Require permission(s) - AND logic (read-only mode).
        
        Args:
            permissions: Single permission string or list of permissions
        """
        from utils.database.force_write import consistency_context
        # Normalize to list
        perm_list = [permissions] if isinstance(permissions, str) else permissions
        
        async def _require_all_read_only(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> AuthContext:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Validate token using read replica
            with consistency_context("read"):
                auth_context = self._get_auth_context(token, auth_service)
            
            # Check ALL permissions (AND logic)
            missing_permissions = [
                perm for perm in perm_list 
                if not auth_context.has_permission(perm)
            ]
            
            if missing_permissions:
                if len(missing_permissions) == 1:
                    detail = f"Permission required: {missing_permissions[0]}"
                else:
                    detail = f"Permissions required: {', '.join(missing_permissions)}"
                
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=detail
                )
            
            return auth_context
        
        return _require_all_read_only

    def require_any_read_only(self, permissions: Union[str, List[str]]):
        """
        Require any permission - OR logic (read-only mode).
        
        Args:
            permissions: Single permission string or list of permissions
        """
        from utils.database.force_write import consistency_context
        # Normalize to list
        perm_list = [permissions] if isinstance(permissions, str) else permissions
        
        async def _require_any_read_only(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> AuthContext:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Validate token using read replica
            with consistency_context("read"):
                auth_context = self._get_auth_context(token, auth_service)
            
            # Check ANY permission (OR logic)
            has_any = any(
                auth_context.has_permission(perm) 
                for perm in perm_list
            )
            
            if not has_any:
                if len(perm_list) == 1:
                    detail = f"Permission required: {perm_list[0]}"
                else:
                    detail = f"One of these permissions required: {', '.join(perm_list)}"
                
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=detail
                )
            
            return auth_context
        
        return _require_any_read_only
    
    def path_gated_admin(self, admin_permissions: Union[str, List[str]]):
        """
        Dual-purpose auth dep for handlers that are double-mounted at
        a user-facing prefix AND an admin prefix. Behaviour depends on
        the request path:

          - If `request.url.path.startswith('/admin/')`: require ANY
            permission in `admin_permissions`. Otherwise 403.
          - Otherwise: just require authentication. Handler reads
            `auth_context.has_permission(...)` to decide its own
            ownership-filter behaviour.

        Used by the TikTok dual-mount in routes/main.py:
          read_router @ /tiktok        → non-admin path → any user OK
          read_router @ /admin/tiktok  → admin path → admin only

        Read replica for both code paths (these are GET handlers).
        """
        from utils.database.force_write import consistency_context
        from fastapi import Request

        perm_list = (
            [admin_permissions]
            if isinstance(admin_permissions, str)
            else admin_permissions
        )

        async def _path_gated(
            request: Request,
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service),
        ) -> AuthContext:
            token = self._get_token(oauth2_token, bearer_credentials)
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            with consistency_context("read"):
                auth_context = self._get_auth_context(token, auth_service)
            if request.url.path.startswith("/admin/"):
                if not any(auth_context.has_permission(p) for p in perm_list):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Admin permission required for this path "
                            f"(one of: {', '.join(perm_list)})"
                        ),
                    )
            return auth_context

        return _path_gated

    def authenticated(self):
        """
        Require authentication only (no specific permission).

        Returns:
            FastAPI dependency that returns AuthContext

        Example:
            Depends(rbac.authenticated())
        """
        async def _authenticated(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> AuthContext:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Validate token
            return self._get_auth_context(token, auth_service)
        
        return _authenticated
    
    def authenticated_read_only(self):
        """
        Require authentication (read-only mode).
        
        Uses read replica for database operations to reduce load on master.
        Ideal for high-traffic GET endpoints.
        
        Returns:
            FastAPI dependency that returns AuthContext
        
        Example:
            Depends(rbac.authenticated_read_only())
        """
        from utils.database.force_write import consistency_context
        
        async def _authenticated_read_only(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> AuthContext:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Use read replica for token validation
            with consistency_context("read"):
                return self._get_auth_context(token, auth_service)
        
        return _authenticated_read_only

    
    def public(self):
        """
        Public endpoint - no authentication required.
        
        Use this to explicitly mark an endpoint as public for consistency.
        Always returns True.
        
        Returns:
            FastAPI dependency that returns True
        
        Example:
            @router.get("/health")
            async def health(
                _: bool = Depends(rbac.public())
            ):
                return {"status": "ok"}
        """
        async def _public() -> bool:
            return True
        
        return _public
    
    def optional(self):
        """
        Optional authentication - public endpoint with user context if available.
        
        Returns AuthContext if user is authenticated, None otherwise.
        Never raises an authentication error.
        
        Returns:
            FastAPI dependency that returns Optional[AuthContext]
        
        Example:
            @router.get("/products")
            async def list_products(
                current_user: Optional[AuthContext] = Depends(rbac.optional())
            ):
                if current_user:
                    return {"message": f"Hello, {current_user.user.username}"}
                else:
                    return {"message": "Hello, guest"}
        """
        async def _optional(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> Optional[AuthContext]:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                return None  # No authentication, but that's OK
            
            # Try to validate token (silently fail for public endpoints)
            try:
                auth_context = auth_service.get_auth_context(token)
                return auth_context  # Could be None if token is invalid
            except Exception:  # noqa: BLE001
                return None  # Token validation failed, but that's OK for public
        
        return _optional
    
    def optional_read_only(self):
        """
        Optional authentication (read-only mode).
        """
        from utils.database.force_write import consistency_context
        async def _optional_read_only(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> Optional[AuthContext]:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                return None
            
            # Try to validate token using read replica
            try:
                with consistency_context("read"):
                    auth_context = auth_service.get_auth_context(token)
                return auth_context
            except Exception:  # noqa: BLE001
                return None
        
        return _optional_read_only

    def verified(self):
        """
        Require authentication and verification (is_verified=True).
        
        Returns:
            FastAPI dependency that returns AuthContext
        
        Example:
            Depends(rbac.verified())
        """
        async def _verified(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> AuthContext:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Validate token
            auth_context = self._get_auth_context(token, auth_service)
            
            # Check verification status
            if not auth_context.user.is_verified:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account verification required. Please verify your email address."
                )
            
            return auth_context
        
        return _verified

    def verified_read_only(self):
        """
        Require authentication and verification (read-only mode).
        
        Uses read replica for database operations.
        
        Returns:
            FastAPI dependency that returns AuthContext
        """
        from utils.database.force_write import consistency_context
        
        async def _verified_read_only(
            oauth2_token: Optional[str] = Depends(_oauth2_scheme),
            bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_security),
            auth_service: AuthService = Depends(get_auth_service)
        ) -> AuthContext:
            # Get token
            token = self._get_token(oauth2_token, bearer_credentials)
            
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Use read replica for token validation
            with consistency_context("read"):
                auth_context = self._get_auth_context(token, auth_service)
            
            # Check verification status
            if not auth_context.user.is_verified:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account verification required. Please verify your email address."
                )
            
            return auth_context
        
        return _verified_read_only


# Singleton instance for easy importing
rbac = RBACDependency()


# Convenience aliases
require = rbac.require
require_any = rbac.require_any
authenticated = rbac.authenticated
public = rbac.public
optional = rbac.optional
require_read_only = rbac.require_read_only
require_any_read_only = rbac.require_any_read_only
authenticated_read_only = rbac.authenticated_read_only
authenticated_read_only = rbac.authenticated_read_only
optional_read_only = rbac.optional_read_only
verified = rbac.verified
verified_read_only = rbac.verified_read_only

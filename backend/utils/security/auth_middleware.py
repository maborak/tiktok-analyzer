"""
Authentication Middleware

FastAPI middleware for JWT token validation, rate limiting, and authorization.
"""

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any, List
import time
import logging
from datetime import datetime, timedelta

from domain.entities.auth_models import AuthContext, UserRole
from domain.services.auth_service import AuthService
from config import settings

logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBearer()

# Rate limiting storage (in production, use Redis or similar)
_rate_limit_storage: Dict[str, Dict[str, Any]] = {}

class AuthMiddleware:
    """Authentication middleware for FastAPI"""
    
    def __init__(self, auth_service: AuthService):
        self.auth_service = auth_service
    
    async def get_current_user(
        self,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        request: Request = None
    ) -> AuthContext:
        """Get current authenticated user from JWT token"""
        try:
            token = credentials.credentials
            auth_context = self.auth_service.get_auth_context(token)
            
            if not auth_context:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            
            # Check rate limiting
            if not await self._check_rate_limit(auth_context, request):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded"
                )
            
            # Increment request count
            await self._increment_request_count(auth_context)
            
            return auth_context
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Authentication middleware error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed",
                headers={"WWW-Authenticate": "Bearer"}
            )
    
    async def get_current_user_optional(
        self,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
        request: Request = None
    ) -> Optional[AuthContext]:
        """Get current user (optional - doesn't fail if no token)"""
        try:
            if not credentials:
                return None
            
            token = credentials.credentials
            auth_context = self.auth_service.get_auth_context(token)
            
            if not auth_context:
                return None
            
            # Check rate limiting
            if not await self._check_rate_limit(auth_context, request):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded"
                )
            
            # Increment request count
            await self._increment_request_count(auth_context)
            
            return auth_context
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Optional authentication middleware error: {e}")
            return None
    
    def require_role(self, required_role: UserRole):
        """Dependency to require specific user role"""
        async def _require_role(auth_context: AuthContext = Depends(self.get_current_user)) -> AuthContext:
            if auth_context.user.role != required_role and auth_context.user.role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role {required_role.value} required"
                )
            return auth_context
        return _require_role
    
    def require_permission(self, permission: str):
        """Dependency to require specific permission"""
        async def _require_permission(auth_context: AuthContext = Depends(self.get_current_user)) -> AuthContext:
            if not self.auth_service.validate_permission(auth_context, permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission '{permission}' required"
                )
            return auth_context
        return _require_permission
    
    def require_product_access(self, product_id_param: str = "product_id"):
        """Dependency to require product access"""
        async def _require_product_access(
            request: Request,
            auth_context: AuthContext = Depends(self.get_current_user)
        ) -> AuthContext:
            # Extract product_id from path parameters
            product_id = request.path_params.get(product_id_param)
            if not product_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Product ID not found in request"
                )
            
            if not self.auth_service.validate_product_access(auth_context, product_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access to this product is not allowed"
                )
            
            return auth_context
        return _require_product_access
    
    async def _check_rate_limit(self, auth_context: AuthContext, request: Request) -> bool:
        """Check if user has exceeded rate limit"""
        try:
            # Check if rate limiting is enabled
            if not settings("RATE_LIMIT_ENABLED", True):
                return True  # Rate limiting disabled
            
            # Check for bypass key
            bypass_key = settings("RATE_LIMIT_BYPASS_KEY")
            if bypass_key and request.headers.get("X-Rate-Limit-Bypass") == bypass_key:
                return True  # Bypass rate limiting
            
            # Get rate limit from auth context
            rate_limit = auth_context.user.api_rate_limit
            
            # Create rate limit key
            rate_limit_key = f"rate_limit:{auth_context.user.id}"
            current_time = time.time()
            window_start = current_time - settings("RATE_LIMIT_WINDOW")  # Use configurable window
            
            # Get current rate limit data
            if rate_limit_key not in _rate_limit_storage:
                _rate_limit_storage[rate_limit_key] = {
                    "requests": [],
                    "last_reset": current_time
                }
            
            rate_data = _rate_limit_storage[rate_limit_key]
            
            # Clean old requests
            rate_data["requests"] = [
                req_time for req_time in rate_data["requests"] 
                if req_time > window_start
            ]
            
            # Check if limit exceeded
            if len(rate_data["requests"]) >= rate_limit:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Rate limit check error: {e}")
            return True  # Allow request if rate limiting fails
    
    async def _increment_request_count(self, auth_context: AuthContext) -> None:
        """Increment request count for rate limiting"""
        try:
            rate_limit_key = f"rate_limit:{auth_context.user.id}"
            current_time = time.time()
            
            if rate_limit_key not in _rate_limit_storage:
                _rate_limit_storage[rate_limit_key] = {
                    "requests": [],
                    "last_reset": current_time
                }
            
            rate_data = _rate_limit_storage[rate_limit_key]
            rate_data["requests"].append(current_time)
            
            # Update API key usage if using API key
            if auth_context.api_key:
                self.auth_service.api_key_management_port.update_api_key_usage(auth_context.api_key.id)
                
        except Exception as e:
            logger.error(f"Increment request count error: {e}")

class RateLimitMiddleware:
    """Rate limiting middleware"""
    
    def __init__(self, window_size: int = 3600, max_requests: int = 1000):
        self.window_size = window_size
        self.max_requests = max_requests
        self._storage: Dict[str, List[float]] = {}
    
    async def __call__(self, request: Request, call_next):
        """Process request with rate limiting"""
        try:
            # Check if rate limiting is enabled
            if not settings("RATE_LIMIT_ENABLED", True):
                return await call_next(request)  # Skip rate limiting
            
            # Check for bypass key
            bypass_key = settings("RATE_LIMIT_BYPASS_KEY")
            if bypass_key and request.headers.get("X-Rate-Limit-Bypass") == bypass_key:
                return await call_next(request)  # Skip rate limiting
            
            # Get client identifier
            client_id = self._get_client_id(request)
            
            # Check rate limit
            if not self._check_rate_limit(client_id):
                return HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded"
                )
            
            # Process request
            response = await call_next(request)
            
            # Increment request count
            self._increment_request_count(client_id)
            
            return response
            
        except Exception as e:
            logger.error(f"Rate limit middleware error: {e}")
            return await call_next(request)
    
    def _get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting"""
        # Use IP address as client identifier
        client_ip = request.client.host
        
        # If using authentication, use user ID
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            # Extract user ID from token (simplified)
            return f"user:{client_ip}"
        
        return f"ip:{client_ip}"
    
    def _check_rate_limit(self, client_id: str) -> bool:
        """Check if client has exceeded rate limit"""
        current_time = time.time()
        window_start = current_time - self.window_size
        
        # Get client requests
        if client_id not in self._storage:
            self._storage[client_id] = []
        
        # Clean old requests
        self._storage[client_id] = [
            req_time for req_time in self._storage[client_id]
            if req_time > window_start
        ]
        
        # Check if limit exceeded
        return len(self._storage[client_id]) < self.max_requests
    
    def _increment_request_count(self, client_id: str) -> None:
        """Increment request count for client"""
        current_time = time.time()
        
        if client_id not in self._storage:
            self._storage[client_id] = []
        
        self._storage[client_id].append(current_time)

# Utility functions for authentication

def get_auth_middleware(auth_service: AuthService) -> AuthMiddleware:
    """Get authentication middleware instance"""
    return AuthMiddleware(auth_service)

def get_rate_limit_middleware(window_size: Optional[int] = None, max_requests: Optional[int] = None) -> RateLimitMiddleware:
    """Get rate limiting middleware instance with configurable settings"""
    if window_size is None:
        window_size = settings("RATE_LIMIT_WINDOW")
    if max_requests is None:
        max_requests = settings("RATE_LIMIT_REQUESTS")
    return RateLimitMiddleware(window_size, max_requests)

# Common authentication dependencies

def get_current_user(auth_service: AuthService):
    """Get current user dependency"""
    middleware = AuthMiddleware(auth_service)
    return middleware.get_current_user

def get_current_user_optional(auth_service: AuthService):
    """Get current user dependency (optional)"""
    middleware = AuthMiddleware(auth_service)
    return middleware.get_current_user_optional

def require_admin(auth_service: AuthService):
    """Require admin role dependency"""
    middleware = AuthMiddleware(auth_service)
    return middleware.require_role(UserRole.ADMIN)

def require_moderator(auth_service: AuthService):
    """Require moderator role dependency"""
    middleware = AuthMiddleware(auth_service)
    return middleware.require_role(UserRole.MODERATOR)

def require_permission(permission: str, auth_service: AuthService):
    """Require specific permission dependency"""
    middleware = AuthMiddleware(auth_service)
    return middleware.require_permission(permission)

def require_product_access(auth_service: AuthService, product_id_param: str = "product_id"):
    """Require product access dependency"""
    middleware = AuthMiddleware(auth_service)
    return middleware.require_product_access(product_id_param) 
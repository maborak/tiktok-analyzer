"""
Authentication Domain Models

Domain models for user authentication and authorization.
Follows hexagonal architecture principles with clean domain logic.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from enum import Enum

class UserRole(str, Enum):
    """User role enumeration"""
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"

class AuthStatus(str, Enum):
    """Authentication status enumeration"""
    SUCCESS = "success"
    FAILED = "failed"
    LOCKED = "locked"       # Kept for backward compat; no longer emitted by login
    THROTTLED = "throttled"  # Progressive delay active — treat as generic failure
    EXPIRED = "expired"
    INVALID = "invalid"
    LINK_REQUIRED = "link_required"  # OAuth email matches existing account — password confirmation needed

@dataclass
class User:
    """Domain model for user accounts"""
    id: int
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role_id: Optional[int] = None  # Foreign key to roles table
    role: UserRole = UserRole.USER  # Role enum (for backward compatibility)
    is_active: bool = True
    is_verified: bool = False
    max_products: int = 100
    api_rate_limit: int = 1000
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    has_password: bool = True  # False for OAuth-only users (sentinel password)

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
    
    @property
    def is_throttled(self) -> bool:
        """Check if login attempts are throttled (progressive delay active)"""
        if self.locked_until:
            locked = self.locked_until
            if locked.tzinfo is None:
                locked = locked.replace(tzinfo=timezone.utc)
            if locked > datetime.now(timezone.utc):
                return True
        return False

    @property
    def can_login(self) -> bool:
        """Check if user can attempt login"""
        return self.is_active and not self.is_throttled

    def increment_failed_attempts(self):
        """Increment failed login attempts and apply progressive delay.

        Progressive delay: attempts 1-3 = no delay, 4+ = min(2^(n-3), 300)s.
        The account is NEVER hard-locked.
        """
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 4:
            delay_seconds = min(2 ** (self.failed_login_attempts - 3), 300)
            self.locked_until = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        else:
            self.locked_until = None

    def reset_failed_attempts(self):
        """Reset failed login attempts and clear throttle"""
        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_login = datetime.now(timezone.utc)

@dataclass
class UserSession:
    """Domain model for user sessions"""
    id: int
    user_id: int
    session_token: str
    refresh_token: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    is_active: bool = True
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    @property
    def is_expired(self) -> bool:
        """Check if session is expired"""
        if self.expires_at:
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > expires
        return False

@dataclass
class ApiKey:
    """Domain model for API keys"""
    id: int
    user_id: int
    key_name: str
    key_prefix: str
    permissions: Optional[str] = None
    rate_limit: int = 1000
    is_active: bool = True
    last_used: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    @property
    def is_expired(self) -> bool:
        """Check if API key is expired"""
        if self.expires_at:
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > expires
        return False

@dataclass
class LoginRequest:
    """Login request model"""
    email: str
    password: str
    remember_me: bool = False
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

@dataclass
class LoginResponse:
    """Login response model"""
    status: AuthStatus
    user: Optional[User] = None
    session: Optional[UserSession] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    message: Optional[str] = None
    expires_in: Optional[int] = None
    failed_login_attempts: int = 0
    link_data: Optional[Dict[str, Any]] = None  # OAuth linking data when status=LINK_REQUIRED

@dataclass
class RegisterRequest:
    """User registration request model"""
    email: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

@dataclass
class RegisterResponse:
    """User registration response model"""
    status: AuthStatus
    user: Optional[User] = None
    message: Optional[str] = None
    verification_token: Optional[str] = None  # Token for email verification (should be sent via email)

@dataclass
class PasswordResetRequest:
    """Password reset request model"""
    email: str

@dataclass
class PasswordResetResponse:
    """Password reset response model"""
    status: AuthStatus
    message: Optional[str] = None
    reset_token: Optional[str] = None

@dataclass
class ChangePasswordRequest:
    """Change password request model"""
    current_password: str
    new_password: str

@dataclass
class ChangePasswordResponse:
    """Change password response model"""
    status: AuthStatus
    message: Optional[str] = None

@dataclass
class CreateApiKeyRequest:
    """Create API key request model"""
    key_name: str
    permissions: Optional[str] = None
    rate_limit: Optional[int] = None
    expires_at: Optional[datetime] = None

@dataclass
class CreateApiKeyResponse:
    """Create API key response model"""
    status: AuthStatus
    api_key: Optional[ApiKey] = None
    full_key: Optional[str] = None  # Only returned once
    message: Optional[str] = None

@dataclass
class JWTToken:
    """JWT token model"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600  # 1 hour

@dataclass
class TokenPayload:
    """JWT token payload model"""
    user_id: int
    email: str  # Changed from username to email
    role: str
    exp: datetime
    iat: datetime
    session_id: Optional[int] = None

@dataclass
class AuthContext:
    """Authentication context for request processing"""
    user: User
    session: Optional[UserSession] = None
    api_key: Optional[ApiKey] = None
    permissions: List[str] = None  # List of permission names (e.g., ["admin:read", "products:write"])
    role_permissions: List[str] = None  # Permissions from user's role
    direct_permissions: List[str] = None  # Direct user permissions (overrides)
    
    def has_permission(self, permission: str) -> bool:
        """
        Check if user has specific permission using RBAC system.
        
        Permission checking order:
        1. Direct user permissions (highest priority, overrides role)
        2. Role-based permissions
        3. Legacy permissions list (for backward compatibility)
        
        Note: Admin role does NOT automatically have all permissions.
        Permissions must be explicitly assigned to the admin role.
        """
        # Check direct user permissions (highest priority)
        if self.direct_permissions and permission in self.direct_permissions:
            return True
        
        # Check role-based permissions
        if self.role_permissions and permission in self.role_permissions:
            return True
        
        # Legacy: check permissions list (for backward compatibility)
        if self.permissions and permission in self.permissions:
            return True
        
        return False
    
    def has_any_permission(self, permissions: List[str]) -> bool:
        """Check if user has any of the specified permissions"""
        return any(self.has_permission(perm) for perm in permissions)
    
    def has_all_permissions(self, permissions: List[str]) -> bool:
        """Check if user has all of the specified permissions"""
        return all(self.has_permission(perm) for perm in permissions)
    
    def can_access_product(self, product_id: str) -> bool:
        """Check if user can access specific product"""
        # Admin can access all products
        if self.user.role == UserRole.ADMIN:
            return True
        
        # Check if user has products:read permission
        if self.has_permission("products:read"):
            # Users can only access their own products unless they have products:read:all
            if self.has_permission("products:read:all"):
                return True
            # Ownership check required — deny by default until implemented
            return False
        
        return False 
"""
Authentication Ports (Interfaces)

Defines the interfaces for authentication and authorization services.
Follows hexagonal architecture principles with clear port definitions.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from domain.entities.auth_models import (
    User, UserSession, ApiKey, LoginRequest, LoginResponse,
    RegisterRequest, RegisterResponse, PasswordResetRequest, PasswordResetResponse,
    ChangePasswordRequest, ChangePasswordResponse, CreateApiKeyRequest, CreateApiKeyResponse,
    AuthContext, AuthStatus, UserRole
)

class AuthPort(ABC):
    """Port for authentication operations"""
    
    @abstractmethod
    def authenticate_user(self, request: LoginRequest) -> LoginResponse:
        """Authenticate a user with email/password"""
        pass
    
    @abstractmethod
    def register_user(self, request: RegisterRequest) -> RegisterResponse:
        """Register a new user"""
        pass
    
    @abstractmethod
    def refresh_token(self, refresh_token: str) -> Optional[LoginResponse]:
        """Refresh an access token using refresh token"""
        pass
    
    @abstractmethod
    def logout_user(self, session_token: str) -> bool:
        """Logout a user by invalidating their session"""
        pass
    
    @abstractmethod
    def update_password_hash(self, user_id: int, password_hash: str, salt: str) -> bool:
        """Update user password hash in persistence layer.
        
        This is a pure persistence operation - no business logic.
        The service layer handles password validation and hashing.
        
        Args:
            user_id: User ID
            password_hash: Hashed password
            salt: Password salt
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def request_password_reset(self, request: PasswordResetRequest) -> Optional[Dict[str, Any]]:
        """Request password reset and generate reset token.
        
        Returns:
            Dict with reset_token and expires_in_hours if successful, None otherwise.
            Keys: reset_token, expires_in_hours
        """
        pass
    
    @abstractmethod
    def reset_password(self, token: str, password_hash: str, salt: str) -> Optional[int]:
        """Reset password using reset token.
        
        Pure persistence operation - verifies token and updates password hash.
        Returns user_id if successful, None otherwise.
        """
        pass
    
    @abstractmethod
    def verify_email(self, token: str) -> Optional[int]:
        """Verify user email using verification token. Returns user_id if successful, None otherwise."""
        pass
    
    @abstractmethod
    def create_verification_token(self, email: str) -> Optional[Dict[str, Any]]:
        """Create a new email verification token for an existing user.
        
        Returns:
            Dict with user info and verification_token if successful, None otherwise.
            Keys: user_id, email, username, first_name, last_name, verification_token
        """
        pass

class UserManagementPort(ABC):
    """Port for user management operations"""
    
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        pass
    
    @abstractmethod
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        pass
    
    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        pass
    
    @abstractmethod
    def create_user(self, user: User, password: str) -> Optional[User]:
        """Create a new user"""
        pass
    
    @abstractmethod
    def update_user(self, user_id: int, updates: Dict[str, Any]) -> Optional[User]:
        """Update user information"""
        pass
    
    @abstractmethod
    def delete_user(self, user_id: int) -> bool:
        """Delete a user"""
        pass
    
    @abstractmethod
    def list_users(
        self, 
        page: int = 1, 
        page_size: int = 10, 
        role_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        is_verified: Optional[bool] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> Dict[str, Any]:
        """List users with pagination, filtering, and sorting."""
        pass
    
    @abstractmethod
    def cleanup_unverified_users(self, days: int = 30) -> int:
        """Clean up unverified users created before n days.
        
        Args:
            days: Number of days before today to consider unverified users as expired
            
        Returns:
            Number of deleted users
        """
        pass

class SessionManagementPort(ABC):
    """Port for session management operations"""
    
    @abstractmethod
    def create_session(self, user_id: int, ip_address: Optional[str] = None, 
                      user_agent: Optional[str] = None, remember_me: bool = False) -> Optional[UserSession]:
        """Create a new user session"""
        pass
    
    @abstractmethod
    def get_session_by_token(self, session_token: str) -> Optional[UserSession]:
        """Get session by token"""
        pass
    
    @abstractmethod
    def get_session_by_refresh_token(self, refresh_token: str) -> Optional[UserSession]:
        """Get session by refresh token"""
        pass
        
    @abstractmethod
    def get_session_by_id(self, session_id: int) -> Optional[UserSession]:
        """Get session by ID"""
        pass
    
    @abstractmethod
    def invalidate_session(self, session_token: str) -> bool:
        """Invalidate a session"""
        pass
    
    @abstractmethod
    def invalidate_session_by_id(self, session_id: int) -> bool:
        """Invalidate a session by ID"""
        pass
    
    @abstractmethod
    def invalidate_user_sessions(self, user_id: int, exclude_session_id: Optional[int] = None) -> int:
        """Invalidate all sessions for a user"""
        pass
    
    @abstractmethod
    def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions"""
        pass
    
    @abstractmethod
    def get_user_sessions(self, user_id: int) -> List[UserSession]:
        """Get all active sessions for a user"""
        pass

    @abstractmethod
    def update_session_refresh_token(self, session_id: int, refresh_token_hash: str) -> bool:
        """Update the stored refresh token hash for a session (for single-use rotation)"""
        pass

class ApiKeyManagementPort(ABC):
    """Port for API key management operations"""
    
    @abstractmethod
    def create_api_key(self, user_id: int, request: CreateApiKeyRequest) -> CreateApiKeyResponse:
        """Create a new API key"""
        pass
    
    @abstractmethod
    def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        """Get API key by hash"""
        pass
    
    @abstractmethod
    def get_api_key_by_prefix(self, key_prefix: str) -> Optional[ApiKey]:
        """Get API key by prefix"""
        pass
    
    @abstractmethod
    def list_user_api_keys(self, user_id: int) -> List[ApiKey]:
        """List all API keys for a user"""
        pass
    
    @abstractmethod
    def revoke_api_key(self, key_id: int, user_id: int) -> bool:
        """Revoke an API key"""
        pass
    
    @abstractmethod
    def update_api_key_usage(self, key_id: int) -> bool:
        """Update API key last used timestamp"""
        pass
    
    @abstractmethod
    def cleanup_expired_api_keys(self) -> int:
        """Clean up expired API keys"""
        pass

class AuthorizationPort(ABC):
    """Port for authorization operations"""
    
    @abstractmethod
    def get_auth_context(self, token: str, token_type: str = "bearer", 
                        ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Optional[AuthContext]:
        """Get authentication context from token
        
        Args:
            token: JWT token
            token_type: Type of token (default: "bearer")
            ip_address: Current request IP address for validation (optional)
            user_agent: Current request User-Agent for validation (optional)
        
        Returns:
            AuthContext if valid, None otherwise
        """
        pass
    
    @abstractmethod
    def validate_permission(self, auth_context: AuthContext, permission: str) -> bool:
        """Validate if user has specific permission"""
        pass
    
    @abstractmethod
    def validate_product_access(self, auth_context: AuthContext, product_id: str) -> bool:
        """Validate if user can access specific product"""
        pass
    
    @abstractmethod
    def check_rate_limit(self, auth_context: AuthContext) -> bool:
        """Check if user has exceeded rate limit"""
        pass
    
    @abstractmethod
    def increment_request_count(self, auth_context: AuthContext) -> None:
        """Increment request count for rate limiting"""
        pass

class PasswordHasherPort(ABC):
    """Port for password hashing operations.

    Abstracts the hashing algorithm so domain services never import
    from the database layer.
    """

    @abstractmethod
    def generate_salt(self) -> str:
        """Generate a random salt for password hashing."""
        pass

    @abstractmethod
    def hash_password(self, password: str, salt: str) -> str:
        """Hash a password with the given salt."""
        pass

    @abstractmethod
    def verify_password(self, password: str, salt: str, stored_hash: str) -> bool:
        """Verify a password against a stored hash."""
        pass
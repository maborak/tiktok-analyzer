from ..core.base import Base
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta, timezone
from config import get_table_name

class User(Base):
    """
    SQLAlchemy model for user accounts
    
    Stores user authentication and profile information
    """
    __tablename__ = "users"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # User identification
    # Note: username is auto-generated from email during registration
    # It's required (not nullable) but should never be empty (enforced by CHECK constraint)
    username = Column(String(50), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    
    # Authentication
    password_hash = Column(String(255), nullable=False)
    salt = Column(String(64), nullable=False)  # For password hashing
    
    # Profile information
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_verified = Column(Boolean, default=False, nullable=False, index=True)
    
    # Account settings
    role_id = Column(Integer, ForeignKey(f'{get_table_name("roles")}.id'), nullable=False, index=True)  # Foreign key to roles table
    max_products = Column(Integer, default=100, nullable=False)  # Max products user can monitor
    api_rate_limit = Column(Integer, default=1000, nullable=False)  # Requests per hour
    
    # Security
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True, index=True)
    password_changed_at = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    # Relationships
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    oauth_accounts = relationship("OAuthAccount", back_populates="user", cascade="all, delete-orphan")
    # RBAC relationships
    role_obj = relationship("Role", foreign_keys=[role_id], lazy="joined")  # Role object
    direct_permissions = relationship(
        "Permission",
        secondary="user_permissions",  # Will be resolved at runtime
        back_populates="users"
    )
    
    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}', role='{self.role_name}')>"
    
    def __str__(self):
        return f"User {self.username} ({self.email})"
    
    @property
    def role_name(self) -> str:
        """Get user's role name from role_obj relationship"""
        if self.role_obj:
            return self.role_obj.name
        return "user"  # Default role
    
    @property
    def role(self) -> str:
        """Alias for role_name (backward compatibility)"""
        return self.role_name
    
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
    def throttle_seconds_remaining(self) -> int:
        """Seconds remaining before next login attempt is allowed"""
        if not self.locked_until:
            return 0
        locked = self.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        remaining = (locked - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))

    @property
    def can_login(self) -> bool:
        """Check if user can attempt login"""
        return self.is_active and not self.is_throttled

    def increment_failed_attempts(self):
        """Increment failed login attempts and apply progressive delay.

        Progressive delay formula (per-account):
          Attempts 1-3: no delay
          Attempt 4+:  min(2^(attempts-3), 300) seconds

        The account is NEVER hard-locked. The delay caps at 5 minutes.
        On successful login, everything resets.
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

class UserSession(Base):
    """
    SQLAlchemy model for user sessions
    
    Stores active user sessions for session management
    """
    __tablename__ = "user_sessions"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    # Session information
    session_token = Column(String(255), nullable=False, unique=True, index=True)
    refresh_token = Column(String(255), nullable=False, unique=True, index=True)
    
    # Session metadata
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    user_agent = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Expiration
    expires_at = Column(DateTime, nullable=False, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="sessions")
    
    def __repr__(self):
        return f"<UserSession(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"
    
    def __str__(self):
        return f"Session {self.id} for user {self.user_id}"
    
    @property
    def is_expired(self) -> bool:
        """Check if session is expired"""
        if not self.expires_at:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

class ApiKey(Base):
    """
    SQLAlchemy model for API keys
    
    Stores API keys for programmatic access
    """
    __tablename__ = "api_keys"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    # API key information
    key_name = Column(String(100), nullable=False)  # User-friendly name
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    key_prefix = Column(String(8), nullable=False, index=True)  # First 8 chars for identification
    
    # Permissions
    permissions = Column(String(500), nullable=True)  # JSON string of permissions
    rate_limit = Column(Integer, default=1000, nullable=False)  # Requests per hour
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    last_used = Column(DateTime, nullable=True, index=True)
    
    # Expiration
    expires_at = Column(DateTime, nullable=True, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="api_keys")
    
    def __repr__(self):
        return f"<ApiKey(id={self.id}, key_name='{self.key_name}', user_id={self.user_id})>"
    
    def __str__(self):
        return f"API Key {self.key_name} for user {self.user_id}"
    
    @property
    def is_expired(self) -> bool:
        """Check if API key is expired"""
        if not self.expires_at:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

class EmailVerification(Base):
    """
    SQLAlchemy model for email verification tokens
    
    Stores temporary tokens for email verification functionality
    """
    __tablename__ = "email_verifications"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    # Verification token
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    token_salt = Column(String(255), nullable=False)  # Salt used for token hashing
    token_prefix = Column(String(16), nullable=False, index=True)  # First 16 chars of hash for fast lookup
    
    # Expiration
    expires_at = Column(DateTime, nullable=False, index=True)
    
    # Usage
    used_at = Column(DateTime, nullable=True)
    is_used = Column(Boolean, default=False, nullable=False, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    
    def __repr__(self):
        return f"<EmailVerification(id={self.id}, user_id={self.user_id}, is_used={self.is_used})>"
    
    def __str__(self):
        return f"Email verification for user {self.user_id}"
    
    @property
    def is_expired(self) -> bool:
        """Check if verification token is expired"""
        if not self.expires_at:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

class PasswordReset(Base):
    """
    SQLAlchemy model for password reset tokens
    
    Stores temporary tokens for password reset functionality
    """
    __tablename__ = "password_resets"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    # Reset token
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    token_salt = Column(String(255), nullable=False)  # Salt used for token hashing
    
    # Expiration
    expires_at = Column(DateTime, nullable=False, index=True)
    
    # Usage
    used_at = Column(DateTime, nullable=True)
    is_used = Column(Boolean, default=False, nullable=False, index=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    
    def __repr__(self):
        return f"<PasswordReset(id={self.id}, user_id={self.user_id}, is_used={self.is_used})>"
    
    def __str__(self):
        return f"Password reset for user {self.user_id}"
    
    @property
    def is_expired(self) -> bool:
        """Check if reset token is expired"""
        if not self.expires_at:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires 
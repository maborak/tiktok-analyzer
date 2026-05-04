"""
Authentication Service

Core business logic for authentication and authorization.
Implements the domain logic for user authentication, session management, and authorization.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import jwt as pyjwt
import secrets
import hashlib
import json
import logging

from domain.entities.auth_models import (
    User, UserSession, ApiKey, LoginRequest, LoginResponse,
    RegisterRequest, RegisterResponse, PasswordResetRequest, PasswordResetResponse,
    ChangePasswordRequest, ChangePasswordResponse, CreateApiKeyRequest, CreateApiKeyResponse,
    AuthContext, AuthStatus, UserRole, JWTToken, TokenPayload
)
from ports.auth import (
    AuthPort, UserManagementPort, SessionManagementPort, ApiKeyManagementPort,
    AuthorizationPort, PasswordHasherPort
)

logger = logging.getLogger(__name__)

class AuthService:
    """Core authentication service implementing business logic"""
    
    def __init__(
        self,
        auth_port: AuthPort,
        user_management_port: UserManagementPort,
        session_management_port: SessionManagementPort,
        api_key_management_port: ApiKeyManagementPort,
        authorization_port: AuthorizationPort,
        password_hasher: PasswordHasherPort,
        jwt_secret: str,
        jwt_algorithm: str = "HS256",
        access_token_expiry: int = 3600,  # 1 hour
        refresh_token_expiry: int = 2592000,  # 30 days
        session_expiry: int = 86400,  # 24 hours
        remember_me_expiry: int = 2592000,  # 30 days
    ):
        self.auth_port = auth_port
        self.user_management_port = user_management_port
        self.session_management_port = session_management_port
        self.api_key_management_port = api_key_management_port
        self.authorization_port = authorization_port
        self.password_hasher = password_hasher
        
        # JWT Configuration
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm
        self.access_token_expiry = access_token_expiry
        self.refresh_token_expiry = refresh_token_expiry
        self.session_expiry = session_expiry
        self.remember_me_expiry = remember_me_expiry
    
    # --- User Profile ---

    def get_user_profile(self, user_id: int) -> Optional[User]:
        """Get user profile by ID (domain entity, no DB models)."""
        return self.user_management_port.get_user_by_id(user_id)

    def update_user_profile(self, user_id: int, updates: Dict[str, Any]) -> Optional[User]:
        """
        Update user profile fields.
        Validates uniqueness of username/email before updating.
        """
        if "username" in updates and updates["username"]:
            existing = self.user_management_port.get_user_by_username(updates["username"])
            if existing and existing.id != user_id:
                raise ValueError("Username already taken")
        if "email" in updates and updates["email"]:
            existing = self.user_management_port.get_user_by_email(updates["email"])
            if existing and existing.id != user_id:
                raise ValueError("Email already in use")
        return self.user_management_port.update_user(user_id, updates)

    def delete_user_account(self, user_id: int) -> bool:
        """Delete a user account and associated data."""
        return self.user_management_port.delete_user(user_id)

    def get_failed_login_attempts(self, email: str) -> int:
        """Get the number of failed login attempts for an email. Returns 0 if user not found."""
        user = self.user_management_port.get_user_by_email(email)
        return user.failed_login_attempts if user else 0

    def authenticate_user(self, request: LoginRequest) -> LoginResponse:
        """Authenticate a user with email/password"""
        try:
            # Check if user is OAuth-only before attempting password auth
            # This avoids incrementing failed login attempts for OAuth users
            user = self.user_management_port.get_user_by_email(request.email)
            if user and not user.has_password:
                return LoginResponse(
                    status=AuthStatus.FAILED,
                    message="This account uses Google Sign-In. Please use the Google button to log in.",
                )

            # Use the auth port for authentication
            response = self.auth_port.authenticate_user(request)
            
            if response.status == AuthStatus.SUCCESS and response.user and response.session:
                # Generate JWT tokens
                access_token = self._generate_access_token(response.user, response.session)
                refresh_token = self._generate_refresh_token(response.user, response.session)

                # Store refresh token hash for single-use rotation
                self.session_management_port.update_session_refresh_token(
                    response.session.id, self._hash_token(refresh_token)
                )

                # Fire login event
                try:
                    from ports.hooks import hook_manager
                    from ports.hooks.base_handler import HookEvent, HookEventType
                    hook_manager.fire(HookEvent(
                        event_type=HookEventType.USER_LOGIN,
                        data={"user_id": response.user.id, "email": response.user.email},
                        source="auth_service",
                    ))
                except Exception:
                    pass

                return LoginResponse(
                    status=AuthStatus.SUCCESS,
                    user=response.user,
                    session=response.session,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_in=self.access_token_expiry
                )
            else:
                return response
                
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return LoginResponse(
                status=AuthStatus.FAILED,
                message="Authentication failed"
            )
    
    def register_user(self, request: RegisterRequest) -> RegisterResponse:
        """Register a new user"""
        try:
            # Check if email already exists
            existing_email = self.user_management_port.get_user_by_email(request.email)
            if existing_email:
                if not existing_email.has_password:
                    return RegisterResponse(
                        status=AuthStatus.FAILED,
                        message="This email is already registered with Google Sign-In. Please use the Google button to log in."
                    )
                return RegisterResponse(
                    status=AuthStatus.FAILED,
                    message="Email already exists"
                )
            
            # Validate password strength
            if not self._validate_password_strength(request.password):
                return RegisterResponse(
                    status=AuthStatus.FAILED,
                    message="Password must be at least 8 characters long and contain letters and numbers"
                )
            
            # Create user (username will be auto-generated from email in adapter)
            user = User(
                id=0,  # Will be set by database
                username="",  # Will be auto-generated from email in adapter
                email=request.email,
                first_name=request.first_name,
                last_name=request.last_name,
                role=UserRole.USER,
                is_active=True,
                is_verified=False
            )
            
            try:
                created_user = self.user_management_port.create_user(user, request.password)
                if not created_user:
                    # Check if there's a more detailed error from the adapter
                    from config import CONFIG
                    if CONFIG.get("DEBUG_MODE", False):
                        return RegisterResponse(
                            status=AuthStatus.FAILED,
                            message="Failed to create user (create_user returned None - check logs for details)"
                        )
                    return RegisterResponse(
                        status=AuthStatus.FAILED,
                        message="Failed to create user"
                    )
            except Exception as e:
                # In DEBUG_MODE, preserve the original error message with full details
                from config import CONFIG
                if CONFIG.get("DEBUG_MODE", False):
                    # The error message already contains [ErrorType] from the adapter
                    # Just prepend "Failed to create user: " to it
                    error_msg = f"Failed to create user: {str(e)}"
                    logger.error("User creation failed (DEBUG_MODE): %s", e, exc_info=True)
                    return RegisterResponse(
                        status=AuthStatus.FAILED,
                        message=error_msg
                    )
                # In production, return generic message
                logger.error("User creation failed: %s", e, exc_info=True)
                return RegisterResponse(
                    status=AuthStatus.FAILED,
                    message="Failed to create user"
                )
            
            # Extract verification token if available
            verification_token = getattr(created_user, '_verification_token', None)
            
            # Fire USER_REGISTERED hook (for analytics, logging, etc.)
            try:
                from ports.hooks import hook_manager
                from ports.hooks.base_handler import HookEvent, HookEventType
                
                registered_event = HookEvent(
                    event_type=HookEventType.USER_REGISTERED,
                    data={
                        "user_id": created_user.id,
                        "email": created_user.email,
                        "username": created_user.username or "",
                        "first_name": created_user.first_name or "",
                        "last_name": created_user.last_name or "",
                        "role": created_user.role.value if created_user.role else "user",
                    },
                    source="auth_service"
                )
                hook_manager.fire(registered_event)
                logger.info("User registered hook fired for: %s (id=%s)", created_user.email, created_user.id)
            except Exception as hook_error:
                logger.error("Failed to fire user registered hook: %s", hook_error)
                # Don't fail registration if hook fails
            
            # Fire verification email hook (same as resend-verification)
            if verification_token:
                try:
                    verification_event = HookEvent(
                        event_type=HookEventType.USER_VERIFICATION_REQUESTED,
                        data={
                            "email": created_user.email,
                            "username": created_user.username or "",
                            "first_name": created_user.first_name or "",
                            "last_name": created_user.last_name or "",
                            "verification_token": verification_token,
                            "expires_in_days": 7,
                        },
                        source="auth_service"
                    )
                    hook_manager.fire(verification_event)
                    logger.info("Registration verification email hook fired for: %s", created_user.email)
                except Exception as hook_error:
                    logger.error("Failed to fire registration verification email hook: %s", hook_error)
                    # Don't fail registration if hook fails
            
            # Don't return token in response (security - token sent via email)
            return RegisterResponse(
                status=AuthStatus.SUCCESS,
                user=created_user,
                message="User registered successfully. Please check your email to verify your account.",
                verification_token=None  # Never return token in API response
            )
            
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return RegisterResponse(
                status=AuthStatus.FAILED,
                message="Registration failed"
            )
    
    
    def login_as_user(self, target_user_id: int) -> LoginResponse:
        """Login as another user (Impersonation).
        
        Allows an admin to generate a valid session and tokens for a specific user
        without knowing their password.
        """
        try:
            # Get target user
            user = self.user_management_port.get_user_by_id(target_user_id)
            if not user:
                return LoginResponse(
                    status=AuthStatus.FAILED,
                    message="Target user not found"
                )
            
            # Create a new session for this user
            # We treat this as a fresh login
            session = self.session_management_port.create_session(user.id)
            if not session:
                 return LoginResponse(
                    status=AuthStatus.FAILED,
                    message="Failed to create session"
                )
            
            # Generate tokens
            access_token = self._generate_access_token(user, session)
            refresh_token = self._generate_refresh_token(user, session)

            # Store refresh token hash for single-use rotation
            self.session_management_port.update_session_refresh_token(
                session.id, self._hash_token(refresh_token)
            )

            logger.warning(f"User {user.email} (ID: {user.id}) was impersonated by an admin.")
            
            return LoginResponse(
                status=AuthStatus.SUCCESS,
                user=user,
                session=session,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=self.access_token_expiry
            )
            
        except Exception as e:
            logger.error(f"Login as user error: {e}")
            return LoginResponse(
                status=AuthStatus.FAILED,
                message="Impersonation failed"
            )

    def login_as_user_by_email(self, email: str) -> LoginResponse:
        """Login as another user by email (Impersonation)."""
        try:
            # Get target user by email
            user = self.user_management_port.get_user_by_email(email)
            if not user:
                return LoginResponse(
                    status=AuthStatus.FAILED,
                    message="Target user not found"
                )
            
            # Delegate to ID-based login
            return self.login_as_user(user.id)
            
        except Exception as e:
            logger.error(f"Login as user by email error: {e}")
            return LoginResponse(
                status=AuthStatus.FAILED,
                message="Impersonation failed"
            )

    @staticmethod
    def _hash_token(token: str) -> str:
        """SHA-256 hash of a token for storage comparison"""
        return hashlib.sha256(token.encode()).hexdigest()

    def refresh_token(self, refresh_token: str) -> Optional[LoginResponse]:
        """Refresh an access token using refresh token (single-use rotation)"""
        try:
            # Decode the refresh token
            decoded_token = self._decode_token(refresh_token)
            if not decoded_token:
                return None

            # Security: Reject access tokens used as refresh tokens
            # Refresh tokens must have "type": "refresh" claim
            token_type = decoded_token.get("type")
            if token_type != "refresh":
                logger.warning("Access token attempted to be used as refresh token")
                return None

            user_id = decoded_token.get("user_id")
            session_id = decoded_token.get("session_id")

            if not user_id or not session_id:
                return None

            # Get user
            user = self.user_management_port.get_user_by_id(user_id)
            if not user or not user.is_active:
                return None

            # Get session by ID and validate
            session = self.session_management_port.get_session_by_id(session_id)
            if not session or not session.is_active or session.is_expired:
                logger.warning(f"Attempted to refresh token with inactive or expired session: {session_id}")
                return None

            # Single-use enforcement: verify presented token matches stored hash.
            # If the stored token is a raw JWT (legacy) or empty, skip verification
            # but still rotate going forward.
            presented_hash = self._hash_token(refresh_token)
            stored_token = session.refresh_token or ""
            is_hashed = len(stored_token) == 64 and all(c in "0123456789abcdef" for c in stored_token)

            if is_hashed and stored_token != presented_hash:
                # Replay detected: a previously-used refresh token was presented.
                # Kill the entire session to protect the user.
                logger.warning(f"Refresh token replay detected for session {session_id} — invalidating session")
                self.session_management_port.invalidate_session_by_id(session_id)
                return None

            # Generate new tokens
            access_token = self._generate_access_token(user, session)
            new_refresh_token = self._generate_refresh_token(user, session)

            # Store hash of new refresh token for next rotation check
            self.session_management_port.update_session_refresh_token(
                session_id, self._hash_token(new_refresh_token)
            )

            return LoginResponse(
                status=AuthStatus.SUCCESS,
                user=user,
                session=session,
                access_token=access_token,
                refresh_token=new_refresh_token,
                expires_in=self.access_token_expiry
            )

        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return None
    
    def logout_user(self, session_token: str) -> bool:
        """Logout a user by invalidating their session"""
        try:
            # For JWT-based auth, we might want to blacklist the token instead
            # For now, we'll try to invalidate the session by ID if it's numeric
            try:
                session_id = int(session_token)
                # Invalidate session by ID
                return self.session_management_port.invalidate_session_by_id(session_id)
            except ValueError:
                # Fallback to token-based invalidation
                return self.session_management_port.invalidate_session(session_token)
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return False
    
    def change_password(self, user_id: int, request: ChangePasswordRequest) -> ChangePasswordResponse:
        """Change user password
        
        Business logic layer - handles validation, verification, and orchestration.
        Delegates persistence to the adapter via port.
        """
        try:
            # Get user
            user = self.user_management_port.get_user_by_id(user_id)
            if not user:
                return ChangePasswordResponse(
                    status=AuthStatus.FAILED,
                    message="User not found"
                )
            
            # OAuth-only users cannot change password
            if not user.has_password:
                return ChangePasswordResponse(
                    status=AuthStatus.FAILED,
                    message="Password change is not available for accounts using Google login"
                )

            # Verify current password (business logic)
            if not self._verify_password(request.current_password, user):
                return ChangePasswordResponse(
                    status=AuthStatus.FAILED,
                    message="Current password is incorrect"
                )
            
            # Validate new password strength (business logic)
            if not self._validate_password_strength(request.new_password):
                return ChangePasswordResponse(
                    status=AuthStatus.FAILED,
                    message="New password must be at least 8 characters long and contain letters and numbers"
                )
            
            # Hash new password using injected hasher
            new_salt = self.password_hasher.generate_salt()
            new_password_hash = self.password_hasher.hash_password(request.new_password, new_salt)
            
            # Persist password hash (delegate to adapter)
            success = self.auth_port.update_password_hash(user_id, new_password_hash, new_salt)
            if success:
                # Invalidate all sessions (security business logic)
                self.session_management_port.invalidate_user_sessions(user_id)
                
                return ChangePasswordResponse(
                    status=AuthStatus.SUCCESS,
                    message="Password changed successfully"
                )
            else:
                return ChangePasswordResponse(
                    status=AuthStatus.FAILED,
                    message="Failed to change password"
                )
                
        except Exception as e:
            logger.error(f"Change password error: {e}")
            return ChangePasswordResponse(
                status=AuthStatus.FAILED,
                message="Failed to change password"
            )
    
    def request_password_reset(self, request: PasswordResetRequest, template_set: Optional[str] = None) -> PasswordResetResponse:
        """Request password reset
        
        Generates reset token and fires hook event for email delivery.
        
        Args:
            request: Password reset request with user email
            template_set: Optional template set override (e.g., 'tech-stripe', 'enterprise-dark')
        """
        try:
            # Get user by email
            user = self.user_management_port.get_user_by_email(request.email)
            if not user:
                # Don't reveal if email exists or not (security best practice)
                return PasswordResetResponse(
                    status=AuthStatus.SUCCESS,
                    message="If the email exists, a reset link has been sent"
                )

            # OAuth-only users have no password to reset — return same generic message
            # to avoid leaking whether an email uses OAuth
            if not user.has_password:
                return PasswordResetResponse(
                    status=AuthStatus.SUCCESS,
                    message="If the email exists, a reset link has been sent"
                )

            # Create password reset request (generates token internally)
            result = self.auth_port.request_password_reset(request)
            
            if result and result.get("reset_token"):
                reset_token = result["reset_token"]
                expires_in_hours = result.get("expires_in_hours", 24)
                
                # Fire hook event for email handler to send the email
                try:
                    from ports.hooks import hook_manager
                    from ports.hooks.base_handler import HookEvent, HookEventType
                    
                    event_data = {
                        "email": user.email,
                        "username": user.username or "",
                        "first_name": user.first_name or "",
                        "last_name": user.last_name or "",
                        "reset_token": reset_token,
                        "expires_in_hours": expires_in_hours,
                    }
                    
                    # Add template_set override if provided
                    if template_set:
                        event_data["template_set"] = template_set
                    
                    event = HookEvent(
                        event_type=HookEventType.USER_PASSWORD_RESET_REQUESTED,
                        data=event_data,
                        source="auth_service"
                    )
                    hook_manager.fire(event)
                    logger.info("Password reset email hook fired for: %s (template_set=%s)", user.email, template_set or "default")
                except Exception as hook_error:
                    logger.error("Failed to fire password reset email hook: %s", hook_error)
                    # Don't fail the request if hook fails
                
                # Always return success (don't reveal if email exists)
                return PasswordResetResponse(
                    status=AuthStatus.SUCCESS,
                    message="If the email exists, a reset link has been sent"
                )
            else:
                # Generic failure message
                return PasswordResetResponse(
                    status=AuthStatus.SUCCESS,
                    message="If the email exists, a reset link has been sent"
                )
                
        except Exception as e:
            logger.error(f"Password reset request error: {e}")
            # Always return success to prevent email enumeration
            return PasswordResetResponse(
                status=AuthStatus.SUCCESS,
                message="If the email exists, a reset link has been sent"
            )
    
    def reset_password(self, token: str, new_password: str) -> bool:
        """Reset password using reset token.
        
        Business logic:
        - Validates password strength
        - Hashes password with new salt
        - Verifies reset token and updates password
        - Invalidates all user sessions (security)
        """
        try:
            # Validate new password strength
            if not self._validate_password_strength(new_password):
                logger.warning("Password reset failed: weak password")
                return False
            
            # Generate new salt and hash password using injected hasher
            new_salt = self.password_hasher.generate_salt()
            new_password_hash = self.password_hasher.hash_password(new_password, new_salt)
            
            # Call persistence layer to verify token and update password
            user_id = self.auth_port.reset_password(token, new_password_hash, new_salt)
            
            if not user_id:
                logger.warning("Password reset failed: invalid or expired token")
                return False
            
            # Invalidate all user sessions (security - force re-login after password reset)
            try:
                self.session_management_port.invalidate_user_sessions(user_id)
                logger.info("All sessions invalidated for user_id=%s after password reset", user_id)
            except Exception as session_error:
                logger.error("Failed to invalidate sessions after password reset: %s", session_error)
                # Don't fail password reset if session invalidation fails
            
            logger.info("Password reset successful for user_id=%s", user_id)
            return True
            
        except Exception as e:
            logger.error(f"Password reset error: {e}", exc_info=True)
            return False
    
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
        try:
            return self.authorization_port.get_auth_context(token, token_type, ip_address, user_agent)
        except Exception as e:
            logger.error(f"Get auth context error: {e}")
            return None
    
    def validate_permission(self, auth_context: AuthContext, permission: str) -> bool:
        """Validate if user has specific permission"""
        try:
            return self.authorization_port.validate_permission(auth_context, permission)
        except Exception as e:
            logger.error(f"Permission validation error: {e}")
            return False
    
    def validate_product_access(self, auth_context: AuthContext, product_id: str) -> bool:
        """Validate if user can access specific product"""
        try:
            return self.authorization_port.validate_product_access(auth_context, product_id)
        except Exception as e:
            logger.error(f"Product access validation error: {e}")
            return False
    
    def create_api_key(self, user_id: int, request: CreateApiKeyRequest) -> CreateApiKeyResponse:
        """Create a new API key"""
        try:
            return self.api_key_management_port.create_api_key(user_id, request)
        except Exception as e:
            logger.error(f"Create API key error: {e}")
            return CreateApiKeyResponse(
                status=AuthStatus.FAILED,
                message="Failed to create API key"
            )
    
    def verify_email(self, token: str) -> Optional[int]:
        """Verify user email using verification token. Returns user_id if successful, None otherwise."""
        try:
            return self.auth_port.verify_email(token)
        except Exception as e:
            logger.error(f"Email verification error: {e}")
            return None
    
    def request_verification_email(self, email: str, template_set: Optional[str] = None) -> bool:
        """Request a new verification email for a user.
        
        Creates a new verification token and fires the USER_VERIFICATION_REQUESTED hook.
        
        Note: This should only be called for authenticated users requesting
        verification for their own email address.
        
        Args:
            email: User email address
            template_set: Optional template set override (e.g., 'tech-stripe', 'enterprise-dark')
        
        Returns:
            True if verification email was sent, False otherwise.
        """
        try:
            # Create new verification token
            result = self.auth_port.create_verification_token(email)
            
            if not result:
                logger.warning("Could not create verification token for: %s", email)
                return False
            
            # Fire hook event for email handler to send the email
            try:
                from ports.hooks import hook_manager
                from ports.hooks.base_handler import HookEvent, HookEventType
                
                event_data = {
                    "email": result["email"],
                    "username": result.get("username", ""),
                    "first_name": result.get("first_name", ""),
                    "last_name": result.get("last_name", ""),
                    "verification_token": result["verification_token"],
                    "expires_in_days": 7,
                }
                
                # Add template_set override if provided
                if template_set:
                    event_data["template_set"] = template_set
                
                event = HookEvent(
                    event_type=HookEventType.USER_VERIFICATION_REQUESTED,
                    data=event_data,
                    source="auth_service"
                )
                hook_manager.fire(event)
                logger.info("Verification email hook fired for: %s (template_set=%s)", email, template_set or "default")
                return True
                
            except Exception as hook_error:
                logger.error("Failed to fire verification email hook: %s", hook_error)
                return False
            
        except Exception as e:
            logger.error(f"Request verification email error: {e}")
            return False
    
    # Private helper methods
    
    def _verify_password(self, password: str, user: User) -> bool:
        """Verify password against user's stored hash"""
        try:
            # Get the actual user from the database to verify password
            db_user = self.user_management_port.get_user_by_id(user.id)
            if not db_user:
                return False
            
            # Use the auth port to verify password by attempting authentication
            # This is the proper way to verify passwords in the service layer
            from domain.entities.auth_models import LoginRequest
            login_request = LoginRequest(
                email=db_user.email,
                password=password,
                remember_me=False
            )
            
            # Use the auth port to verify password
            login_response = self.auth_port.authenticate_user(login_request)
            return login_response is not None and login_response.status == AuthStatus.SUCCESS
            
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False
    
    def _validate_password_strength(self, password: str) -> bool:
        """Validate password strength"""
        if len(password) < 8:
            return False
        
        has_letter = any(c.isalpha() for c in password)
        has_digit = any(c.isdigit() for c in password)
        
        return has_letter and has_digit
    
    def _generate_access_token(self, user: User, session: UserSession) -> str:
        """Generate JWT access token"""
        payload = TokenPayload(
            user_id=user.id,
            email=user.email,  # Changed from username to email
            role=user.role.value,
            exp=datetime.now(timezone.utc) + timedelta(seconds=self.access_token_expiry),
            iat=datetime.now(timezone.utc),
            session_id=session.id
        )
        
        return pyjwt.encode(
            {
                "user_id": payload.user_id,
                "email": payload.email,
                "role": payload.role,
                "exp": payload.exp,
                "iat": payload.iat,
                "session_id": payload.session_id,
                "type": "access"
            },
            self.jwt_secret,
            algorithm=self.jwt_algorithm
        )
    
    def _generate_refresh_token(self, user: User, session: UserSession) -> str:
        """Generate JWT refresh token"""
        payload = TokenPayload(
            user_id=user.id,
            email=user.email,  # Changed from username to email
            role=user.role.value,
            exp=datetime.now(timezone.utc) + timedelta(seconds=self.refresh_token_expiry),
            iat=datetime.now(timezone.utc),
            session_id=session.id
        )
        
        return pyjwt.encode(
            {
                "user_id": payload.user_id,
                "email": payload.email,  # Changed from username to email
                "role": payload.role,
                "exp": payload.exp,
                "iat": payload.iat,
                "session_id": payload.session_id,
                "type": "refresh"
            },
            self.jwt_secret,
            algorithm=self.jwt_algorithm
        )
    
    def _decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Decode JWT token"""
        try:
            return pyjwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
        except pyjwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except pyjwt.InvalidTokenError:
            logger.warning("Invalid token")
            return None
        except Exception as e:
            logger.error(f"Token decode error: {e}")
            return None 
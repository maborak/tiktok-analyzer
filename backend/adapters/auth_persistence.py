"""
Authentication Persistence Adapter

Database adapter for authentication and user management operations.
Implements the authentication ports for database persistence.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func, and_, or_, asc
import hashlib
import json
import logging
import threading
import time
import jwt
import re
import uuid

from ports.auth import (
    AuthPort, UserManagementPort, SessionManagementPort, ApiKeyManagementPort,
    AuthorizationPort
)
from domain.entities.auth_models import (
    User, UserSession, ApiKey, LoginRequest, LoginResponse,
    RegisterRequest, RegisterResponse, PasswordResetRequest, PasswordResetResponse,
    ChangePasswordRequest, ChangePasswordResponse, CreateApiKeyRequest, CreateApiKeyResponse,
    AuthContext, AuthStatus, UserRole
)
from database import (
    User as UserModel, UserSession as UserSessionModel, ApiKey as ApiKeyModel,
    PasswordReset as PasswordResetModel,
    EmailVerification as EmailVerificationModel,
    CreditLedgerModel, PaymentTransactionModel, InvoiceModel,
)
from database.auth.oauth_models import OAuthAccount as OAuthAccountModel
from database.auth.utils import (
    generate_salt, hash_password, verify_password,
    generate_session_token, generate_api_key, generate_reset_token,
    generate_urlsafe_token
)
from utils.database.database_session import get_db_session
from utils.database.resilience import retry_db_operation

logger = logging.getLogger(__name__)


def _check_has_password(user_model) -> bool:
    """Check if a user has a real password (not an OAuth-only sentinel).

    Handles both new OAuth users (literal "!OAUTH_ONLY") and legacy OAuth users
    whose sentinel was hashed. Legacy users are detected by having oauth_accounts linked.
    """
    # New format: literal sentinel stored directly
    if user_model.password_hash == "!OAUTH_ONLY" or user_model.salt == "!OAUTH_ONLY":
        return False
    # Legacy format: sentinel was hashed, but user has OAuth accounts linked
    try:
        if hasattr(user_model, 'oauth_accounts') and user_model.oauth_accounts:
            # User has OAuth accounts — check if the password was the hashed sentinel
            # by verifying "!OAUTH_ONLY" against the stored hash
            if verify_password("!OAUTH_ONLY", str(user_model.salt), str(user_model.password_hash)):
                return False
    except Exception:
        pass
    return True


class AuthPersistenceAdapter(AuthPort, UserManagementPort, SessionManagementPort,
                           ApiKeyManagementPort, AuthorizationPort):
    """Database adapter for authentication operations"""

    # Token-keyed AuthContext cache. `get_auth_context` is hit on every
    # authenticated request — 3 calls on the /admin/tiktok cold mount,
    # 1 per 30 s poll cycle, plus every other admin route call. Each
    # call previously paid 3–4 DB round-trips (session lookup + user
    # lookup + RBAC role perms + RBAC direct perms). At ~30 ms total
    # per request on a remote DB, that's a measurable share of the
    # admin-tab perf budget that adds no security value once we've
    # already validated the same token a few seconds ago.
    #
    # Cache shape: `key → (expires_at, AuthContext)`. Key is
    # SHA-256(token | ip | ua) so an IP / UA change forces a fresh
    # full validation (the underlying DB check would reject anyway,
    # but a different cache slot avoids racing against a stale entry).
    # TTL is short (30 s) so a session revoked through `/auth/logout`
    # disappears within one poll cycle even without explicit busting.
    _auth_context_cache: dict[str, tuple[float, "AuthContext"]] = {}
    _auth_context_lock = threading.Lock()
    _AUTH_CONTEXT_TTL_S = 30.0

    def __init__(self, jwt_secret: str):
        self.jwt_secret = jwt_secret

    @classmethod
    def _auth_cache_key(
        cls,
        token: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> str:
        h = hashlib.sha256()
        h.update(token.encode("utf-8"))
        h.update(b"|")
        h.update((ip_address or "").encode("utf-8"))
        h.update(b"|")
        h.update((user_agent or "").encode("utf-8"))
        return h.hexdigest()

    @classmethod
    def _auth_cache_get(cls, key: str) -> Optional["AuthContext"]:
        with cls._auth_context_lock:
            hit = cls._auth_context_cache.get(key)
            if hit is None:
                return None
            expires_at, ctx = hit
            if time.monotonic() >= expires_at:
                # Lazy eviction. Keeps the cache size bounded by the
                # set of live tokens × IP/UA combos rather than letting
                # expired entries linger forever.
                cls._auth_context_cache.pop(key, None)
                return None
            return ctx

    @classmethod
    def _auth_cache_put(cls, key: str, ctx: "AuthContext") -> None:
        expires_at = time.monotonic() + cls._AUTH_CONTEXT_TTL_S
        with cls._auth_context_lock:
            cls._auth_context_cache[key] = (expires_at, ctx)
            # Cheap bound: when the cache grows past a soft limit,
            # drop the oldest half by expiry. Real eviction strategy
            # for an LRU would need an OrderedDict; this is good
            # enough at our scale (tens of admins × handful of
            # IP/UA combos = under 100 entries steady-state).
            if len(cls._auth_context_cache) > 1024:
                items = sorted(
                    cls._auth_context_cache.items(),
                    key=lambda kv: kv[1][0],
                )
                for k, _ in items[: len(items) // 2]:
                    cls._auth_context_cache.pop(k, None)

    # No explicit invalidate helper. The 30 s TTL ensures a session
    # revoked via /auth/logout disappears from the cache within one
    # poll cycle. If we ever need stricter logout semantics we'd
    # maintain a `session_id → set[cache_key]` reverse index — for
    # now the TTL bound is acceptable.
    
    # AuthPort implementations
    
    @retry_db_operation()
    def authenticate_user(self, request: LoginRequest) -> LoginResponse:
        """Authenticate a user with email/password"""
        try:
            with get_db_session() as session:
                # Get user by email
                user_model = session.query(UserModel).filter(
                    UserModel.email == request.email
                ).first()
                
                if not user_model:
                    return LoginResponse(
                        status=AuthStatus.FAILED,
                        message="Invalid email or password"
                    )
                
                # Convert to domain model
                user = self._user_model_to_domain(user_model)
                
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

                # Check if account is active
                if not user_model.is_active:
                    return LoginResponse(
                        status=AuthStatus.FAILED,
                        message="Invalid email or password",
                        failed_login_attempts=user_model.failed_login_attempts,
                    )

                # Check progressive delay throttle — return generic error
                # (same message as wrong password to prevent enumeration)
                if user_model.locked_until and user_model.locked_until > now_utc:
                    return LoginResponse(
                        status=AuthStatus.FAILED,
                        message="Invalid email or password",
                        failed_login_attempts=user_model.failed_login_attempts,
                    )

                # Check if this is an OAuth-only account (no password set)
                if not _check_has_password(user_model):
                    # Get the OAuth providers linked to this account
                    from database.auth.oauth_models import OAuthAccount as OAuthAccountModel
                    oauth_accounts = session.query(OAuthAccountModel).filter(
                        OAuthAccountModel.user_id == user_model.id
                    ).all()
                    providers = [a.provider for a in oauth_accounts] if oauth_accounts else ["OAuth"]
                    return LoginResponse(
                        status=AuthStatus.FAILED,
                        message=f"OAUTH_ONLY_ACCOUNT:{','.join(providers)}",
                        failed_login_attempts=user_model.failed_login_attempts,
                    )

                # Verify password
                if not verify_password(request.password, str(user_model.salt), str(user_model.password_hash)):
                    from config import CONFIG
                    lockout_threshold = CONFIG.get("ACCOUNT_LOCKOUT_THRESHOLD", 10)
                    lockout_duration = CONFIG.get("ACCOUNT_LOCKOUT_DURATION", 300)

                    user_model.failed_login_attempts += 1
                    if user_model.failed_login_attempts >= lockout_threshold:
                        user_model.locked_until = datetime.now(timezone.utc) + timedelta(seconds=lockout_duration)
                    else:
                        user_model.locked_until = None
                    session.commit()

                    return LoginResponse(
                        status=AuthStatus.FAILED,
                        message="Invalid email or password",
                        failed_login_attempts=user_model.failed_login_attempts,
                    )
                
                # Reset failed attempts on successful login
                user_model.failed_login_attempts = 0
                user_model.locked_until = None
                user_model.last_login = datetime.now(timezone.utc)
                session.commit()
                
                # Create session
                session_model = self._create_session_model(session, user_model.id, request)
                if not session_model:
                    return LoginResponse(
                        status=AuthStatus.FAILED,
                        message="Failed to create session"
                    )
                
                # Convert to domain models
                user = self._user_model_to_domain(user_model)
                session_domain = self._session_model_to_domain(session_model)
                
                return LoginResponse(
                    status=AuthStatus.SUCCESS,
                    user=user,
                    session=session_domain
                )
                
        except Exception as e:
            # Enhanced error logging when DEBUG_MODE is enabled
            from config import CONFIG
            debug_mode = CONFIG.get("DEBUG_MODE", False)
            
            if debug_mode:
                import traceback
                tb_str = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                logger.error(
                    "Authentication error (DEBUG_MODE enabled): %s\nEmail: %s\nTraceback:\n%s",
                    e, request.email, tb_str,
                    exc_info=True
                )
            else:
                logger.error(f"Authentication error: {e}", exc_info=True)
            
            return LoginResponse(
                status=AuthStatus.FAILED,
                message="Authentication failed"
            )
    
    @retry_db_operation()
    def register_user(self, request: RegisterRequest) -> RegisterResponse:
        """Register a new user"""
        try:
            with get_db_session() as session:
                # Check if email already exists
                existing_email = session.query(UserModel).filter(
                    UserModel.email == request.email
                ).first()
                
                if existing_email:
                    return RegisterResponse(
                        status=AuthStatus.FAILED,
                        message="Email already exists"
                    )
                
                # Auto-generate username from email (part before @)
                # If username already exists, append a number
                # CRITICAL: Ensure username is never empty to avoid unique constraint violations
                
                # Extract base username from email
                if '@' in request.email and request.email.split('@')[0]:
                    base_username = request.email.split('@')[0].strip()
                else:
                    # Fallback if email doesn't have @ or part before @ is empty
                    # Use email with sanitization, or generate UUID-based username
                    if request.email and request.email.strip():
                        base_username = request.email.replace('@', '_').replace('.', '_')[:20]
                        base_username = base_username.strip()
                    else:
                        # Last resort: generate UUID-based username
                        base_username = f"user_{uuid.uuid4().hex[:8]}"
                
                # Ensure base_username is not empty after all processing
                if not base_username or not base_username.strip():
                    # Final fallback: generate UUID-based username
                    base_username = f"user_{uuid.uuid4().hex[:8]}"
                
                # Clean and validate username
                base_username = base_username.strip()
                # Remove any invalid characters (keep alphanumeric, underscore, hyphen)
                base_username = re.sub(r'[^a-zA-Z0-9_-]', '_', base_username)
                
                # Final check: ensure it's not empty after cleaning
                if not base_username:
                    base_username = f"user_{uuid.uuid4().hex[:8]}"
                
                username = base_username
                counter = 1
                max_attempts = 100  # Prevent infinite loop
                while session.query(UserModel).filter(UserModel.username == username).first():
                    username = f"{base_username}{counter}"
                    counter += 1
                    if counter > max_attempts:
                        # Fallback to UUID-based username if too many conflicts
                        username = f"user_{uuid.uuid4().hex[:8]}"
                        break
                
                # CRITICAL: Final validation - username must never be empty
                if not username or not username.strip():
                    logger.error(
                        "CRITICAL: Username is empty after all processing! "
                        "Email: %s, base_username: %s, username: %s",
                        request.email, base_username, username
                    )
                    # Force UUID-based username as last resort
                    username = f"user_{uuid.uuid4().hex[:8]}"
                    logger.warning("Generated UUID-based username as fallback: %s", username)
                
                # Ensure username is not empty one more time (defensive programming)
                username = username.strip()
                if not username:
                    username = f"user_{uuid.uuid4().hex[:8]}"
                
                # Create user model
                salt = generate_salt()
                password_hash = hash_password(request.password, salt)
                
                # Log username before creation for debugging
                logger.debug("Creating user with username: %s, email: %s", username, request.email)
                
                # CRITICAL: One final check before creating UserModel
                # This should never happen, but if it does, we'll catch it here
                if not username or username.strip() == '':
                    error_msg = (
                        f"CRITICAL BUG: Username is empty before UserModel creation! "
                        f"Email: {request.email}, username: {repr(username)}, "
                        f"base_username: {repr(base_username)}"
                    )
                    logger.error(error_msg)
                    # Force UUID-based username
                    username = f"user_{uuid.uuid4().hex[:8]}"
                    logger.warning("Forced UUID-based username: %s", username)
                
                # Ensure username is not None or empty (defensive)
                username = str(username).strip() if username else f"user_{uuid.uuid4().hex[:8]}"
                
                user_model = UserModel(
                    username=username,  # Auto-generated from email
                    email=request.email,
                    first_name=request.first_name,
                    last_name=request.last_name,
                    password_hash=password_hash,
                    salt=salt,
                    role=UserRole.USER.value,
                    is_active=True,
                    is_verified=False
                )
                
                session.add(user_model)
                session.flush()  # Flush to get the ID without committing
                session.refresh(user_model)  # Refresh to get all database-generated fields
                session.commit()  # Commit after refresh
                
                # Convert to domain model
                user = self._user_model_to_domain(user_model)
                
                return RegisterResponse(
                    status=AuthStatus.SUCCESS,
                    user=user,
                    message="User registered successfully"
                )
                
        except Exception as e:
            # Enhanced error logging when DEBUG_MODE is enabled
            from config import CONFIG
            debug_mode = CONFIG.get("DEBUG_MODE", False)
            
            if debug_mode:
                import traceback
                tb_str = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                logger.error(
                    "Registration error (DEBUG_MODE enabled): %s\nEmail: %s\nTraceback:\n%s",
                    e, request.email, tb_str,
                    exc_info=True
                )
            else:
                logger.error(f"Registration error: {e}", exc_info=True)
            
            return RegisterResponse(
                status=AuthStatus.FAILED,
                message="Registration failed"
            )
    
    @retry_db_operation()
    def refresh_token(self, refresh_token: str) -> Optional[LoginResponse]:
        """Refresh an access token using refresh token"""
        try:
            with get_db_session() as session:
                # Get session by refresh token
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.refresh_token == refresh_token,
                    UserSessionModel.is_active == True
                ).first()
                
                if not session_model or session_model.is_expired:
                    return None
                
                # Get user
                user_model = session.query(UserModel).filter(
                    UserModel.id == session_model.user_id
                ).first()
                
                if not user_model or not user_model.can_login:
                    return None
                
                # Convert to domain models
                user = self._user_model_to_domain(user_model)
                session_domain = self._session_model_to_domain(session_model)
                
                return LoginResponse(
                    status=AuthStatus.SUCCESS,
                    user=user,
                    session=session_domain
                )
                
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return None
    
    @retry_db_operation()
    def logout_user(self, session_token: str) -> bool:
        """Logout a user by invalidating their session"""
        try:
            with get_db_session() as session:
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.session_token == session_token
                ).first()
                
                if session_model:
                    session_model.is_active = False
                    session.commit()
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return False
    
    @retry_db_operation()
    def update_password_hash(self, user_id: int, password_hash: str, salt: str) -> bool:
        """Update user password hash in database.
        
        Pure persistence operation - no business logic.
        All validation and hashing is done by the service layer.
        
        Args:
            user_id: User ID
            password_hash: Pre-hashed password (from service layer)
            salt: Password salt (from service layer)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(UserModel.id == user_id).first()
                
                if not user_model:
                    logger.warning(f"User not found for password update: user_id={user_id}")
                    return False
                
                # Pure persistence - update password hash and salt
                user_model.password_hash = password_hash
                user_model.salt = salt
                user_model.password_changed_at = datetime.now(timezone.utc)
                
                session.commit()
                logger.info(f"Password hash updated for user_id={user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Update password hash error: {e}")
            return False
    
    @retry_db_operation()
    def request_password_reset(self, request: PasswordResetRequest) -> Optional[Dict[str, Any]]:
        """Request password reset and generate reset token.
        
        Pure persistence operation - generates token and stores it.
        Returns token for service layer to send via email hook.
        """
        try:
            from database.auth.utils import generate_urlsafe_token
            
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(
                    UserModel.email == request.email
                ).first()
                
                if not user_model:
                    # Don't reveal if email exists or not
                    logger.debug("Password reset request for non-existent email")
                    return None
                
                # Generate URL-safe reset token (same as verification tokens)
                reset_token = generate_urlsafe_token(32)
                token_salt = generate_salt()
                token_hash = hash_password(reset_token, token_salt)
                
                # Invalidate any existing unused reset tokens for this user
                session.query(PasswordResetModel).filter(
                    PasswordResetModel.user_id == user_model.id,
                    PasswordResetModel.is_used == False
                ).update({"is_used": True, "used_at": datetime.now(timezone.utc)})
                
                # Create password reset record
                expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
                reset_model = PasswordResetModel(
                    user_id=user_model.id,
                    token_hash=token_hash,
                    token_salt=token_salt,
                    expires_at=expires_at
                )
                
                session.add(reset_model)
                session.commit()
                
                logger.info("Password reset token created for user_id=%s", user_model.id)
                
                return {
                    "reset_token": reset_token,
                    "expires_in_hours": 24,
                }
                
        except Exception as e:
            logger.error(f"Password reset request error: {e}")
            return None
    
    @retry_db_operation()
    def reset_password(self, token: str, password_hash: str, salt: str) -> Optional[int]:
        """Reset password using reset token.
        
        Pure persistence operation - verifies token and updates password hash.
        Returns user_id if successful, None otherwise.
        """
        try:
            import hmac
            
            with get_db_session() as session:
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                # Find all unused, non-expired reset tokens
                reset_models = session.query(PasswordResetModel).filter(
                    and_(
                        PasswordResetModel.is_used == False,
                        PasswordResetModel.expires_at > now_utc
                    )
                ).all()
                
                if not reset_models:
                    logger.debug("No valid reset tokens found")
                    return None
                
                # Verify token against each reset model (using stored salt)
                reset_model = None
                for model in reset_models:
                    # Hash token with stored salt
                    test_hash_with_salt = hash_password(token, model.token_salt)
                    if hmac.compare_digest(test_hash_with_salt, model.token_hash):
                        reset_model = model
                        break
                
                if not reset_model:
                    logger.debug("Reset token verification failed")
                    return None
                
                # Get user
                user_model = session.query(UserModel).filter(
                    UserModel.id == reset_model.user_id
                ).first()
                
                if not user_model:
                    logger.error("User not found for reset token user_id=%s", reset_model.user_id)
                    return None
                
                # Update password hash (pre-hashed by service layer)
                user_model.password_hash = password_hash
                user_model.salt = salt
                user_model.password_changed_at = datetime.now(timezone.utc)
                
                # Mark reset token as used
                reset_model.is_used = True
                reset_model.used_at = datetime.now(timezone.utc)
                
                session.commit()
                
                logger.info("Password reset successful for user_id=%s", user_model.id)
                return user_model.id
                
        except Exception as e:
            logger.error(f"Password reset error: {e}", exc_info=True)
            return None
    
    @retry_db_operation()
    def verify_email(self, token: str) -> Optional[int]:
        """Verify user email using verification token (optimized and secure)"""
        try:
            import hmac
            import hashlib
            
            with get_db_session() as session:
                # Step 1: Calculate lookup prefix from token (without salt)
                # This allows us to narrow down the search space significantly
                token_prefix = hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]
                
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                # Step 2: Query only tokens with matching prefix (much faster than loading all)
                # This reduces the search space from O(n) to O(1) in most cases
                candidate_models = session.query(EmailVerificationModel).filter(
                    EmailVerificationModel.token_prefix == token_prefix,
                    EmailVerificationModel.is_used == False,
                    EmailVerificationModel.expires_at > now_utc
                ).all()
                
                # Step 3: Find matching token using constant-time comparison
                # This prevents timing attacks
                matching_verification = None
                for verification_model in candidate_models:
                    # Hash token with stored salt (same method used in create_user)
                    test_hash_with_salt = hash_password(token, verification_model.token_salt)
                    # Use constant-time comparison to prevent timing attacks
                    if hmac.compare_digest(test_hash_with_salt, verification_model.token_hash):
                        matching_verification = verification_model
                        break
                
                # Step 4: Generic failure (don't reveal why it failed)
                # Always return None with same timing to prevent information disclosure
                if not matching_verification:
                    # Log attempt for security monitoring (server-side only)
                    logger.warning("Email verification failed: invalid or expired token")
                    return None
                
                # Step 5: Get user
                user_model = session.query(UserModel).filter(
                    UserModel.id == matching_verification.user_id
                ).first()
                
                if not user_model:
                    logger.warning("Email verification failed: user not found for token")
                    return None
                
                # Step 6: Check if already verified (idempotent - safe to call multiple times)
                if user_model.is_verified:
                    # Already verified, return user_id (don't reveal this was a duplicate)
                    logger.info("Email verification: user already verified (idempotent)")
                    return user_model.id
                
                # Step 7: Mark user as verified
                user_model.is_verified = True
                
                # Step 8: Mark verification token as used
                matching_verification.is_used = True
                matching_verification.used_at = datetime.now(timezone.utc)
                
                session.commit()
                
                logger.info("Email verification successful: user_id=%s", user_model.id)
                return user_model.id
                
        except Exception as e:
            logger.error("Email verification error: %s", e)
            # Generic failure - don't reveal internal errors
            return None
    
    @retry_db_operation()
    def create_verification_token(self, email: str) -> Optional[Dict[str, Any]]:
        """Create a new email verification token for an existing user.
        
        Used for resending verification emails.
        
        Returns:
            Dict with user info and verification_token if successful, None otherwise.
        """
        try:
            import hashlib
            
            with get_db_session() as session:
                # Find user by email
                user_model = session.query(UserModel).filter(
                    UserModel.email == email
                ).first()
                
                if not user_model:
                    # Don't reveal if user exists or not
                    logger.debug("Verification token request for non-existent email")
                    return None
                
                # Check if already verified
                if user_model.is_verified:
                    logger.debug("Verification token request for already verified user")
                    return None
                
                # Invalidate any existing unused verification tokens for this user
                session.query(EmailVerificationModel).filter(
                    EmailVerificationModel.user_id == user_model.id,
                    EmailVerificationModel.is_used == False
                ).update({"is_used": True, "used_at": datetime.now(timezone.utc)})
                
                # Generate new verification token (URL-safe)
                verification_token = generate_urlsafe_token()
                verification_salt = generate_salt()
                token_hash = hash_password(verification_token, verification_salt)
                token_prefix_hash = hashlib.sha256(verification_token.encode('utf-8')).hexdigest()[:16]
                
                verification_model = EmailVerificationModel(
                    user_id=user_model.id,
                    token_hash=token_hash,
                    token_salt=verification_salt,
                    token_prefix=token_prefix_hash,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7)
                )
                
                session.add(verification_model)
                session.commit()
                
                logger.info("New verification token created for user_id=%s", user_model.id)
                
                return {
                    "user_id": user_model.id,
                    "email": user_model.email,
                    "username": user_model.username,
                    "first_name": user_model.first_name,
                    "last_name": user_model.last_name,
                    "verification_token": verification_token,
                }
                
        except Exception as e:
            logger.error("Create verification token error: %s", e)
            return None
    
    # UserManagementPort implementations
    
    @retry_db_operation()
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(UserModel.id == user_id).first()
                return self._user_model_to_domain(user_model) if user_model else None
        except Exception as e:
            logger.error(f"Get user by ID error: {e}")
            return None
    
    @retry_db_operation()
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(
                    UserModel.username == username
                ).first()
                return self._user_model_to_domain(user_model) if user_model else None
        except Exception as e:
            logger.error(f"Get user by username error: {e}")
            return None
    
    @retry_db_operation()
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(
                    UserModel.email == email
                ).first()
                return self._user_model_to_domain(user_model) if user_model else None
        except Exception as e:
            logger.error(f"Get user by email error: {e}")
            return None
    
    @retry_db_operation()
    def create_user(self, user: User, password: str) -> Optional[User]:
        """Create a new user and generate email verification token"""
        try:
            with get_db_session() as session:
                # CRITICAL: Auto-generate username if empty (from email)
                # This handles the case where username is passed as empty string
                if not user.username or not user.username.strip():
                    # Auto-generate username from email (part before @)
                    if '@' in user.email and user.email.split('@')[0]:
                        base_username = user.email.split('@')[0].strip()
                    else:
                        # Fallback if email doesn't have @ or part before @ is empty
                        if user.email and user.email.strip():
                            base_username = user.email.replace('@', '_').replace('.', '_')[:20]
                            base_username = base_username.strip()
                        else:
                            base_username = f"user_{uuid.uuid4().hex[:8]}"
                    
                    # Ensure base_username is not empty
                    if not base_username or not base_username.strip():
                        base_username = f"user_{uuid.uuid4().hex[:8]}"
                    
                    # Clean and validate username
                    base_username = base_username.strip()
                    base_username = re.sub(r'[^a-zA-Z0-9_-]', '_', base_username)
                    
                    if not base_username:
                        base_username = f"user_{uuid.uuid4().hex[:8]}"
                    
                    # Check for conflicts and append number if needed
                    username = base_username
                    counter = 1
                    max_attempts = 100
                    while session.query(UserModel).filter(UserModel.username == username).first():
                        username = f"{base_username}{counter}"
                        counter += 1
                        if counter > max_attempts:
                            username = f"user_{uuid.uuid4().hex[:8]}"
                            break
                    
                    # Final validation
                    if not username or not username.strip():
                        username = f"user_{uuid.uuid4().hex[:8]}"
                    
                    logger.info("Auto-generated username for user: %s -> %s", user.email, username)
                else:
                    username = user.username.strip()
                    # Final check even if username was provided
                    if not username:
                        username = f"user_{uuid.uuid4().hex[:8]}"
                
                # OAuth-only users: store sentinel literally (not hashed)
                # so has_password detection works via password_hash != "!OAUTH_ONLY"
                if password == "!OAUTH_ONLY":
                    salt = "!OAUTH_ONLY"
                    password_hash = "!OAUTH_ONLY"
                else:
                    salt = generate_salt()
                    password_hash = hash_password(password, salt)
                
                # Use role_id directly if provided, otherwise look up from role name
                role_id = user.role_id
                if not role_id:
                    # Fallback: Look up role_id from role name
                    role_name = user.role.value if isinstance(user.role, UserRole) else user.role
                    try:
                        from database.auth.rbac_service import RBACService
                        rbac_service = RBACService(session)
                        db_role = rbac_service.get_role_by_name(role_name)
                        if db_role:
                            role_id = db_role.id
                        else:
                            raise ValueError(f"Role '{role_name}' not found in database. Run seed_database() to create default roles.")
                    except ValueError:
                        raise
                    except Exception as e:
                        logger.warning(f"Could not look up role_id for role '{role_name}': {e}")
                
                user_model = UserModel(
                    username=username,  # Use auto-generated or provided username
                    email=user.email,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    password_hash=password_hash,
                    salt=salt,
                    role_id=role_id,  # Foreign key to roles table
                    is_active=user.is_active,
                    is_verified=user.is_verified,
                    max_products=user.max_products,
                    api_rate_limit=user.api_rate_limit
                )
                
                session.add(user_model)
                session.flush()  # Flush to get the ID without committing
                session.refresh(user_model)  # Refresh to get all database-generated fields
                session.commit()  # Commit after refresh
                
                # Generate email verification token (URL-safe)
                verification_token = generate_urlsafe_token()
                # Generate a proper salt for token hashing
                verification_salt = generate_salt()
                token_hash = hash_password(verification_token, verification_salt)
                # Store prefix for fast lookup (hash of token without salt for consistent lookup)
                # This allows us to query by prefix first, then verify with salted hash
                import hashlib
                token_prefix_hash = hashlib.sha256(verification_token.encode('utf-8')).hexdigest()[:16]
                
                verification_model = EmailVerificationModel(
                    user_id=user_model.id,
                    token_hash=token_hash,
                    token_salt=verification_salt,  # Store salt for verification
                    token_prefix=token_prefix_hash,  # Fast lookup prefix (from token, not salted hash)
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7)  # 7 days expiry
                )
                
                session.add(verification_model)
                session.commit()
                
                # Return user with verification token (in real implementation, send via email)
                created_user = self._user_model_to_domain(user_model)
                # Store token in a temporary attribute for the service layer
                setattr(created_user, '_verification_token', verification_token)
                
                return created_user
                
        except Exception as e:
            # Enhanced error logging when DEBUG_MODE is enabled
            from config import CONFIG
            debug_mode = CONFIG.get("DEBUG_MODE", False)
            
            if debug_mode:
                import traceback
                tb_str = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                error_type = type(e).__name__
                error_message = str(e)
                logger.error(
                    "Create user error (DEBUG_MODE enabled): [%s] %s\nEmail: %s\nUsername: %s\nTraceback:\n%s",
                    error_type, error_message, user.email, user.username, tb_str,
                    exc_info=True
                )
                # Re-raise with detailed message in DEBUG_MODE so it propagates to service layer
                # Use the original error type, not RuntimeError, to avoid double wrapping
                raise type(e)(f"[{error_type}] {error_message}") from e
            else:
                logger.error(f"Create user error: {e}", exc_info=True)
            
            return None
    
    @retry_db_operation()
    def update_user(self, user_id: int, updates: Dict[str, Any]) -> Optional[User]:
        """Update user information"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(UserModel.id == user_id).first()
                
                if not user_model:
                    return None
                
                # Update fields from dict
                if "username" in updates:
                    user_model.username = updates["username"]
                if "email" in updates:
                    user_model.email = updates["email"]
                if "first_name" in updates:
                    user_model.first_name = updates["first_name"]
                if "last_name" in updates:
                    user_model.last_name = updates["last_name"]
                # Handle role update - always update role_id
                if "role_id" in updates:
                    user_model.role_id = updates["role_id"]
                elif "role" in updates:
                    # If role name/enum provided, look up role_id
                    role_value = updates["role"]
                    role_name = role_value.value if isinstance(role_value, UserRole) else role_value
                    try:
                        from database.auth.rbac_service import RBACService
                        rbac_service = RBACService(session)
                        db_role = rbac_service.get_role_by_name(role_name)
                        if db_role:
                            user_model.role_id = db_role.id
                        else:
                            logger.warning(f"Role '{role_name}' not found in database")
                    except Exception as e:
                        logger.warning(f"Could not look up role_id for role '{role_name}': {e}")
                if "password_hash" in updates:
                    user_model.password_hash = updates["password_hash"]
                if "salt" in updates:
                    user_model.salt = updates["salt"]
                if "is_active" in updates:
                    user_model.is_active = updates["is_active"]
                if "is_verified" in updates:
                    user_model.is_verified = updates["is_verified"]
                if "max_products" in updates:
                    user_model.max_products = updates["max_products"]
                if "api_rate_limit" in updates:
                    user_model.api_rate_limit = updates["api_rate_limit"]
                
                user_model.updated_at = datetime.now(timezone.utc)
                
                session.flush()  # Flush to get updated fields without committing
                session.refresh(user_model)  # Refresh to get all database-generated fields
                session.commit()  # Commit after refresh
                
                return self._user_model_to_domain(user_model)
                
        except Exception as e:
            logger.error(f"Update user error: {e}")
            return None
    
    def delete_user(self, user_id: int) -> bool:
        """Delete a user and all related records"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(UserModel.id == user_id).first()

                if not user_model:
                    return False

                self._delete_user_cascade(session, user_id, user_model)
                session.commit()
                return True

        except Exception as e:
            logger.error(f"Delete user error: {e}")
            return False

    def _delete_user_cascade(self, session, user_id: int, user_model) -> None:
        """Delete all records owned by a user in correct FK dependency order."""
        # --- deepest children first ---

        # 1. invoices (FK → payment_transactions, user_id)
        session.query(InvoiceModel).filter(
            InvoiceModel.user_id == user_id
        ).delete(synchronize_session=False)

        # 9. payment_transactions (FK → user_id)
        session.query(PaymentTransactionModel).filter(
            PaymentTransactionModel.user_id == user_id
        ).delete(synchronize_session=False)

        # 10. credit_ledgers (FK → user_id)
        session.query(CreditLedgerModel).filter(
            CreditLedgerModel.user_id == user_id
        ).delete(synchronize_session=False)

        # 11. oauth_accounts (FK → user_id)
        session.query(OAuthAccountModel).filter(
            OAuthAccountModel.user_id == user_id
        ).delete(synchronize_session=False)

        # 12. email verifications
        session.query(EmailVerificationModel).filter(
            EmailVerificationModel.user_id == user_id
        ).delete(synchronize_session=False)

        # 15. password resets
        session.query(PasswordResetModel).filter(
            PasswordResetModel.user_id == user_id
        ).delete(synchronize_session=False)

        # 16. user sessions
        session.query(UserSessionModel).filter(
            UserSessionModel.user_id == user_id
        ).delete(synchronize_session=False)

        # 17. api keys
        session.query(ApiKeyModel).filter(
            ApiKeyModel.user_id == user_id
        ).delete(synchronize_session=False)

        # 18. clear user permissions (m2m)
        user_model.direct_permissions = []

        # 19. delete the user
        session.delete(user_model)
    
    @retry_db_operation()
    def cleanup_unverified_users(self, days: int = 30) -> int:
        """Clean up unverified users created before n days."""
        try:
            with get_db_session() as session:
                # Calculate cutoff date
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
                
                # Find users to delete
                users_to_delete = session.query(UserModel).filter(
                    UserModel.is_verified == False,
                    UserModel.created_at < cutoff_date
                ).all()
                
                count = 0
                for user in users_to_delete:
                    self._delete_user_cascade(session, user.id, user)
                    count += 1
                
                session.commit()
                logger.info(f"Cleaned up {count} unverified users older than {days} days")
                return count
                
        except Exception as e:
            logger.error(f"Cleanup unverified users error: {e}")
            return 0
    
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
        try:
            with get_db_session() as session:
                query = session.query(UserModel)
                
                # Apply filters
                if role_id:
                    query = query.filter(UserModel.role_id == role_id)
                if is_active is not None:
                    query = query.filter(UserModel.is_active == is_active)
                if is_verified is not None:
                    query = query.filter(UserModel.is_verified == is_verified)
                if search:
                    search_term = f"%{search}%"
                    query = query.filter(
                        or_(
                            UserModel.username.ilike(search_term),
                            UserModel.email.ilike(search_term),
                            UserModel.first_name.ilike(search_term),
                            UserModel.last_name.ilike(search_term)
                        )
                    )
                
                # Apply sorting
                sort_columns = {
                    "id": UserModel.id,
                    "username": UserModel.username,
                    "email": UserModel.email,
                    "created_at": UserModel.created_at,
                    "updated_at": UserModel.updated_at,
                    "last_login": UserModel.last_login
                }
                sort_column = sort_columns.get(sort_by, UserModel.created_at)
                if sort_order.lower() == "asc":
                    query = query.order_by(asc(sort_column))
                else:
                    query = query.order_by(desc(sort_column))
                
                total = query.count()
                users = query.offset((page - 1) * page_size).limit(page_size).all()
                
                return {
                    "users": [self._user_model_to_domain(user) for user in users],
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": (total + page_size - 1) // page_size
                }
                
        except Exception as e:
            logger.error(f"List users error: {e}")
            return {"users": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}
    
    def get_all_users(self) -> List[User]:
        """Get all users"""
        try:
            with get_db_session() as session:
                user_models = session.query(UserModel).all()
                return [self._user_model_to_domain(user_model) for user_model in user_models]
        except Exception as e:
            logger.error(f"Get all users error: {e}")
            return []
    
    # SessionManagementPort implementations
    
    def create_session(self, user_id: int, ip_address: Optional[str] = None, 
                      user_agent: Optional[str] = None, remember_me: bool = False) -> Optional[UserSession]:
        """Create a new user session"""
        try:
            with get_db_session() as session:
                session_token = generate_session_token()
                refresh_token = generate_session_token()
                
                # Set expiration based on remember_me
                if remember_me:
                    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                else:
                    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
                
            session_model = UserSessionModel(
                user_id=user_id,
                session_token=session_token,
                refresh_token=refresh_token,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=expires_at
            )
            
            session.add(session_model)
            session.commit()
            session.refresh(session_model)
            
            return self._session_model_to_domain(session_model)
                
        except Exception as e:
            logger.error(f"Create session error: {e}")
            return None
    
    def get_session_by_token(self, session_token: str) -> Optional[UserSession]:
        """Get session by token"""
        try:
            with get_db_session() as session:
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.session_token == session_token,
                    UserSessionModel.is_active == True
                ).first()
                
                return self._session_model_to_domain(session_model) if session_model else None
                
        except Exception as e:
            logger.error(f"Get session by token error: {e}")
            return None
    
    def get_session_by_refresh_token(self, refresh_token: str) -> Optional[UserSession]:
        """Get session by refresh token"""
        try:
            with get_db_session() as session:
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.refresh_token == refresh_token,
                    UserSessionModel.is_active == True
                ).first()
                
                return self._session_model_to_domain(session_model) if session_model else None
                
        except Exception as e:
            logger.error(f"Get session by refresh token error: {e}")
            return None

    def get_session_by_id(self, session_id: int) -> Optional[UserSession]:
        """Get session by ID (only returns active sessions)"""
        try:
            with get_db_session() as session:
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.id == session_id,
                    UserSessionModel.is_active == True
                ).first()
                
                return self._session_model_to_domain(session_model) if session_model else None
                
        except Exception as e:
            logger.error(f"Get session by ID error: {e}")
            return None
    
    def invalidate_session(self, session_token: str) -> bool:
        """Invalidate a session"""
        try:
            with get_db_session() as session:
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.session_token == session_token
                ).first()
                
                if session_model:
                    session_model.is_active = False
                    session.commit()
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Invalidate session error: {e}")
            return False
    
    def invalidate_session_by_id(self, session_id: int) -> bool:
        """Invalidate a session by ID"""
        try:
            with get_db_session() as session:
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.id == session_id
                ).first()
                
                if session_model:
                    session_model.is_active = False
                    session.commit()
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Invalidate session by ID error: {e}")
            return False
    
    def update_session_refresh_token(self, session_id: int, refresh_token_hash: str) -> bool:
        """Update the stored refresh token hash for a session (for single-use rotation)"""
        try:
            with get_db_session() as session:
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.id == session_id,
                    UserSessionModel.is_active == True
                ).first()

                if session_model:
                    session_model.refresh_token = refresh_token_hash
                    session.commit()
                    return True

                return False

        except Exception as e:
            logger.error(f"Update session refresh token error: {e}")
            return False

    def invalidate_user_sessions(self, user_id: int, exclude_session_id: Optional[int] = None) -> int:
        """Invalidate all sessions for a user"""
        try:
            with get_db_session() as session:
                query = session.query(UserSessionModel).filter(
                    UserSessionModel.user_id == user_id,
                    UserSessionModel.is_active == True
                )
                
                if exclude_session_id:
                    query = query.filter(UserSessionModel.id != exclude_session_id)
                
                sessions = query.all()
                count = len(sessions)
                
                for session_model in sessions:
                    session_model.is_active = False
                
                session.commit()
                return count
                
        except Exception as e:
            logger.error(f"Invalidate user sessions error: {e}")
            return 0
    
    def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions"""
        try:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            with get_db_session() as session:
                expired_sessions = session.query(UserSessionModel).filter(
                    UserSessionModel.expires_at < now_utc
                ).all()
                
                count = len(expired_sessions)
                
                for session_model in expired_sessions:
                    session_model.is_active = False
                
                session.commit()
                return count
                
        except Exception as e:
            logger.error(f"Cleanup expired sessions error: {e}")
            return 0
    
    def get_user_sessions(self, user_id: int) -> List[UserSession]:
        """Get all active sessions for a user"""
        try:
            with get_db_session() as session:
                session_models = session.query(UserSessionModel).filter(
                    UserSessionModel.user_id == user_id,
                    UserSessionModel.is_active == True
                ).all()
                
                return [self._session_model_to_domain(session_model) for session_model in session_models]
                
        except Exception as e:
            logger.error(f"Get user sessions error: {e}")
            return []
    
    # Helper methods for model conversion
    
    def _user_model_to_domain(self, user_model: UserModel) -> User:
        """Convert database user model to domain user"""
        if not user_model:
            return None
        
        # Get role name from role_obj relationship (uses role_name property as fallback)
        role_name = user_model.role_name  # This is a property that returns role_obj.name or "user"
        
        # Try to convert to UserRole enum, fallback to USER if not found
        try:
            user_role = UserRole(role_name)
        except ValueError:
            # Role not in enum, default to USER
            logger.warning(f"User {user_model.id} has role '{role_name}' not in enum, defaulting to USER")
            user_role = UserRole.USER
        
        return User(
            id=user_model.id,
            username=user_model.username,
            email=user_model.email,
            first_name=user_model.first_name,
            last_name=user_model.last_name,
            role_id=user_model.role_id,  # Foreign key to roles table
            role=user_role,
            is_active=user_model.is_active,
            is_verified=user_model.is_verified,
            max_products=user_model.max_products,
            api_rate_limit=user_model.api_rate_limit,
            failed_login_attempts=user_model.failed_login_attempts,
            locked_until=user_model.locked_until,
            last_login=user_model.last_login,
            created_at=user_model.created_at,
            updated_at=user_model.updated_at,
            has_password=_check_has_password(user_model),
        )
    
    def _session_model_to_domain(self, session_model: UserSessionModel) -> UserSession:
        """Convert database session model to domain session"""
        if not session_model:
            return None
        
        return UserSession(
            id=session_model.id,
            user_id=session_model.user_id,
            session_token=session_model.session_token,
            refresh_token=session_model.refresh_token,
            ip_address=session_model.ip_address,
            user_agent=session_model.user_agent,
            is_active=session_model.is_active,
            expires_at=session_model.expires_at,
            created_at=session_model.created_at
        )
    
    def _create_session_model(self, session: Session, user_id: int, request: LoginRequest) -> Optional[UserSessionModel]:
        """Create a new session model"""
        try:
            session_token = generate_session_token()
            refresh_token = generate_session_token()
            
            # Set expiration based on remember_me
            if request.remember_me:
                expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            else:
                expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            
            session_model = UserSessionModel(
                user_id=user_id,
                session_token=session_token,
                refresh_token=refresh_token,
                ip_address=request.ip_address,
                user_agent=request.user_agent,
                expires_at=expires_at
            )
            
            session.add(session_model)
            session.flush()  # Flush to get the ID without committing
            session.refresh(session_model)  # Refresh to get all database-generated fields
            session.commit()  # Commit after refresh
            
            return session_model
            
        except Exception as e:
            # Enhanced error logging when DEBUG_MODE is enabled
            from config import CONFIG
            debug_mode = CONFIG.get("DEBUG_MODE", False)
            
            # Log additional context
            error_context = {
                "user_id": user_id,
                "ip_address": request.ip_address,
                "user_agent": request.user_agent,
                "remember_me": request.remember_me,
                "error_type": type(e).__name__,
                "error_message": str(e)
            }
            
            if debug_mode:
                import traceback
                tb_str = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                logger.error(
                    "Create session model error (DEBUG_MODE enabled): %s\n"
                    "Context: %s\n"
                    "Traceback:\n%s",
                    e, error_context, tb_str,
                    exc_info=True
                )
            else:
                logger.error(
                    "Create session model error: %s (user_id=%s, error_type=%s)",
                    e, user_id, type(e).__name__,
                    exc_info=True
                )
            return None
    
    # ApiKeyManagementPort implementations
    
    def create_api_key(self, user_id: int, request: CreateApiKeyRequest) -> CreateApiKeyResponse:
        """Create a new API key for a user"""
        try:
            with get_db_session() as session:
                # Generate API key - returns (full_key, key_hash)
                api_key_value, api_key_hash = generate_api_key()
                
                # Generate key prefix for identification
                key_prefix = api_key_value[:8]
                
                api_key_model = ApiKeyModel(
                    user_id=user_id,
                    key_name=request.key_name,
                    key_hash=api_key_hash,
                    key_prefix=key_prefix,
                    permissions=request.permissions or "[]",
                    rate_limit=request.rate_limit or 1000,
                    is_active=True
                )
                
                session.add(api_key_model)
                session.flush()  # Flush to get the ID without committing
                session.refresh(api_key_model)  # Refresh to get all database-generated fields
                session.commit()  # Commit after refresh
                
                # Create domain API key object
                api_key = ApiKey(
                    id=api_key_model.id,
                    user_id=api_key_model.user_id,
                    key_name=api_key_model.key_name,
                    key_prefix=api_key_model.key_prefix,
                    permissions=request.permissions or "[]",
                    rate_limit=api_key_model.rate_limit,
                    is_active=api_key_model.is_active,
                    created_at=api_key_model.created_at
                )
                
                return CreateApiKeyResponse(
                    status=AuthStatus.SUCCESS,
                    api_key=api_key,
                    full_key=api_key_value,
                    message="API key created successfully"
                )
                
        except Exception as e:
            logger.error(f"Create API key error: {e}")
            return CreateApiKeyResponse(
                status=AuthStatus.FAILED,
                message="Failed to create API key"
            )
    
    def get_api_key_by_id(self, api_key_id: int) -> Optional[ApiKey]:
        """Get API key by ID"""
        try:
            with get_db_session() as session:
                api_key_model = session.query(ApiKeyModel).filter(
                    ApiKeyModel.id == api_key_id
                ).first()
                
                return self._api_key_model_to_domain(api_key_model) if api_key_model else None
                
        except Exception as e:
            logger.error(f"Get API key error: {e}")
            return None
    
    def get_api_key_by_key(self, api_key: str) -> Optional[ApiKey]:
        """Get API key by key value"""
        try:
            with get_db_session() as session:
                # Hash the provided key to compare with stored hash
                api_key_hash = hash_password(api_key, generate_salt())
                
                api_key_model = session.query(ApiKeyModel).filter(
                    ApiKeyModel.key_hash == api_key_hash,
                    ApiKeyModel.is_active == True
                ).first()
                
                return self._api_key_model_to_domain(api_key_model) if api_key_model else None
                
        except Exception as e:
            logger.error(f"Get API key by key error: {e}")
            return None
    
    def list_user_api_keys(self, user_id: int) -> List[ApiKey]:
        """List all API keys for a user"""
        try:
            with get_db_session() as session:
                api_key_models = session.query(ApiKeyModel).filter(
                    ApiKeyModel.user_id == user_id,
                    ApiKeyModel.is_active == True
                ).all()
                
                return [self._api_key_model_to_domain(model) for model in api_key_models]
                
        except Exception as e:
            logger.error(f"List user API keys error: {e}")
            return []
    
    def revoke_api_key(self, api_key_id: int, user_id: int) -> bool:
        """Revoke an API key"""
        try:
            with get_db_session() as session:
                api_key_model = session.query(ApiKeyModel).filter(
                    ApiKeyModel.id == api_key_id,
                    ApiKeyModel.user_id == user_id
                ).first()
                
                if api_key_model:
                    api_key_model.is_active = False
                    session.commit()
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Revoke API key error: {e}")
            return False
    
    # AuthorizationPort implementations
    
    def get_auth_context(self, token: str, token_type: str = "bearer",
                        ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Optional[AuthContext]:
        """Get authentication context from JWT token with IP and User-Agent validation"""
        try:
            # Validate token format before decoding
            if not token or not isinstance(token, str):
                logger.warning("Invalid token: token is empty or not a string")
                return None

            # Token-keyed cache (30 s TTL). Skips the full JWT decode +
            # 3–4 DB round-trip cascade when the same (token, ip, ua)
            # tuple was validated within the cache window. Decoded JWT
            # signature is the only cryptographic guarantee we drop;
            # since we control both the cache process and the JWT
            # secret, that's safe. IP / UA are part of the key so a
            # mismatch forces a fresh full validation.
            cache_key = self._auth_cache_key(token, ip_address, user_agent)
            cached = self._auth_cache_get(cache_key)
            if cached is not None:
                return cached
            
            # JWT tokens must have 3 parts separated by dots (header.payload.signature)
            token_parts = token.split('.')
            if len(token_parts) != 3:
                from config import CONFIG
                if CONFIG.get("DEBUG_MODE", False):
                    logger.warning(
                        "Invalid JWT token format: expected 3 segments (header.payload.signature), "
                        "got %d segments. Token length: %d, Token preview: %s",
                        len(token_parts), len(token), token[:50] + "..." if len(token) > 50 else token
                    )
                else:
                    logger.warning("Invalid JWT token format: not enough segments")
                return None
            
            # Decode JWT token
            decoded_token = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])

            # Reject refresh tokens used as access tokens
            if decoded_token.get("type") == "refresh":
                logger.warning("Refresh token used as access token — rejected")
                return None

            user_id = decoded_token.get("user_id")
            session_id = decoded_token.get("session_id")
            
            if not user_id or not session_id:
                return None
            
            with get_db_session() as session:
                # Get session by ID
                session_model = session.query(UserSessionModel).filter(
                    UserSessionModel.id == session_id,
                    UserSessionModel.is_active == True
                ).first()
                
                if session_model and not session_model.is_expired:
                    # Validate IP address if provided
                    if ip_address and session_model.ip_address:
                        if ip_address != session_model.ip_address:
                            logger.warning(
                                f"IP address mismatch for session {session_id}: "
                                f"expected {session_model.ip_address}, got {ip_address}"
                            )
                            # Reject on IP mismatch to prevent token sharing/spam
                            return None
                    
                    # Validate User-Agent if provided
                    if user_agent and session_model.user_agent:
                        if user_agent != session_model.user_agent:
                            logger.warning(
                                f"User-Agent mismatch for session {session_id}: "
                                f"expected {session_model.user_agent[:50]}..., got {user_agent[:50]}..."
                            )
                            # Reject on User-Agent mismatch for security
                            return None
                    
                    # Get user
                    user_model = session.query(UserModel).filter(
                        UserModel.id == user_id,
                        UserModel.is_active == True
                    ).first()
                    
                    if user_model:
                        user = self._user_model_to_domain(user_model)
                        
                        # Load permissions using RBAC system
                        role_perms = []
                        direct_perms = []
                        all_perms = []
                        
                        try:
                            from database.auth.rbac_service import RBACService
                            rbac_service = RBACService(session)
                            
                            # Get role-based permissions
                            # Use role_id if available, otherwise fallback to role string
                            if user_model.role_id:
                                role_perms = rbac_service.get_role_permissions_by_id(user_model.role_id)
                            else:
                                # Fallback to using role name (from role_name property)
                                role_perms = rbac_service.get_role_permissions(user_model.role_name)
                            
                            # Get direct user permissions
                            direct_perms = rbac_service.get_user_direct_permissions(user_id)
                            
                            # Combine all permissions
                            all_perms = list(set(role_perms + direct_perms))
                            
                            # Debug logging (only in debug mode)
                            from config import CONFIG
                            if CONFIG.get("DEBUG_MODE", False):
                                role_info = f"role_id={user_model.role_id}, role={user_model.role_name}"
                                logger.debug(
                                    "Loaded permissions for user %d (%s): "
                                    "role_perms=%d, direct_perms=%d, total=%d",
                                    user_id, role_info, len(role_perms), 
                                    len(direct_perms), len(all_perms)
                                )
                                if all_perms:
                                    logger.debug("Permissions: %s", ", ".join(all_perms[:10]))
                        except Exception as e:
                            # If RBAC tables don't exist or there's an error, log but continue
                            # This allows graceful degradation if RBAC isn't set up yet
                            logger.warning(
                                "Failed to load RBAC permissions for user %d: %s. "
                                "RBAC tables may not exist. Run migrations: "
                                "python database/migrations/add_rbac_tables.py",
                                user_id, e
                            )
                            # Continue with empty permissions - user will only have role-based access
                        
                        ctx = AuthContext(
                            user=user,
                            session=self._session_model_to_domain(session_model),
                            permissions=all_perms,  # All permissions (for backward compatibility)
                            role_permissions=role_perms,  # Permissions from role
                            direct_permissions=direct_perms  # Direct user permissions
                        )
                        # Populate cache for the next 30 s of requests
                        # against the same (token, ip, ua) tuple.
                        self._auth_cache_put(cache_key, ctx)
                        return ctx
                
                return None
                
        except jwt.ExpiredSignatureError:
            logger.debug("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            from config import CONFIG
            if CONFIG.get("DEBUG_MODE", False):
                logger.warning("Invalid JWT token: %s (token preview: %s)", e, token[:50] + "..." if token and len(token) > 50 else token)
            else:
                logger.debug("Invalid JWT token")
            return None
        except Exception as e:
            from config import CONFIG
            if CONFIG.get("DEBUG_MODE", False):
                logger.error("Get auth context error: %s (token preview: %s)", e, token[:50] + "..." if token and len(token) > 50 else token, exc_info=True)
            else:
                logger.error("Get auth context error: %s", e)
            return None
    
    def check_permission(self, user_id: int, permission: str) -> bool:
        """Check if user has specific permission"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(
                    UserModel.id == user_id,
                    UserModel.is_active == True
                ).first()
                
                if not user_model:
                    return False
                
                # Simple role-based permission check
                if permission == "admin" and user_model.role_name == "admin":
                    return True
                elif permission == "user" and user_model.role_name in ["user", "admin"]:
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Check permission error: {e}")
            return False
    
    def _api_key_model_to_domain(self, api_key_model: ApiKeyModel) -> ApiKey:
        """Convert database API key model to domain API key"""
        if not api_key_model:
            return None
        
        return ApiKey(
            id=api_key_model.id,
            user_id=api_key_model.user_id,
            key_name=api_key_model.key_name,
            key_prefix=api_key_model.key_prefix,
            permissions=api_key_model.permissions,
            rate_limit=api_key_model.rate_limit,
            is_active=api_key_model.is_active,
            last_used=api_key_model.last_used,
            expires_at=api_key_model.expires_at,
            created_at=api_key_model.created_at
        )
    
    # Additional required method implementations
    
    def check_rate_limit(self, user_id: int, endpoint: str) -> bool:
        """Check if user has exceeded rate limit for endpoint"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(UserModel.id == user_id).first()
                if not user_model:
                    return False
                
                # Simple rate limiting - can be enhanced
                return True  # TODO: Implement proper rate limiting
                
        except Exception as e:
            logger.error(f"Check rate limit error: {e}")
            return False
    
    def cleanup_expired_api_keys(self) -> int:
        """Clean up expired API keys"""
        try:
            with get_db_session() as session:
                expired_keys = session.query(ApiKeyModel).filter(
                    ApiKeyModel.expires_at < datetime.now(timezone.utc),
                    ApiKeyModel.is_active == True
                ).all()
                
                count = len(expired_keys)
                for key in expired_keys:
                    key.is_active = False
                
                session.commit()
                return count
                
        except Exception as e:
            logger.error(f"Cleanup expired API keys error: {e}")
            return 0
    
    def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        """Get API key by hash"""
        try:
            with get_db_session() as session:
                api_key_model = session.query(ApiKeyModel).filter(
                    ApiKeyModel.key_hash == key_hash,
                    ApiKeyModel.is_active == True
                ).first()
                
                return self._api_key_model_to_domain(api_key_model) if api_key_model else None
                
        except Exception as e:
            logger.error(f"Get API key by hash error: {e}")
            return None
    
    def get_api_key_by_prefix(self, key_prefix: str) -> Optional[ApiKey]:
        """Get API key by prefix"""
        try:
            with get_db_session() as session:
                api_key_model = session.query(ApiKeyModel).filter(
                    ApiKeyModel.key_prefix == key_prefix,
                    ApiKeyModel.is_active == True
                ).first()
                
                return self._api_key_model_to_domain(api_key_model) if api_key_model else None
                
        except Exception as e:
            logger.error(f"Get API key by prefix error: {e}")
            return None
    
    
    def increment_request_count(self, user_id: int, endpoint: str) -> bool:
        """Increment request count for rate limiting"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(UserModel.id == user_id).first()
                if user_model:
                    # TODO: Implement proper request counting
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Increment request count error: {e}")
            return False
    
    def update_api_key_usage(self, api_key_id: int) -> bool:
        """Update API key last used timestamp"""
        try:
            with get_db_session() as session:
                api_key_model = session.query(ApiKeyModel).filter(ApiKeyModel.id == api_key_id).first()
                if api_key_model:
                    api_key_model.last_used = datetime.now(timezone.utc)
                    session.commit()
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Update API key usage error: {e}")
            return False
    
    
    def validate_permission(self, user_id: int, permission: str) -> bool:
        """Validate if user has specific permission"""
        try:
            with get_db_session() as session:
                user_model = session.query(UserModel).filter(UserModel.id == user_id).first()
                if not user_model or not user_model.is_active:
                    return False
                
                # Simple permission validation
                if permission == "admin" and user_model.role_name == "admin":
                    return True
                elif permission == "user" and user_model.role_name in ["user", "admin"]:
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Validate permission error: {e}")
            return False
    
    def validate_product_access(self, user_id: int, product_id: str) -> bool:
        """Validate if user has access to specific product"""
        # UserProduct model removed — default deny for now
        return False
"""
Authentication API Routes

FastAPI routes for user authentication, registration, and session management.
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request, Header, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import jwt as pyjwt
from config import CONFIG
from utils.security.captcha import validate_captcha

from domain.entities.auth_models import (
    LoginRequest, LoginResponse, RegisterRequest, RegisterResponse,
    PasswordResetRequest, PasswordResetResponse, ChangePasswordRequest, ChangePasswordResponse,
    CreateApiKeyRequest, CreateApiKeyResponse, User, UserSession, ApiKey,
    AuthContext, AuthStatus, UserRole
)
from domain.services.auth_service import AuthService
from domain.api_models import ApiResponse, ErrorResponse
from utils.request import get_request_metadata
from utils.database.force_write import require_write_db, require_read_db
from utils.security.rbac import rbac
from utils.auth_provider import get_auth_service
from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Custom OAuth2 form that accepts "username" (OAuth2 standard) but treats it as email
# OAuth2 standard requires "username" field name, but we use email for authentication
class OAuth2EmailPasswordRequestForm:
    """
    Custom OAuth2 form that accepts 'username' field (OAuth2 standard)
    but treats it as email for authentication
    """
    def __init__(
        self,
        username: str = Form(..., description="User's email address (OAuth2 uses 'username' field name, but enter your email here)"),
        password: str = Form(..., description="User's password (required)"),
        grant_type: Optional[str] = Form("password", description="OAuth2 grant type"),
        scope: Optional[str] = Form("", description="OAuth2 scopes"),
        client_id: Optional[str] = Form(None, description="OAuth2 client ID"),
        client_secret: Optional[str] = Form(None, description="OAuth2 client secret"),
    ):
        # OAuth2 sends "username" but we treat it as email
        self.email = username
        self.username = username  # Keep for compatibility
        self.password = password
        self.grant_type = grant_type
        self.scope = scope
        self.client_id = client_id
        self.client_secret = client_secret

# Configure logging
logger = logging.getLogger(__name__)

# API Request Models (Pydantic) - exclude internal fields from Swagger
class LoginRequestAPI(BaseModel):
    """API request model for login (excludes ip_address and user_agent)"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "admin@example.com",
                "password": "secure_password",
                "remember_me": False,
                "captcha_token": None
            }
        }
    )

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=500)
    remember_me: bool = False
    captcha_token: Optional[str] = None

class RegisterRequestAPI(BaseModel):
    """API request model for registration"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "password": "secure_password123",
                "first_name": "John",
                "last_name": "Doe",
                "captcha_token": "03AGdBq24..."
            }
        }
    )
    
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    captcha_token: Optional[str] = None

class PasswordResetRequestAPI(BaseModel):
    """API request model for password reset"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "captcha_token": "03AGdBq24..."
            }
        }
    )
    
    email: EmailStr
    captcha_token: Optional[str] = None

class ResetPasswordRequestAPI(BaseModel):
    """API request model for resetting password with token"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "k2HlxVjniTaZ2DGxC7-VdlSW7EdmzfTYtcDJrY_BzVA",
                "new_password": "NewSecurePassword123",
                "captcha_token": "03AGdBq24..."
            }
        }
    )
    token: str = Field(..., min_length=1, max_length=500)
    new_password: str = Field(..., min_length=8, max_length=128)
    captcha_token: Optional[str] = None

class RefreshTokenRequestAPI(BaseModel):
    """API request model for refreshing an access token"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
            }
        }
    )
    refresh_token: str = Field(..., min_length=1)

# Security schemes
security = HTTPBearer()
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/token",
    scopes={
        "read": "Read access to products and monitoring",
        "write": "Write access to products and monitoring", 
        "admin": "Administrative access"
    }
)

router = APIRouter(tags=["Authentication"])

# Dependency placeholders (set by main.py)
data_persistence_adapter = None
ticket_service = None
credit_service = None
oauth_service = None

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth_service: AuthService = Depends(get_auth_service)
) -> AuthContext:
    """Get current authenticated user from JWT token with IP and User-Agent validation"""
    try:
        token = credentials.credentials
        
        # Extract IP address and User-Agent from request
        ip_address, user_agent = get_request_metadata(request)
        
        auth_context = auth_service.get_auth_context(
            token,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        if not auth_context:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        return auth_context
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"}
        )

async def get_current_user_oauth2(
    request: Request,
    token: str = Depends(oauth2_scheme),
    auth_service: AuthService = Depends(get_auth_service)
) -> AuthContext:
    """Get current authenticated user from OAuth2 token with IP and User-Agent validation"""
    try:
        # Extract IP address and User-Agent from request
        ip_address, user_agent = get_request_metadata(request)
        
        auth_context = auth_service.get_auth_context(
            token,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        if not auth_context:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        return auth_context
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth2 authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"}
        )

# OAuth2 scheme for Swagger (optional, won't raise error if missing)
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/auth/token",
    auto_error=False,  # Don't raise error if token is missing
    scopes={
        "read": "Read access to products and monitoring",
        "write": "Write access to products and monitoring",
        "admin": "Administrative access"
    }
)

# Bearer token security for programmatic access (optional)
bearer_security_optional = HTTPBearer(auto_error=False)

async def get_current_user_swagger_compatible(
    request: Request,
    oauth2_token: Optional[str] = Depends(oauth2_scheme_optional),
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_security_optional),
    auth_service_instance: AuthService = Depends(get_auth_service)
) -> AuthContext:
    """
    Unified authentication dependency that works with both Swagger OAuth2 and Bearer tokens.
    
    This dependency supports:
    - OAuth2 tokens from Swagger UI (via oauth2_scheme_optional)
    - Bearer tokens for programmatic access (via bearer_security_optional)
    
    Tries OAuth2 token first (for Swagger UI), then falls back to Bearer token.
    Can be used by any route that requires authentication.
    
    Validates IP address and User-Agent against the session for security.
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
    
    # Extract IP address and User-Agent from request
    ip_address, user_agent = get_request_metadata(request)
    
    try:
        auth_context = auth_service_instance.get_auth_context(
            token, 
            ip_address=ip_address, 
            user_agent=user_agent
        )
        
        if not auth_context:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        return auth_context
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"}
        )
@require_read_db
@router.post("/login",
         summary="User Login",
         description="Authenticate user with email and password",
         response_model=ApiResponse,
         responses={
             200: {"description": "Login successful"},
             401: {"description": "Invalid credentials"}
         })
async def login(
    api_request: LoginRequestAPI,
    http_request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    _ = Depends(rbac.public())
):
    """
    ## User Login 🔐
    
    Authenticate a user with email and password.
    
    **Features:**
    - Email/password authentication
    - Account lockout protection
    - Session management
    - JWT token generation
    - Remember me functionality
    
    **Security:**
    - Password hashing with salt
    - Failed attempt tracking with progressive delay
    - IP-based rate limiting
    - Session-based authentication
    """
    try:
        ip_address, user_agent = get_request_metadata(http_request)

        # Progressive rate limiting
        from utils.middleware.progressive_rate_limiter import check_progressive_limit, record_attempt, reset_attempts
        prl_strategy = CONFIG.get("PRL_LOGIN", "")
        prl_identifier = f"{ip_address}:{api_request.email}"

        if prl_strategy:
            check = await check_progressive_limit("login", prl_identifier, prl_strategy)
            if not check.allowed:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "message": "Too many attempts. Please wait and try again.",
                        **check.to_error_dict(),
                    },
                )
            if check.requires_captcha:
                captcha_token = api_request.captcha_token or ""
                captcha_valid, _ = await validate_captcha(captcha_token, ip_address)
                if not captcha_valid:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail={
                            "message": "Invalid email or password",
                            **check.to_error_dict(),
                        },
                    )

        # Convert API request to domain model with metadata
        request = LoginRequest(
            email=api_request.email,
            password=api_request.password,
            remember_me=api_request.remember_me,
            ip_address=ip_address or "unknown",
            user_agent=user_agent
        )

        # Authenticate user
        response = auth_service.authenticate_user(request)

        if response.status == AuthStatus.SUCCESS and response.user and response.session:
            if prl_strategy:
                await reset_attempts("login", prl_identifier)

            return ApiResponse(
                success=True,
                message="Login successful",
                data={
                    "user": {
                        "id": response.user.id,
                        "username": response.user.username,
                        "email": response.user.email,
                        "full_name": response.user.full_name,
                        "role": response.user.role.value,
                        "is_verified": response.user.is_verified
                    },
                    "tokens": {
                        "access_token": response.access_token,
                        "refresh_token": response.refresh_token,
                        "token_type": "bearer",
                        "expires_in": response.expires_in
                    },
                    "session": {
                        "id": response.session.id,
                        "expires_at": response.session.expires_at.isoformat() if response.session.expires_at else None
                    }
                }
            )
        else:
            # Check if this is an OAuth-only account (no password set)
            if response.message and response.message.startswith("OAUTH_ONLY_ACCOUNT:"):
                providers = response.message.split(":", 1)[1].split(",")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "message": "This account uses external sign-in",
                        "code": "OAUTH_ONLY_ACCOUNT",
                        "providers": providers,
                    }
                )

            # Record failure and return next tier's requirements
            if prl_strategy:
                next_state = await record_attempt("login", prl_identifier, prl_strategy)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "message": "Invalid email or password",
                        **next_state.to_error_dict(),
                    }
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "message": "Invalid email or password",
                    }
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )

@router.post("/token",
         summary="OAuth2 Token (Login with Email)",
         description="Get OAuth2 token for Swagger UI authentication. IMPORTANT: In the 'username' field, enter your EMAIL address (not username). OAuth2 standard uses 'username' field name, but this API uses email for authentication.",
         response_model=Dict[str, Any],
         responses={
             200: {"description": "Token generated successfully"},
             401: {"description": "Invalid credentials"}
         })
async def oauth2_token(
    http_request: Request,
    form_data: OAuth2EmailPasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
    _ = Depends(rbac.public())
):
    """
    ## OAuth2 Token Endpoint 🔑
    
    Get OAuth2 token for Swagger UI authentication.
    This endpoint is used by Swagger UI to authenticate users.
    
    **Usage:**
    1. Click "Authorize" in Swagger UI
    2. Enter email and password
    3. Token will be automatically used for authenticated endpoints
    
    **Parameters (Form Data):**
    - `email` (required): User's email address
    - `password` (required): User's password
    - `grant_type` (optional): OAuth2 grant type (default: "password")
    - `scope` (optional): OAuth2 scopes
    """
    try:
        # Extract IP address and User-Agent from request headers
        ip_address, user_agent = get_request_metadata(http_request)
        
        # Create login request from OAuth2 form data with metadata
        login_request = LoginRequest(
            email=form_data.email,
            password=form_data.password,
            remember_me=False,
            ip_address=ip_address or "unknown",
            user_agent=user_agent
        )
        
        # Authenticate user
        response = auth_service.authenticate_user(login_request)
        
        if response.status == AuthStatus.SUCCESS and response.access_token:
            return {
                "access_token": response.access_token,
                "token_type": "bearer",
                "expires_in": response.expires_in
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth2 token error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token generation failed"
        )

@router.post("/register",
         summary="User Registration",
         description="Register a new user account",
         response_model=ApiResponse,
         responses={
             201: {"description": "User registered successfully"},
             400: {"description": "Invalid registration data"},
             409: {"description": "Email already exists"}
         })
async def register(
    api_request: RegisterRequestAPI,
    http_request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    _ = Depends(rbac.public())
):
    """
    ## User Registration 📝
    
    Register a new user account.
    
    **Features:**
    - Email validation
    - Password strength requirements
    - reCAPTCHA validation
    - Email verification (optional)
    - Role assignment
    - Username auto-generated from email
    
    **Requirements:**
    - Email: Valid email format
    - Password: Minimum 8 characters, letters and numbers
    - CAPTCHA: Valid CAPTCHA token (if enabled)
    - First name and last name are optional
    """
    try:
        # Validate CAPTCHA (configurable provider)
        ip_address, _ = get_request_metadata(http_request)
        captcha_token = api_request.captcha_token or ""
        
        logger.info("Registration attempt: email=%s, IP=%s", api_request.email, ip_address)
        captcha_valid, error_message = await validate_captcha(captcha_token, ip_address)
        
        if not captcha_valid:
            logger.info("Registration blocked: CAPTCHA validation failed for email=%s, IP=%s", api_request.email, ip_address)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message or "CAPTCHA validation failed. Please complete the CAPTCHA challenge."
            )
        
        logger.info("Registration CAPTCHA validated: email=%s, IP=%s", api_request.email, ip_address)
        
        # Convert API request to domain model
        request = RegisterRequest(
            email=api_request.email,
            password=api_request.password,
            first_name=api_request.first_name,
            last_name=api_request.last_name
        )
        
        response = auth_service.register_user(request)
        
        if response.status == AuthStatus.SUCCESS and response.user:
            # Grant initial credits to new user
            if credit_service:
                try:
                    credit_service.grant_registration_credits(response.user.id)
                except Exception as credit_error:
                    logger.error(f"Failed to grant registration credits to user {response.user.id}: {credit_error}")

            # Migrate guest tickets if ticket_service is available
            if ticket_service:
                try:
                    ticket_service.migrate_guest_tickets(response.user.email, response.user.id)
                except Exception as migration_error:
                    logger.error(f"Failed to migrate guest tickets for {response.user.email}: {migration_error}")

            # Verification token is sent via email, not in API response
            return ApiResponse(
                success=True,
                message=response.message or "User registered successfully",
                data={
                    "user": {
                        "id": response.user.id,
                        "username": response.user.username,
                        "email": response.user.email,
                        "full_name": response.user.full_name,
                        "role": response.user.role.value,
                        "is_verified": response.user.is_verified
                    }
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response.message or "Registration failed"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        from utils.validation.error_handling import sanitize_error_message
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=sanitize_error_message(e, "User registration")
        ) from e

@router.post("/refresh",
         summary="Refresh Token",
         description="Refresh access token using refresh token",
         response_model=ApiResponse,
         responses={
             200: {"description": "Token refreshed successfully"},
             401: {"description": "Invalid refresh token"}
         })
@require_write_db
async def refresh_token(
    body: RefreshTokenRequestAPI,
    auth_service: AuthService = Depends(get_auth_service),
    _ = Depends(rbac.public())
):
    """
    ## Refresh Token 🔄

    Refresh access token using refresh token.

    **Features:**
    - Token refresh without re-authentication
    - Automatic session validation
    - New access and refresh tokens
    """
    try:
        response = auth_service.refresh_token(body.refresh_token)
        
        if response and response.status == AuthStatus.SUCCESS:
            return ApiResponse(
                success=True,
                message="Token refreshed successfully",
                data={
                    "tokens": {
                        "access_token": response.access_token,
                        "refresh_token": response.refresh_token,
                        "token_type": "bearer",
                        "expires_in": response.expires_in
                    }
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )

@router.post("/logout",
         summary="User Logout",
         description="Logout user and invalidate session",
         response_model=ApiResponse,
         responses={
             200: {"description": "Logout successful"},
             401: {"description": "Invalid token"}
         })
async def logout(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    ## User Logout 🚪
    
    Logout user and invalidate current session.
    
    **Features:**
    - Session invalidation
    - Token blacklisting
    - Clean logout process
    - Graceful handling of invalid tokens
    """
    try:
        # Get authorization header
        auth_header = request.headers.get("Authorization")
        
        if not auth_header or not auth_header.startswith("Bearer "):
            # No token provided, still return success for logout
            return ApiResponse(
                success=True,
                message="Logout successful",
                data={}
            )
        
        # Extract token
        token = auth_header.split(" ")[1]
        
        # Try to get current user, but don't fail if token is invalid
        session_invalidated = False
        try:
            # Extract IP address and User-Agent from request
            ip_address, user_agent = get_request_metadata(request)

            current_user = auth_service.get_auth_context(
                token,
                ip_address=ip_address,
                user_agent=user_agent
            )
            if current_user and current_user.session:
                session_token = str(current_user.session.id)
                auth_service.logout_user(session_token)
                session_invalidated = True
        except Exception:
            pass

        # Fallback: if the access token was expired, decode without exp validation
        # to extract session_id and invalidate the session anyway
        if not session_invalidated:
            try:
                decoded = pyjwt.decode(
                    token,
                    CONFIG["JWT_SECRET"],
                    algorithms=[CONFIG["JWT_ALGORITHM"]],
                    options={"verify_exp": False}
                )
                session_id = decoded.get("session_id")
                if session_id:
                    auth_service.logout_user(str(session_id))
            except Exception:
                pass
        
        return ApiResponse(
            success=True,
            message="Logout successful",
            data={}
        )
            
    except Exception as e:
        logger.error(f"Logout error: {e}")
        # Even if there's an error, return success for logout
        return ApiResponse(
            success=True,
            message="Logout successful",
            data={}
        )

@router.post("/change-password",
         summary="Change Password",
         description="Change user password",
         response_model=ApiResponse,
         responses={
             200: {"description": "Password changed successfully"},
             400: {"description": "Invalid password data"},
             401: {"description": "Unauthorized"}
         })
@require_write_db
async def change_password(
    request: ChangePasswordRequest,
    current_user: AuthContext = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    ## Change Password 🔒
    
    Change user password.
    
    **Features:**
    - Current password verification
    - Password strength validation
    - Session invalidation for security
    """
    try:
        response = auth_service.change_password(current_user.user.id, request)
        
        if response.status == AuthStatus.SUCCESS:
            return ApiResponse(
                success=True,
                message=response.message or "Password changed successfully",
                data={}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response.message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Change password error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed"
        )

@router.post("/request-password-reset",
         summary="Request Password Reset",
         description="Request password reset via email",
         response_model=ApiResponse,
         responses={
             200: {"description": "Reset request sent"},
             400: {"description": "Invalid email"}
         })
@require_write_db
async def request_password_reset(
    api_request: PasswordResetRequestAPI,
    http_request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    _ = Depends(rbac.public())
):
    """
    ## Request Password Reset 📧
    
    Request password reset via email.
    
    **Features:**
    - Email validation
    - CAPTCHA validation (if enabled)
    - Secure reset token generation
    - Email delivery (implementation required)
    """
    try:
        # Validate CAPTCHA (configurable provider)
        ip_address, _ = get_request_metadata(http_request)
        captcha_token = api_request.captcha_token or ""
        
        logger.info("Password reset request attempt: email=%s, IP=%s", api_request.email, ip_address)
        captcha_valid, error_message = await validate_captcha(captcha_token, ip_address)
        
        if not captcha_valid:
            logger.info("Password reset request blocked: CAPTCHA validation failed for email=%s, IP=%s", api_request.email, ip_address)
            # Raise HTTPException - will be caught by except HTTPException and re-raised
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message or "CAPTCHA validation failed. Please complete the CAPTCHA challenge."
            )
        
        logger.info("Password reset request CAPTCHA validated: email=%s, IP=%s", api_request.email, ip_address)
        
        # Convert API request to domain model
        request = PasswordResetRequest(email=api_request.email)
        response = auth_service.request_password_reset(request)
        
        return ApiResponse(
            success=True,
            message=response.message or "Password reset request sent",
            data={}
        )
        
    except HTTPException as http_ex:
        # Re-raise HTTPExceptions (like CAPTCHA validation failures) with their original status code
        raise http_ex
    except Exception as e:
        logger.error(f"Password reset request error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset request failed"
        )

@router.post("/reset-password",
         summary="Reset Password",
         description="Reset password using reset token from email link",
         response_model=ApiResponse,
         responses={
             200: {"description": "Password reset successful"},
             400: {"description": "Invalid reset token or weak password"}
         })
@require_write_db
async def reset_password(
    api_request: ResetPasswordRequestAPI,
    http_request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    _ = Depends(rbac.public())
):
    """
    ## Reset Password 🔑
    
    Reset password using reset token from email link.
    
    **Flow:**
    1. User clicks reset link from email: `DOMAIN_UI/account/reset-password?token=xxx`
    2. UI extracts token from URL
    3. UI calls this endpoint with token and new password
    4. Backend validates token, updates password, invalidates all sessions
    
    **Features:**
    - Token validation (verifies hash against stored salt)
    - Password strength validation
    - Secure password update (hashed with new salt)
    - Session invalidation (forces re-login)
    - CAPTCHA validation (if enabled)
    """
    try:
        # Validate CAPTCHA (configurable provider)
        ip_address, _ = get_request_metadata(http_request)
        captcha_token = api_request.captcha_token or ""
        
        logger.info("Password reset attempt: IP=%s", ip_address)
        captcha_valid, error_message = await validate_captcha(captcha_token, ip_address)
        
        if not captcha_valid:
            logger.info("Password reset blocked: CAPTCHA validation failed for IP=%s", ip_address)
            # Raise HTTPException - will be caught by except HTTPException and re-raised
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message or "CAPTCHA validation failed. Please complete the CAPTCHA challenge."
            )
        
        logger.info("Password reset CAPTCHA validated: IP=%s", ip_address)
        
        success = auth_service.reset_password(api_request.token, api_request.new_password)
        
        if success:
            return ApiResponse(
                success=True,
                message="Password reset successful. Please log in with your new password.",
                data={}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token, or password does not meet strength requirements"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password reset error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset failed"
        )

@router.get("/me",
         summary="Get Current User",
         description="Get current authenticated user information",
         response_model=ApiResponse,
         responses={
             200: {"description": "User information retrieved"},
             401: {"description": "Unauthorized"}
         })
async def get_current_user_info(
    current_user: AuthContext = Depends(get_current_user_swagger_compatible)
):
    """
    ## Get Current User 👤
    
    Get current authenticated user information.
    
    **Features:**
    - User profile information
    - Account status
    - Role and permissions
    """
    try:
        return ApiResponse(
            success=True,
            message="User information retrieved",
            data={
                "user": {
                    "id": current_user.user.id,
                    "username": current_user.user.username,
                    "email": current_user.user.email,
                    "full_name": current_user.user.full_name,
                    "role": current_user.user.role.value,
                    "is_verified": current_user.user.is_verified,
                    "is_active": current_user.user.is_active,
                    "max_products": current_user.user.max_products,
                    "api_rate_limit": current_user.user.api_rate_limit,
                    "created_at": current_user.user.created_at.isoformat() if current_user.user.created_at else None,
                    "last_login": current_user.user.last_login.isoformat() if current_user.user.last_login else None
                },
                "session": {
                    "id": current_user.session.id if current_user.session else None,
                    "expires_at": current_user.session.expires_at.isoformat() if current_user.session and current_user.session.expires_at else None
                } if current_user.session else None
            }
        )
        
    except Exception as e:
        logger.error(f"Get user info error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user information"
        )

@router.post("/api-keys",
         summary="Create API Key",
         description="Create a new API key for programmatic access",
         response_model=ApiResponse,
         responses={
             201: {"description": "API key created successfully"},
             400: {"description": "Invalid API key data"},
             401: {"description": "Unauthorized"}
         })
async def create_api_key(
    request: CreateApiKeyRequest,
    current_user: AuthContext = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    ## Create API Key 🔑
    
    Create a new API key for programmatic access.
    
    **Features:**
    - Custom key naming
    - Permission scoping
    - Rate limiting
    - Expiration dates
    """
    try:
        response = auth_service.create_api_key(current_user.user.id, request)
        
        if response.status == AuthStatus.SUCCESS and response.api_key:
            return ApiResponse(
                success=True,
                message="API key created successfully",
                data={
                    "api_key": {
                        "id": response.api_key.id,
                        "key_name": response.api_key.key_name,
                        "key_prefix": response.api_key.key_prefix,
                        "permissions": response.api_key.permissions,
                        "rate_limit": response.api_key.rate_limit,
                        "expires_at": response.api_key.expires_at.isoformat() if response.api_key.expires_at else None
                    },
                    "full_key": getattr(response, 'full_key', None)  # Add full_key if available
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=response.message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create API key error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key creation failed"
        )

@router.get("/api-keys",
         summary="List API Keys",
         description="List all API keys for current user",
         response_model=ApiResponse,
         responses={
             200: {"description": "API keys retrieved"},
             401: {"description": "Unauthorized"}
         })
async def list_api_keys(
    current_user: AuthContext = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    ## List API Keys 📋
    
    List all API keys for current user.
    
    **Features:**
    - Key information (without full key)
    - Usage statistics
    - Status and expiration
    """
    try:
        # This would be implemented in the auth service
        api_keys = []  # Placeholder
        
        return ApiResponse(
            success=True,
            message="API keys retrieved",
            data={
                "api_keys": api_keys
            }
        )
        
    except Exception as e:
        logger.error(f"List API keys error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve API keys"
        )

class VerifyEmailRequest(BaseModel):
    """Request model for email verification"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "verification_token_from_email",
                "captcha_token": "03AGdBq24..."
            }
        }
    )
    
    token: str
    captcha_token: Optional[str] = None


@router.post("/verify",
         summary="Verify Email",
         description="Verify user email using verification token from email link",
         response_model=ApiResponse,
         responses={
             200: {"description": "Email verified successfully"},
             400: {"description": "Invalid or expired token"}
         })
@require_write_db
async def verify_email(
    request: VerifyEmailRequest,
    http_request: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    ## Verify Email ✅
    
    Verify a user's email address using a verification token.
    
    **Usage:**
    1. User receives email with verification link (e.g., `https://app.example.com/verify?token=...`)
    2. User clicks link → opens UI verification page
    3. UI extracts token from URL and sends POST request with token in body
    4. System verifies token and sets `is_verified` to `True`
    
    **Security:**
    - POST method prevents token exposure in server logs and browser history
    - CAPTCHA validation (if enabled)
    - Token-based verification (secure)
    - Token expires after 7 days
    - Token can only be used once
    
    **Note:** The email link should point to a UI page that handles the POST request,
    not directly to this API endpoint.
    """
    try:
        if not request.token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token"  # Generic message
            )
        
        # Validate CAPTCHA (configurable provider)
        ip_address, _ = get_request_metadata(http_request)
        captcha_token = request.captcha_token or ""
        
        logger.info("Email verification attempt: IP=%s", ip_address)
        captcha_valid, error_message = await validate_captcha(captcha_token, ip_address)
        
        if not captcha_valid:
            logger.info("Email verification blocked: CAPTCHA validation failed, IP=%s", ip_address)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message or "CAPTCHA validation failed. Please complete the CAPTCHA challenge."
            )
        
        logger.info("Email verification CAPTCHA validated: IP=%s", ip_address)
        
        # Verify email using token (returns user_id on success)
        user_id = auth_service.verify_email(request.token)
        
        if not user_id:
            # Generic error message - don't reveal why it failed
            # (invalid, expired, already used, etc.)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token"
            )
        
        return ApiResponse(
            success=True,
            message="Email verified successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Email verification error: %s", e)
        # Generic error - don't reveal internal errors
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token"
        ) from e


@router.post("/resend-verification",
         summary="Resend Verification Email",
         description="Request a new verification email for the authenticated user",
         response_model=ApiResponse,
         responses={
             200: {"description": "Verification email sent"},
             400: {"description": "Email already verified"},
             401: {"description": "Authentication required"},
             429: {"description": "Too many requests - rate limited"}
         })
@require_write_db
async def resend_verification_email(
    request: Request,
    current_user: AuthContext = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    ## Resend Verification Email 📧
    
    Request a new verification email for the currently authenticated user.
    
    **Usage:**
    - User must be logged in
    - A new verification email is sent to the user's registered email address
    - Previous verification tokens are invalidated
    
    **Security:**
    - Requires authentication (Bearer token)
    - Only sends to the authenticated user's own email
    - Rate limited to prevent abuse
    - Invalidates previous tokens when new one is generated
    """
    try:
        # Check if already verified
        if current_user.user.is_verified:
            return ApiResponse(
                success=False,
                message="Email is already verified"
            )

        # Progressive rate limiting
        from utils.middleware.progressive_rate_limiter import check_progressive_limit, record_attempt, reset_attempts
        ip_address, _ = get_request_metadata(request)
        identifier = current_user.user.email
        prl_strategy = CONFIG.get("PRL_RESEND_VERIFICATION", "")

        if prl_strategy:
            check = await check_progressive_limit("resend_verification", identifier, prl_strategy)
            if not check.allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=check.to_error_dict(),
                )
            # If CAPTCHA required at this tier, the frontend must handle it
            # (for now, just record the attempt — CAPTCHA enforcement can be added later)

        # Use the authenticated user's email
        user_email = current_user.user.email

        # Record the attempt before processing
        if prl_strategy:
            await record_attempt("resend_verification", identifier)

        # Process the request
        auth_service.request_verification_email(user_email)

        return ApiResponse(
            success=True,
            message="Verification email has been sent to your registered email address."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Resend verification email error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email"
        ) from e


# --- OAuth Helpers ---

def _format_oauth_response(response) -> ApiResponse:
    """Format a successful OAuth LoginResponse into an ApiResponse."""
    if response.status == AuthStatus.SUCCESS and response.user and response.session:
        return ApiResponse(
            success=True,
            message="Login successful",
            data={
                "action": "logged_in",
                "user": {
                    "id": response.user.id,
                    "username": response.user.username,
                    "email": response.user.email,
                    "full_name": response.user.full_name,
                    "role": response.user.role.value,
                    "is_verified": response.user.is_verified,
                },
                "tokens": {
                    "access_token": response.access_token,
                    "refresh_token": response.refresh_token,
                    "token_type": "bearer",
                    "expires_in": response.expires_in,
                },
                "session": {
                    "id": response.session.id,
                    "expires_at": response.session.expires_at.isoformat() if response.session.expires_at else None,
                },
            }
        )
    elif response.status == AuthStatus.LINK_REQUIRED and response.link_data:
        return ApiResponse(
            success=True,
            message=response.message or "Account linking required",
            data={
                "action": "link_required",
                "link_data": response.link_data,
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=response.message or "Authentication failed"
        )


# --- Google OAuth ---

class GoogleOAuthRequestAPI(BaseModel):
    """API request model for Google OAuth login."""
    model_config = ConfigDict(strict=True)
    token: str = Field(default="", max_length=5000, description="Google access token or ID token")
    id_token: str = Field(default="", max_length=5000, description="Google ID token (legacy, use 'token' instead)")


@router.post("/oauth/google",
    summary="Google OAuth Login",
    description="Authenticate or register with a Google ID token",
    response_model=ApiResponse,
    responses={
        200: {"description": "Login successful"},
        401: {"description": "Invalid Google token"},
        503: {"description": "Google login not configured"},
    })
async def google_oauth_login(
    api_request: GoogleOAuthRequestAPI,
    http_request: Request,
    _ = Depends(rbac.public()),
):
    """
    ## Google OAuth Login

    Authenticate or register a user with a Google ID token obtained from
    Google Sign-In (GSI) on the frontend.

    **Flow:**
    - Verifies the ID token server-side with Google
    - If the Google account is already linked → logs in
    - If email matches an existing user → auto-links and logs in
    - If new email → creates a new verified user and logs in

    **Returns:** Same response shape as POST /auth/login
    """
    if not oauth_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google login is not configured"
        )

    try:
        ip_address, user_agent = get_request_metadata(http_request)

        # Accept token from either field (new 'token' or legacy 'id_token')
        google_token = api_request.token or api_request.id_token
        if not google_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either 'token' or 'id_token' is required"
            )

        response = oauth_service.authenticate_with_google(
            id_token=google_token,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return _format_oauth_response(response)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Google OAuth login error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google authentication failed"
        ) from e


class OAuthConfirmLinkRequest(BaseModel):
    """Request to confirm OAuth account linking with password.
    Mirrors the login flow: progressive delay, per-IP tracking, CAPTCHA gate."""
    model_config = ConfigDict(strict=True)
    link_token: str = Field(..., max_length=5000, description="Signed link token from the LINK_REQUIRED response")
    password: str = Field(..., min_length=1, max_length=200, description="Password for the existing account")
    captcha_token: Optional[str] = Field(None, max_length=5000, description="CAPTCHA token when required after failed attempts")


@router.post("/oauth/confirm-link",
    summary="Confirm OAuth Account Link",
    description="Complete OAuth account linking by providing the existing account's password. "
                "Same brute-force protection as login: progressive delay + CAPTCHA after threshold.",
    response_model=ApiResponse,
    responses={
        200: {"description": "Account linked and login successful"},
        400: {"description": "Incorrect password, CAPTCHA required, or link expired"},
        503: {"description": "OAuth not configured"},
    })
@require_write_db
async def confirm_oauth_link(
    api_request: OAuthConfirmLinkRequest,
    http_request: Request,
    _ = Depends(rbac.public()),
):
    """
    ## Confirm OAuth Account Link

    Same protection as POST /auth/login:
    - Per-account progressive delay (built into authenticate_user)
    - Per-IP failure tracking in Redis
    - CAPTCHA required after threshold failures
    - Returns `captcha_required: true` so the frontend can show the widget
    """
    if not oauth_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth is not configured"
        )

    try:
        ip_address, user_agent = get_request_metadata(http_request)

        # Progressive rate limiting (same pattern as login)
        from utils.middleware.progressive_rate_limiter import check_progressive_limit, record_attempt, reset_attempts
        prl_strategy = CONFIG.get("PRL_CONFIRM_LINK", "")
        prl_identifier = f"{ip_address}:{api_request.link_token[:32]}"

        if prl_strategy:
            check = await check_progressive_limit("confirm_link", prl_identifier, prl_strategy)
            if not check.allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": "Too many attempts. Please wait and try again.",
                        **check.to_error_dict(),
                    },
                )
            # If CAPTCHA required at this tier, validate it
            if check.requires_captcha:
                captcha_token = api_request.captcha_token or ""
                captcha_valid, _ = await validate_captcha(captcha_token, ip_address)
                if not captcha_valid:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=check.to_error_dict(),
                    )

        # Authenticate
        response = oauth_service.confirm_link_with_password(
            link_token=api_request.link_token,
            password=api_request.password,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        if response.status == AuthStatus.SUCCESS and response.user and response.session:
            if prl_strategy:
                await reset_attempts("confirm_link", prl_identifier)
            return _format_oauth_response(response)
        else:
            # Record failure and return the next tier's requirements
            if prl_strategy:
                next_state = await record_attempt("confirm_link", prl_identifier, prl_strategy)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": response.message or "Incorrect password",
                        **next_state.to_error_dict(),
                    }
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=response.message or "Incorrect password"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("OAuth confirm link error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account linking failed"
        ) from e


# --- GitHub OAuth ---

class GitHubOAuthRequestAPI(BaseModel):
    """API request model for GitHub OAuth login."""
    model_config = ConfigDict(strict=True)
    code: str = Field(..., max_length=200, description="GitHub authorization code from OAuth redirect")


@router.post("/oauth/github",
    summary="GitHub OAuth Login",
    description="Authenticate or register with a GitHub authorization code",
    response_model=ApiResponse,
    responses={
        200: {"description": "Login successful"},
        401: {"description": "Invalid GitHub code"},
        503: {"description": "GitHub login not configured"},
    })
async def github_oauth_login(
    api_request: GitHubOAuthRequestAPI,
    http_request: Request,
    _ = Depends(rbac.public()),
):
    """
    ## GitHub OAuth Login

    Authenticate or register a user with a GitHub authorization code.
    The frontend redirects to GitHub, gets a code, and sends it here.
    The backend exchanges it for an access token and fetches the user profile.
    """
    if not oauth_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth is not configured"
        )

    # Check if GitHub verifier is registered
    if not oauth_service._verifiers.get("github"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub login is not configured"
        )

    try:
        ip_address, user_agent = get_request_metadata(http_request)

        response = oauth_service.authenticate_with_oauth(
            provider="github",
            token=api_request.code,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return _format_oauth_response(response)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("GitHub OAuth login error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub authentication failed"
        ) from e


# --- Facebook OAuth ---

class FacebookOAuthRequestAPI(BaseModel):
    """API request model for Facebook OAuth login."""
    model_config = ConfigDict(strict=True)
    code: str = Field(..., max_length=2000, description="Facebook authorization code from OAuth redirect")
    redirect_uri: str = Field(..., max_length=500, description="Redirect URI used in the authorization request")


@router.post("/oauth/facebook",
    summary="Facebook OAuth Login",
    description="Authenticate or register with a Facebook authorization code",
    response_model=ApiResponse,
    responses={
        200: {"description": "Login successful"},
        401: {"description": "Invalid Facebook code"},
        503: {"description": "Facebook login not configured"},
    })
async def facebook_oauth_login(
    api_request: FacebookOAuthRequestAPI,
    http_request: Request,
    _ = Depends(rbac.public()),
):
    """
    ## Facebook OAuth Login

    Authenticate or register a user with a Facebook authorization code.
    The frontend redirects to Facebook, gets a code, and sends it here.
    The backend exchanges it for an access token and fetches the user profile.
    """
    if not oauth_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth is not configured"
        )

    fb_verifier = oauth_service._verifiers.get("facebook")
    if not fb_verifier:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Facebook login is not configured"
        )

    try:
        ip_address, user_agent = get_request_metadata(http_request)

        response = oauth_service.authenticate_with_oauth(
            provider="facebook",
            token=api_request.code,
            ip_address=ip_address,
            redirect_uri=api_request.redirect_uri,
            user_agent=user_agent,
        )

        return _format_oauth_response(response)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Facebook OAuth login error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Facebook authentication failed"
        ) from e
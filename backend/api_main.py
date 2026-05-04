#!/usr/bin/env python3
"""
Phoveus API

A FastAPI-based SaaS backend service.

Architecture:
- Hexagonal architecture (ports & adapters)
- Dependency injection
- Modular route organization
- Service layer abstraction
"""

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
import uvicorn
import logging
import time
import sys
import click
import os
import asyncio
from typing import Dict, Any
import argparse

# Import route modules
from routes.main import create_main_router, setup_routes

# Import core dependencies
from adapters.database_persistence import DatabaseDataPersistenceAdapter
from config import set_database_url, CONFIG, settings
from datetime import datetime
from utils.request import get_client_ip
import os
import uuid
import json

# Configure structured JSON logging before anything else logs
from utils.logging_config import configure_logging
configure_logging(CONFIG.get("LOG_LEVEL", "info"), CONFIG.get("LOG_OUTPUT", "both"), CONFIG.get("LOG_FORMAT", "json"))

# Attach per-request context filter to every handler so child logger records get enriched
from utils.logging_context import ContextFilter, LogContextMiddleware
_ctx_filter = ContextFilter()
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_ctx_filter)

# Load environment variables once at module level for efficiency
JWT_SECRET = CONFIG["JWT_SECRET"]
JWT_ALGORITHM = CONFIG["JWT_ALGORITHM"]
JWT_ACCESS_TOKEN_EXPIRY = CONFIG["JWT_ACCESS_TOKEN_EXPIRY"]
JWT_REFRESH_TOKEN_EXPIRY = CONFIG["JWT_REFRESH_TOKEN_EXPIRY"]
RATE_LIMIT_ENABLED = CONFIG["RATE_LIMIT_ENABLED"]
RATE_LIMIT_BYPASS_KEY = CONFIG["RATE_LIMIT_BYPASS_KEY"]
RATE_LIMIT_REQUESTS = CONFIG["RATE_LIMIT_REQUESTS"]
RATE_LIMIT_WINDOW = CONFIG["RATE_LIMIT_WINDOW"]

# Global variables for service management
_services: Dict[str, Any] = {}
_services_initialized = False

logger = logging.getLogger(__name__)

# Helper function to log errors with structured extra fields
def log_error_with_id(error_id: str, error_type: str, error_data: dict, concise_message: str):
    """Log error with structured fields (written to both stream and rotating error log via root handlers)."""
    log_level = logging.WARNING if error_data.get('status_code', 500) < 500 else logging.ERROR
    logger.log(
        log_level,
        concise_message,
        extra={
            "error_id": error_id,
            "error_type": error_type,
            "http.status_code": error_data.get("status_code"),
            "http.method": error_data.get("method"),
            "http.path": error_data.get("path"),
            "error.detail": error_data.get("error_message"),
        },
    )

# Database initialization functions are now centralized in utils.database.operations
# Use: from utils.database import init_database, seed_database, reset_database

# Database operations are now centralized in utils.database.operations
# Import them if needed:
# from utils.database import clear_database, init_database, seed_database, reset_database



# Import centralized database connection info functions
from utils.database.connection_info import display_detailed_connection_info


# Import centralized database schema validation
from utils.database.schema_validation import validate_database_schema


# Removed display_command_args function - now using display_main_params


def initialize_services():
    """Initialize all service instances once at startup"""
    global _services, _services_initialized
    
    if _services_initialized:
        return _services
    
    logger.info("Initializing services...")

    # JWT secret safety check — refuse to start in production with the default secret
    _default_jwt_secret = "your-super-secret-jwt-key-here-change-this-in-production"
    if CONFIG.get("JWT_SECRET") == _default_jwt_secret:
        is_production = os.getenv("PHOVEU_PRODUCTION", "").lower() in ("true", "1", "yes")
        if is_production:
            logger.critical(
                "REFUSING TO START: JWT_SECRET is still the default value. "
                "Set PHOVEU_BACKEND_JWT_SECRET to a secure random string before running in production."
            )
            raise SystemExit(1)
        else:
            logger.warning(
                "JWT_SECRET is the default value — acceptable for development only. "
                "Set PHOVEU_BACKEND_JWT_SECRET before deploying to production."
            )

    # Schema validation is now done in main() before FastAPI starts
    logger.info("✅ Database schema validated before startup")
    
    # Initialize adapters
    data_persistence_adapter = DatabaseDataPersistenceAdapter(
        auto_init=True,
    )
    
    # Initialize authentication adapter
    auth_persistence_adapter = None
    try:
        from adapters.auth_persistence import AuthPersistenceAdapter
        
        auth_persistence_adapter = AuthPersistenceAdapter(jwt_secret=JWT_SECRET)
        logger.info("✅ Authentication adapter initialized")
    except Exception as e:
        logger.warning(f"⚠️  Authentication adapter not available: {e}")
    
    # Initialize password hasher adapter
    from adapters.password_hasher import PBKDF2PasswordHasher
    password_hasher = PBKDF2PasswordHasher()

    # Initialize authentication service
    auth_service = None
    if auth_persistence_adapter:
        try:
            from domain.services.auth_service import AuthService

            auth_service = AuthService(
                auth_port=auth_persistence_adapter,
                user_management_port=auth_persistence_adapter,
                session_management_port=auth_persistence_adapter,
                api_key_management_port=auth_persistence_adapter,
                authorization_port=auth_persistence_adapter,
                password_hasher=password_hasher,
                jwt_secret=JWT_SECRET,
                jwt_algorithm=JWT_ALGORITHM,
                access_token_expiry=JWT_ACCESS_TOKEN_EXPIRY,
                refresh_token_expiry=JWT_REFRESH_TOKEN_EXPIRY
            )
            logger.info("✅ Authentication service initialized")
        except Exception as e:
            logger.warning(f"⚠️  Authentication service not available: {e}")

    # Initialize OAuth service (Google login)
    oauth_service = None
    google_client_id = CONFIG.get("GOOGLE_CLIENT_ID", "")
    if auth_persistence_adapter and google_client_id:
        try:
            from adapters.persistence.oauth_persistence import OAuthPersistenceAdapter
            from adapters.google_token_verifier import GoogleTokenVerifier
            from domain.services.oauth_service import OAuthService

            oauth_persistence_adapter = OAuthPersistenceAdapter()
            google_verifier = GoogleTokenVerifier(client_id=google_client_id)
            oauth_service = OAuthService(
                oauth_port=oauth_persistence_adapter,
                auth_port=auth_persistence_adapter,
                user_management_port=auth_persistence_adapter,
                session_management_port=auth_persistence_adapter,
                google_verifier=google_verifier,
                jwt_secret=JWT_SECRET,
                jwt_algorithm=JWT_ALGORITHM,
                access_token_expiry=JWT_ACCESS_TOKEN_EXPIRY,
                refresh_token_expiry=JWT_REFRESH_TOKEN_EXPIRY,
            )
            logger.info("✅ OAuth service initialized (Google login enabled)")
        except Exception as e:
            logger.warning(f"⚠️  OAuth service not available: {e}")

    # Register GitHub verifier if configured
    github_client_id = CONFIG.get("GITHUB_CLIENT_ID", "")
    github_client_secret = CONFIG.get("GITHUB_CLIENT_SECRET", "")
    if oauth_service and github_client_id and github_client_secret:
        try:
            from adapters.github_token_verifier import GitHubTokenVerifier
            github_verifier = GitHubTokenVerifier(
                client_id=github_client_id,
                client_secret=github_client_secret,
            )
            oauth_service._verifiers["github"] = github_verifier
            logger.info("✅ GitHub OAuth verifier registered")
        except Exception as e:
            logger.warning(f"⚠️  GitHub OAuth verifier not available: {e}")

    # Register Facebook verifier if configured
    fb_app_id = CONFIG.get("FACEBOOK_APP_ID", "")
    fb_app_secret = CONFIG.get("FACEBOOK_APP_SECRET", "")
    if oauth_service and fb_app_id and fb_app_secret:
        try:
            from adapters.facebook_token_verifier import FacebookTokenVerifier
            facebook_verifier = FacebookTokenVerifier(
                app_id=fb_app_id,
                app_secret=fb_app_secret,
            )
            oauth_service._verifiers["facebook"] = facebook_verifier
            logger.info("✅ Facebook OAuth verifier registered")
        except Exception as e:
            logger.warning(f"⚠️  Facebook OAuth verifier not available: {e}")

    # Initialize event config service (in-memory cache for event config matrix)
    from adapters.persistence.event_config_persistence import EventConfigAdapter
    from domain.services.event_config_service import EventConfigService
    event_config_adapter = EventConfigAdapter()
    event_config_service = EventConfigService(config_port=event_config_adapter)
    event_config_service.load()

    # Initialize app config adapter (raw namespace/key/value + scope CRUD)
    from adapters.persistence.app_config_persistence import AppConfigAdapter
    app_config_adapter = AppConfigAdapter()

    # Initialize config adapters + service for the typed admin config feature
    # (global-scope read/write + snapshot history). ConfigService preloads
    # the cache from DB so first-request reads don't pay a round trip.
    from adapters.persistence.config_persistence import ConfigAdapter
    from adapters.persistence.config_snapshot_persistence import ConfigSnapshotAdapter
    from domain.services.config_service import ConfigService
    config_adapter = ConfigAdapter()
    config_snapshot_adapter = ConfigSnapshotAdapter()
    config_service = ConfigService(
        config_port=config_adapter,
        snapshot_port=config_snapshot_adapter,
    )
    config_service.load()

    # Initialize notification queue (Redis-backed, for async email delivery)
    notification_queue = None
    if CONFIG.get("NOTIFICATION_QUEUE_ENABLED", True):
        from adapters.notification_queue.redis_queue import RedisNotificationQueueAdapter
        notification_queue = RedisNotificationQueueAdapter()
        logger.info("Notification queue enabled (Redis-backed)")
    else:
        logger.info("Notification queue disabled — emails will be sent synchronously")

    # Configure hook manager with dependencies (before any events fire)
    from ports.hooks import hook_manager
    hook_manager.configure(
        data_persistence=data_persistence_adapter,
        event_config_service=event_config_service,
        notification_queue=notification_queue,
    )

    # Initialize ticket service
    from domain.services.ticket_service import TicketService
    ticket_service = TicketService(
        data_port=data_persistence_adapter,
        hook_manager=hook_manager
    )
    
    # Initialize credit service
    from domain.services.credit_service import CreditService
    credit_service = CreditService(data_persistence_adapter=data_persistence_adapter, hook_manager=hook_manager)

    # Inject credit_service into OAuth service (created earlier, before credit_service was available)
    if oauth_service and credit_service:
        oauth_service.credit_service = credit_service
    
    # Initialize payment service
    from adapters.paypal_payment import PayPalPaymentAdapter
    from adapters.stripe_payment import StripePaymentAdapter
    from domain.services.payment_service import PaymentService
    from domain.entities.billing_models import PaymentProvider
    
    # Load gateway configs from database
    gateway_configs = {}
    try:
        configs = data_persistence_adapter.get_payment_gateway_configs()
        for config in configs:
            gateway_configs[config.provider] = {
                'api_key': config.api_key,
                'api_secret': config.api_secret,
                'webhook_secret': config.webhook_secret,
                'mode': config.mode,
                'config_json': config.config_json
            }
        logger.info(f"✅ Loaded {len(configs)} payment gateway configs from database")
    except Exception as e:
        logger.warning(f"⚠️  Could not load payment gateway configs from database: {e}")
    
    # Initialize adapters with database configs (fallback to env vars if not in DB)
    paypal_config = gateway_configs.get(PaymentProvider.PAYPAL)
    stripe_config = gateway_configs.get(PaymentProvider.STRIPE)
    
    paypal_adapter = PayPalPaymentAdapter(config=paypal_config)
    stripe_adapter = StripePaymentAdapter(config=stripe_config)
    
    payment_service = PaymentService(
        data_persistence_adapter=data_persistence_adapter,
        paypal_gateway=paypal_adapter,
        stripe_gateway=stripe_adapter,
        credit_service=credit_service,
        gateway_configs=gateway_configs,
        hook_manager=hook_manager,
    )
    
    # Initialize RBAC adapter (port implementation)
    from adapters.rbac_adapter import RBACAdapter
    from utils.database.database_session import get_db_session
    rbac_adapter = RBACAdapter(session_factory=get_db_session)
    logger.info("RBAC adapter initialized")

    _services = {
        "data_persistence_adapter": data_persistence_adapter,
        "auth_service": auth_service,
        "ticket_service": ticket_service,
        "payment_service": payment_service,
        "credit_service": credit_service,
        "rbac_adapter": rbac_adapter,
        "event_config_service": event_config_service,
        "notification_queue": notification_queue,
        "app_config_adapter": app_config_adapter,
        "config_adapter": config_adapter,
        "config_snapshot_adapter": config_snapshot_adapter,
        "config_service": config_service,
        "oauth_service": oauth_service,
    }
    
    _services_initialized = True
    logger.info("Services initialized successfully")
    
    return _services

# Services are now accessed directly through dependency injection in setup_routes()

def _patch_uvicorn_invalid_http_logging():
    """Monkey-patch uvicorn's httptools protocol to log the raw bytes on invalid HTTP requests."""
    try:
        from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
        _original_data_received = HttpToolsProtocol.data_received

        def _patched_data_received(self, data):
            try:
                return _original_data_received(self, data)
            except Exception:
                # The original already handles it — we just want to log before it does
                pass

        # Instead of patching data_received (complex), patch at the logger level
        import logging as _logging
        _uvicorn_logger = _logging.getLogger("uvicorn.error")
        _original_warning = _uvicorn_logger.warning

        def _verbose_warning(msg, *args, **kwargs):
            if msg == "Invalid HTTP request received.":
                # Get the raw data from the current frame
                import traceback
                frame = None
                try:
                    import sys
                    frame = sys._getframe(1)
                    raw_data = frame.f_locals.get("data", b"")
                    peer = getattr(frame.f_locals.get("self", None), "_addr", ("?", "?"))
                    preview = raw_data[:200] if isinstance(raw_data, bytes) else str(raw_data)[:200]
                    _original_warning(
                        "Invalid HTTP request from %s — first 200 bytes: %s",
                        peer, preview
                    )
                    return
                except Exception:
                    pass
            return _original_warning(msg, *args, **kwargs)

        _uvicorn_logger.warning = _verbose_warning
        logger.info("Patched uvicorn to log raw bytes on invalid HTTP requests")
    except Exception as e:
        logger.warning("Could not patch uvicorn invalid HTTP logging: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Phoveus API")
    _patch_uvicorn_invalid_http_logging()

    # Initialise Redis (shared state for rate limiter, CAPTCHA trust, guest limits)
    from utils.redis_client import init_redis, close_redis
    await init_redis()

    # Initialize services once at startup
    services = initialize_services()
    
    # Setup routes with dependency injection
    setup_routes(
        data_persistence_adapter=services["data_persistence_adapter"],
        auth_service=services.get("auth_service"),
        ticket_service=services.get("ticket_service"),
        payment_service=services.get("payment_service"),
        credit_service=services.get("credit_service"),
        rbac_port=services.get("rbac_adapter"),
        event_config_service=services.get("event_config_service"),
        notification_queue=services.get("notification_queue"),
        app_config_adapter=services.get("app_config_adapter"),
        oauth_service=services.get("oauth_service"),
        config_service=services.get("config_service"),
    )
    
    logger.info("Services initialized and routes configured successfully")

    # Auto-seed RBAC roles/permissions and payment gateways if missing
    try:
        adapter = services["data_persistence_adapter"]
        adapter.seed_database()
    except Exception as e:
        logger.warning(f"Auto-seed on startup failed (non-fatal): {e}")

    # Start background maintenance task (event config refresh + Redis reconnection)
    async def run_background_maintenance():
        interval = 300  # Background maintenance interval in seconds (5 mins)
        logger.info(f"Background maintenance task started (interval: {interval}s)")

        while True:
            # Refresh event config cache
            try:
                event_config_svc = services.get("event_config_service")
                if event_config_svc:
                    event_config_svc.refresh()
            except Exception as e:
                logger.error(f"Event config refresh failed: {e}")

            # Attempt Redis reconnection if currently unavailable
            try:
                from utils.redis_client import is_redis_available, try_reconnect
                if not is_redis_available():
                    await try_reconnect()
            except Exception:
                pass

            await asyncio.sleep(interval)

    monitor_task = asyncio.create_task(run_background_maintenance())
    
    yield
    
    # Shutdown hooks
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
        
    from ports.hooks import hook_manager
    hook_manager.shutdown()
    await close_redis()
    logger.info("Shutting down Phoveus API")

# Determine whether API docs (Swagger UI, ReDoc, OpenAPI JSON) are enabled
_enable_docs = CONFIG.get("ENABLE_DOCS", True)

# Create FastAPI app with lifespan
app = FastAPI(
    title="Phoveus API",
    description="""
    **Phoveus API**

    A SaaS backend built with hexagonal architecture for maintainability and extensibility.

    ## Architecture

    * **Hexagonal Architecture**: Clean separation of concerns with ports & adapters
    * **Dependency Injection**: Modular service management
    * **Async Processing**: Non-blocking operations for better performance
    * **Database Integration**: SQLAlchemy ORM backend
    * **Modular Routes**: Organized endpoint structure for maintainability

    ## Getting Started

    1. Check the health endpoint: `/health`
    """,
    version="2.0.0",
    contact={
        "name": "Phoveus",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    openapi_url="/openapi.json" if _enable_docs else None,
)

# Log 422 validation errors so they're not silent
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.warning("422 Validation Error: %s %s — %s", request.method, request.url.path, exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# Add CORS middleware
# Get CORS configuration from config
cors_origins = CONFIG["CORS_ORIGINS"]
# If single '*' is in the list, use ["*"] for FastAPI
if len(cors_origins) == 1 and cors_origins[0] == '*':
    cors_origins = ["*"]

cors_methods = CONFIG["CORS_ALLOW_METHODS"]
# If single '*' is in the list, use ["*"] for FastAPI
if len(cors_methods) == 1 and cors_methods[0] == '*':
    cors_methods = ["*"]

cors_headers = CONFIG["CORS_ALLOW_HEADERS"]
# If single '*' is in the list, use ["*"] for FastAPI
if len(cors_headers) == 1 and cors_headers[0] == '*':
    cors_headers = ["*"]

# Build CORS middleware arguments
cors_kwargs = {
    "allow_origins": cors_origins,
    "allow_credentials": CONFIG["CORS_ALLOW_CREDENTIALS"],
    "allow_methods": cors_methods,
    "allow_headers": cors_headers,
}

# Add optional CORS parameters if configured
if CONFIG["CORS_EXPOSE_HEADERS"]:
    cors_kwargs["expose_headers"] = CONFIG["CORS_EXPOSE_HEADERS"]
if CONFIG["CORS_MAX_AGE"]:
    cors_kwargs["max_age"] = CONFIG["CORS_MAX_AGE"]

app.add_middleware(
    CORSMiddleware,
    **cors_kwargs
)

# Register LogContextMiddleware — sets per-request log context (request_id, user_id, etc.)
app.add_middleware(LogContextMiddleware)

# Import middleware factories (infrastructure/adapters concern)
from utils.middleware import (
    create_rate_limiting_middleware,
    create_security_headers_middleware,
    CompressedRequestMiddleware
)

# Decompress gzip/zstd-encoded request bodies (e.g. from Go worker submissions)
from utils.middleware.gzip_request import HAS_ZSTD
logger.info("🗜️  Zstd decompression support: %s", "ENABLED" if HAS_ZSTD else "DISABLED (zstandard not installed)")
app.add_middleware(CompressedRequestMiddleware)

# Register middleware (composition root - wires infrastructure together)
security_headers_middleware = create_security_headers_middleware()
rate_limiting_middleware = create_rate_limiting_middleware(
    rate_limit_enabled=RATE_LIMIT_ENABLED,
    rate_limit_bypass_key=RATE_LIMIT_BYPASS_KEY,
    test_mode=CONFIG["TEST_MODE"]
)

@app.middleware("http")
async def security_headers_middleware_wrapper(request: Request, call_next):
    """Security headers middleware wrapper"""
    return await security_headers_middleware(request, call_next)

@app.middleware("http")
async def rate_limiting_middleware_wrapper(request: Request, call_next):
    """Rate limiting middleware wrapper"""
    return await rate_limiting_middleware(request, call_next)

# Request logging is handled by LogContextMiddleware (registered above via app.add_middleware)

# Include the main router which contains all sub-routers
app.include_router(create_main_router())

# Removed custom validation exception handler - using Pydantic's default
# Pydantic's default handler properly handles JSON serialization and error formatting

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handler for HTTPException (400, 404, 500, etc.) - logs with structured fields."""
    error_id = str(uuid.uuid4())[:8]  # Short unique ID

    logger.warning(
        "http exception: %s %s → %d: %s",
        request.method, request.url.path, exc.status_code, exc.detail,
        extra={
            "error_id": error_id,
            "http.status_code": exc.status_code,
            "error.detail": str(exc.detail),
            "http.method": request.method,
            "http.path": request.url.path,
        },
    )

    # Build error_data for debug response (still useful in DEBUG_MODE)
    error_data = {
        "error_id": error_id,
        "type": "http_exception",
        "status_code": exc.status_code,
        "path": request.url.path,
        "method": request.method,
        "query_params": dict(request.query_params),
        "error_message": exc.detail,
        "error_type": type(exc).__name__,
        "timestamp": datetime.now().isoformat()
    }
    
    # Return sanitized response - hide internal details for 500 errors
    if exc.status_code >= 500:
        # For server errors, don't expose internal details to clients
        client_message = "Internal server error. Please contact support if the problem persists."
    else:
        # For client errors (400, 404, etc.), the detail is usually safe to show
        client_message = exc.detail
    
    # Base error response
    error_response = {
        "detail": client_message,
        "error_id": error_id,
        "type": "http_error",
        "timestamp": datetime.now().isoformat()
    }
    
    # Add debug information if DEBUG_MODE is enabled
    debug_mode_enabled = CONFIG.get("DEBUG_MODE", False)
    if debug_mode_enabled:
        from utils.request import get_client_ip, get_user_agent
        error_response["debug"] = {
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method,
            "query_params": dict(request.query_params),
            "client_ip": get_client_ip(request) or "unknown",
            "user_agent": get_user_agent(request) or "unknown",
            "error_type": type(exc).__name__,
            "original_detail": exc.detail if exc.status_code < 500 else "Hidden in production",
            "headers": dict(request.headers) if hasattr(request, 'headers') else {},
            "error_data": error_data
            # Note: traceback is already included in error_data, no need to duplicate it here
        }
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors"""
    error_id = str(uuid.uuid4())[:8]  # Short unique ID
    import traceback
    
    # Get full traceback
    tb_str = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    
    # Log to errors.log with unique ID
    error_data = {
        "error_id": error_id,
        "type": "internal_error",
        "status_code": 500,
        "path": request.url.path,
        "method": request.method,
        "query_params": dict(request.query_params),
        "error_message": str(exc),
        "error_type": type(exc).__name__,
        "traceback": tb_str,
        "timestamp": datetime.now().isoformat()
    }
    # Log error: full JSON to file, concise to console
    log_error_with_id(
        error_id,
        "internal_error",
        error_data,
        f"❌ Unhandled exception [Error ID: {error_id}] on {request.method} {request.url.path}\n   Error: {str(exc)}\n   Type: {type(exc).__name__}\n   Full traceback saved to errors.log (search for error ID: {error_id})"
    )
    
    # Base error response
    error_response = {
        "detail": "Internal server error. Please check the logs for more information.",
        "error_id": error_id,
        "type": "internal_error",
        "timestamp": datetime.now().isoformat()
    }
    
    # Add debug information if DEBUG_MODE is enabled
    debug_mode_enabled = CONFIG.get("DEBUG_MODE", False)
    if debug_mode_enabled:
        from utils.request import get_client_ip, get_user_agent
        error_response["debug"] = {
            "status_code": 500,
            "path": request.url.path,
            "method": request.method,
            "query_params": dict(request.query_params),
            "client_ip": get_client_ip(request) or "unknown",
            "user_agent": get_user_agent(request) or "unknown",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "headers": dict(request.headers) if hasattr(request, 'headers') else {},
            "error_data": error_data
            # Note: traceback is already included in error_data, no need to duplicate it here
        }
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response
    )

def custom_openapi():
    """Custom OpenAPI schema with enhanced metadata and OAuth2 security schemes"""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Phoveus API",
        version="2.0.0",
        description=app.description,
        routes=app.routes,
    )
    
    # Add OAuth2 security schemes for Swagger UI
    # Preserve existing components (like schemas) and add security schemes
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    
    # Add security schemes to existing components
    openapi_schema["components"]["securitySchemes"] = {
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter your JWT token. Get it from /auth/login or use OAuth2 below."
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter your JWT token. You can get this by calling the /auth/login endpoint."
        },
        "OAuth2PasswordBearer": {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": "/auth/token",
                    "scopes": {
                        "read": "Read access to products and monitoring",
                        "write": "Write access to products and monitoring",
                        "admin": "Administrative access"
                    }
                }
            },
            "description": "⚠️ IMPORTANT: Enter your EMAIL address in the 'username' field below (not a username). This API uses email-based authentication. OAuth2 standard requires 'username' field name, but you must enter your email address there. Example: user@example.com"
        }
    }
    
    # Ensure all routes are included
    if "paths" not in openapi_schema:
        openapi_schema["paths"] = {}
    
    # Customize the /auth/token endpoint to show "email" instead of "username"
    # This modifies the request body schema for the OAuth2 token endpoint
    if "/auth/token" in openapi_schema.get("paths", {}):
        token_path = openapi_schema["paths"]["/auth/token"]
        if "post" in token_path and "requestBody" in token_path["post"]:
            content = token_path["post"]["requestBody"].get("content", {})
            if "application/x-www-form-urlencoded" in content:
                schema = content["application/x-www-form-urlencoded"].get("schema", {})
                if "properties" in schema:
                    # Change "username" property to "email" in the schema
                    if "username" in schema["properties"]:
                        schema["properties"]["email"] = {
                            **schema["properties"]["username"],
                            "title": "Email",
                            "description": "User's email address (required)"
                        }
                        # Keep username for OAuth2 compatibility but mark it as deprecated
                        schema["properties"]["username"]["description"] = "DEPRECATED: Use 'email' field instead. User's email address."
                        # Make email required if username was required
                        if "required" in schema and "username" in schema["required"]:
                            schema["required"] = [f if f != "username" else "email" for f in schema["required"]]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Health check endpoint is handled by routes/general.py

def display_main_params(**kwargs):
    """Display all main function parameter values using kwargs"""
    click.echo("\n🔧 Main Function Parameters:")
    click.echo("=" * 50)
    
    if not kwargs:
        click.echo("   ⚠️  No parameters found")
        return
    
    # Display each parameter with its value
    for param_name, value in sorted(kwargs.items()):
        # Format the display nicely
        if isinstance(value, bool):
            display_value = "✅ Enabled" if value else "❌ Disabled"
        elif isinstance(value, int):
            display_value = f"{value:,}" if value > 1000 else str(value)
        elif value is None:
            display_value = "None"
        else:
            display_value = str(value)
        
        click.echo(f"   • {param_name}: {display_value}")
    
    click.echo("=" * 50)


@click.command()
@click.option('--host', default=CONFIG["UVI_HOST"], help='Host to bind to')
@click.option('--port', type=int, default=CONFIG["UVI_PORT"], help='Port to bind to')
@click.option('--reload', is_flag=True, default=CONFIG["RELOAD"], help='Enable auto-reload')
@click.option('--log-level', default=CONFIG["LOG_LEVEL"], type=click.Choice(["debug", "info", "warning", "error"]), help='Log level')
@click.option('--access-log', is_flag=True, default=CONFIG["UVI_ACCESS_LOG"], help='Enable access logging')
@click.option('--workers', type=int, default=CONFIG["UVI_WORKERS"], help='Number of worker processes')
@click.option('--limit-concurrency', type=int, default=CONFIG["UVI_LIMIT_CONCURRENCY"], help='Maximum concurrent connections')
@click.option('--limit-max-requests', type=int, default=CONFIG["UVI_LIMIT_MAX_REQUESTS"], help='Restart worker after N requests')
@click.option('--timeout-keep-alive', type=int, default=CONFIG["UVI_TIMEOUT_KEEP_ALIVE"], help='Keep connections alive for N seconds')
@click.option('--timeout-graceful-shutdown', type=int, default=CONFIG["UVI_TIMEOUT_GRACEFUL_SHUTDOWN"], help='Graceful shutdown timeout in seconds')
@click.option('--database-url', help='Override DATABASE_URL for this session')
def main(host, port, reload, log_level, access_log, workers, limit_concurrency, limit_max_requests, 
         timeout_keep_alive, timeout_graceful_shutdown, database_url):
    """
    Phoveus API

    A FastAPI-based SaaS backend service.
    Use --database-url to override the DATABASE_URL environment variable for this session.
    """
    
    # Set database URL override if provided (do this early, BEFORE any database connections)
    if database_url:
        # Set environment variable first - this takes precedence over CONFIG
        # get_database_url() will read from os.getenv() before CONFIG
        os.environ["PHOVEU_BACKEND_DATABASE_URL"] = database_url
        # Also set via the config function for backward compatibility
        set_database_url(database_url)
        click.echo(f"🔧 Using database URL override: {database_url[:50]}...")
        # Reset services initialization flag so services are recreated with new database URL
        global _services_initialized, _services
        _services_initialized = False
        _services = None
        # Also reset the database connection cache
        try:
            from utils.database.database_session import reset_database_connection
            reset_database_connection()
        except Exception:
            pass
    
    # Display main function parameters
    display_main_params(host=host, port=port, reload=reload, log_level=log_level, access_log=access_log, workers=workers, 
                       limit_concurrency=limit_concurrency, limit_max_requests=limit_max_requests, 
                       timeout_keep_alive=timeout_keep_alive, timeout_graceful_shutdown=timeout_graceful_shutdown, 
                       database_url=database_url)

    # Apply DEBUG_MODE if enabled
    # Note: Individual settings can still be overridden via CLI flags or environment variables
    if CONFIG.get("DEBUG_MODE", False):
        # Override log_level if it matches the default (meaning it wasn't explicitly set via CLI)
        default_log_level = "debug" if CONFIG.get("DEBUG_MODE", False) else "info"
        if log_level == default_log_level or log_level == CONFIG.get("LOG_LEVEL", "info"):
            log_level = "debug"
            click.echo("🐛 DEBUG_MODE enabled: Using debug log level")
        
        # Override reload if it matches the default (meaning it wasn't explicitly set via CLI)
        default_reload = CONFIG.get("DEBUG_MODE", False)
        if reload == default_reload or reload == CONFIG.get("RELOAD", False):
            reload = True
            click.echo("🔄 DEBUG_MODE enabled: Auto-reload enabled")
        
        # Display debug mode status
        if CONFIG.get("DB_ECHO", False):
            click.echo("📊 DEBUG_MODE enabled: Database query logging enabled")
        if CONFIG.get("DB_ECHO_POOL", False):
            click.echo("🔌 DEBUG_MODE enabled: Connection pool logging enabled")
    
    # Re-apply structured logging with CLI-provided log level
    # (configure_logging was already called at module level; this overrides the level if specified via CLI)
    configure_logging(log_level, CONFIG.get("LOG_OUTPUT", "both"), CONFIG.get("LOG_FORMAT", "json"))
    ctx_filter = ContextFilter()
    for h in logging.getLogger().handlers:
        h.addFilter(ctx_filter)
    
    # Log startup information
    logger.info("🚀 Starting Phoveus API")
    logger.info(f"📊 Log level: {log_level}")
    logger.info(f"🌐 Host: {host}:{port}")
    if not _enable_docs:
        logger.info("📄 API docs disabled (PHOVEU_BACKEND_ENABLE_DOCS=false)")
    
    # Log database configuration and display connection info
    logger.info(f"🗃️  Database URL: {'Override from command line' if database_url else 'From environment variable'}")
    
    # Always display connection info at startup
    click.echo(f"\n🔧 Database Configuration:")
    try:
        display_detailed_connection_info()
    except Exception as e:
        click.echo(f"❌ Error showing database info: {e}")
    
    # Log database connection pool stats on startup
    try:
        from utils.database.database_session import log_pool_stats
        log_pool_stats()
    except Exception as e:
        logger.warning(f"Could not log pool stats: {e}")
    
    # Display main function parameters before schema validation
    display_main_params(host=host, port=port, reload=reload, log_level=log_level, access_log=access_log, workers=workers, 
                       limit_concurrency=limit_concurrency, limit_max_requests=limit_max_requests, 
                       timeout_keep_alive=timeout_keep_alive, timeout_graceful_shutdown=timeout_graceful_shutdown, 
                       database_url=database_url)
    
    # Check database schema before starting FastAPI
    click.echo("\n🔍 Validating database schema...")
    
    # Get validation result without displaying (to check if we should auto-init)
    from utils.database.schema_checker import validate_schema_centralized
    is_in_sync, error_message, differences_count, is_connection_error = validate_schema_centralized()
    
    # Auto-initialize database if schema validation fails due to missing tables only (empty database)
    if not is_in_sync and not is_connection_error:
        from utils.database.schema_checker import analyze_database_schema
        schema_result = analyze_database_schema(strict=False)
        
        # Only auto-initialize if the only issue is missing tables (empty database)
        if schema_result.missing_tables and len(schema_result.missing_tables) > 0 and \
           len(schema_result.column_changes) == 0 and len(schema_result.extra_tables) == 0:
            click.echo("")
            click.echo(click.style("🔧 Database appears to be empty. Auto-initializing...", fg='yellow', bold=True))
            click.echo("")
            
            try:
                from utils.database import init_database
                
                if init_database():
                    click.echo("")
                    click.echo(click.style("✅ Database auto-initialized successfully!", fg='green', bold=True))
                    click.echo("")
                    # Re-validate after initialization
                    is_in_sync, error_message, differences_count, is_connection_error = validate_schema_centralized()
                else:
                    click.echo(click.style("❌ Auto-initialization failed", fg='red'))
                    click.echo("")
                    click.echo("Please initialize manually with: python cli.py system db init")
                    sys.exit(1)
                    
            except Exception as e:
                click.echo(click.style(f"❌ Auto-initialization failed: {e}", fg='red'))
                click.echo("")
                click.echo("Please initialize manually with: python cli.py system db init")
                sys.exit(1)
    
    # Now display the validation result (will exit if still not in sync)
    from utils.database.schema_validation import display_schema_validation_result
    display_schema_validation_result(
        is_in_sync=is_in_sync,
        error_message=error_message,
        differences_count=differences_count,
        is_connection_error=is_connection_error,
        context="API",
        database_url=database_url,
        verbose=True
    )
    
    # Configure 'server' logger for clean JSON output
    server_logger = logging.getLogger("server")
    server_logger.setLevel(logging.INFO)
    server_logger.propagate = False  # Don't propagate to root logger (avoids double logging)
    
    # Remove existing handlers to avoid duplicates
    for handler in server_logger.handlers[:]:
        server_logger.removeHandler(handler)
        
    # Add handler with bare formatting
    json_handler = logging.StreamHandler(sys.stdout)
    json_handler.setFormatter(logging.Formatter('%(message)s'))
    server_logger.addHandler(json_handler)
    
    # Configure uvicorn with optimized settings for production databases
    uvicorn.run(
        "api_main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        access_log=False,  # Disable default Uvicorn access log (using custom JSON middleware)
        # Performance optimizations for concurrent requests
        workers=workers,  # Number of worker processes
        loop="asyncio",
        http="httptools",  # Faster HTTP parser
        # Connection limits
        limit_concurrency=limit_concurrency,  # Allow up to 100 concurrent connections
        limit_max_requests=None if workers == 1 else limit_max_requests,  # Disable limit for single worker to prevent server shutdown
        # Timeout settings
        timeout_keep_alive=timeout_keep_alive,  # Keep connections alive for 30 seconds
        timeout_graceful_shutdown=timeout_graceful_shutdown,  # Graceful shutdown timeout
        # Performance optimizations for production databases
    )


if __name__ == "__main__":
    main()

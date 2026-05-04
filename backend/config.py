from typing import List, Optional, Dict, Any
import os
from pathlib import Path

import sys

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Look for .env file in project root
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded environment variables from {env_path}")
    else:
        # Try to load from current directory as fallback (silent if not found)
        result = load_dotenv()
        # Only print if .env file was actually found and loaded
        if result:
            print("✅ Loaded environment variables from .env file in current directory")
except ImportError:
    # Silent in production - python-dotenv is optional
    pass
except Exception as e:
    print(f"⚠️  Could not load .env file: {e}")

# HTML Cleaning Configuration
# Simple array of HTML elements to remove before saving
# Set to None or empty list to disable cleaning
HTML_CLEANING_CONFIG = [
    "script",      # JavaScript elements
    "style",       # CSS style elements
    "link",        # Link elements (CSS, icons, etc.)
    "meta",        # Meta elements
    "noscript",    # NoScript elements
    "comment",     # Comment elements
]

# Centralized configuration dictionary
CONFIG = {
    # Branding
    "APP_NAME": os.getenv("PHOVEU_APP_NAME", "Phoveus"),
    "APP_LEGAL_ENTITY": os.getenv("PHOVEU_APP_LEGAL_ENTITY", "Phoveus"),
    "APP_SUPPORT_EMAIL": os.getenv("PHOVEU_SUPPORT_EMAIL", "phoveus@maborak.com"),

    # Domain Configuration
    # Frontend/UI domain for links in emails (verification, password reset, etc.)
    # Protocol scheme for email links: "https" or "http" (default: "https")
    # If DOMAIN_UI already includes a scheme, this is used to override it
    "DOMAIN_UI_SCHEME": os.getenv("DOMAIN_UI_SCHEME", "https"),
    "DOMAIN_UI": os.getenv("DOMAIN_UI", "http://localhost:3000"),
    # Public frontend URL used for sitemap.xml and canonical links
    "FRONTEND_BASE_URL": os.getenv("PHOVEU_FRONTEND_BASE_URL", "http://localhost:5173"),
    
    # CAPTCHA Configuration
    # Options: "none", "recaptcha_v3", "turnstile"
    "CAPTCHA_TYPE": os.getenv("PHOVEU_BACKEND_CAPTCHA_TYPE", "none").lower(),
    # Provider-specific secret keys
    "RECAPTCHA_V3_SECRET_KEY": os.getenv("PHOVEU_BACKEND_RECAPTCHA_V3_SECRET_KEY", ""),
    "TURNSTILE_SECRET_KEY": os.getenv("PHOVEU_BACKEND_TURNSTILE_SECRET_KEY", ""),
    # reCAPTCHA v3 score threshold (0.0 to 1.0, default 0.5)
    # Lower scores indicate bot-like behavior
    "RECAPTCHA_V3_THRESHOLD": float(os.getenv("PHOVEU_BACKEND_RECAPTCHA_V3_THRESHOLD", "0.5")),
    # CAPTCHA trust window in seconds (default 300s / 5m)
    # A successful validation grants a temporary trust window for bulk operations
    "CAPTCHA_TRUST_WINDOW": int(os.getenv("PHOVEU_BACKEND_CAPTCHA_TRUST_WINDOW", "300")),
    # Login CAPTCHA: require CAPTCHA after N failed login attempts (0 = disabled)
    "LOGIN_CAPTCHA_THRESHOLD": int(os.getenv("PHOVEU_BACKEND_LOGIN_CAPTCHA_THRESHOLD", "1")),
    
    # Support Inbound IMAP Configuration
    "SUPPORT_INBOUND_SERVER": os.getenv("PHOVEU_SUPPORT_INBOUND_SERVER", "imap.gmail.com"),
    "SUPPORT_INBOUND_PORT": int(os.getenv("PHOVEU_SUPPORT_INBOUND_PORT", "993")),
    "SUPPORT_INBOUND_USERNAME": os.getenv("PHOVEU_SUPPORT_INBOUND_USERNAME", ""),
    "SUPPORT_INBOUND_EMAIL": os.getenv("PHOVEU_SUPPORT_INBOUND_EMAIL", ""),
    "SUPPORT_INBOUND_PASSWORD": os.getenv("PHOVEU_SUPPORT_INBOUND_PASSWORD", ""),
    "SUPPORT_INBOUND_USE_SSL": os.getenv("PHOVEU_SUPPORT_INBOUND_USE_SSL", "true").lower() == "true",
    
    # Support Outbound Identity (defaults used by EmailHandler)
    "SUPPORT_OUTBOUND_SENDER_NAME": os.getenv("PHOVEU_SUPPORT_OUTBOUND_SENDER_NAME", "Phoveus Support"),
    
    # Debug Mode Configuration (unified debug flag)
    # When enabled, automatically sets: LOG_LEVEL=debug, DB_ECHO=true, DB_ECHO_POOL=true, RELOAD=true
    "DEBUG_MODE": os.getenv("PHOVEU_BACKEND_DEBUG_MODE", "false").lower() == "true",

    # API Documentation (Swagger/ReDoc/OpenAPI)
    # Disable in production to avoid exposing internal API structure
    "ENABLE_DOCS": os.getenv("PHOVEU_BACKEND_ENABLE_DOCS", str(os.getenv("PHOVEU_BACKEND_DEBUG_MODE", "false").lower() == "true")).lower() == "true",
    
    # Redis Configuration
    # Used for shared rate limiting, CAPTCHA trust, and guest limits across workers.
    # Set to empty string or omit to fall back to in-memory (single-process only).
    "REDIS_URL": os.getenv("PHOVEU_REDIS_SERVER", ""),

    # Database Configuration
    "DATABASE_URL": os.getenv("PHOVEU_BACKEND_DATABASE_URL", "sqlite:///./database/product_cache.db"),
    # DB_ECHO and DB_ECHO_POOL can be overridden, but default to DEBUG_MODE value if not set
    "DB_ECHO": os.getenv("PHOVEU_BACKEND_DB_ECHO", str(os.getenv("PHOVEU_BACKEND_DEBUG_MODE", "false").lower() == "true")).lower() == "true",
    "DB_ECHO_POOL": os.getenv("PHOVEU_BACKEND_DB_ECHO_POOL", str(os.getenv("PHOVEU_BACKEND_DEBUG_MODE", "false").lower() == "true")).lower() == "true",
    
    # Database Read/Write Separation
    "DB_USE_REPLICA_ENGINE": os.getenv("PHOVEU_BACKEND_DB_USE_REPLICA_ENGINE", "false").lower() == "true",
    "DB_READ_URL": os.getenv("PHOVEU_BACKEND_DB_READ_URL", ""),  # Optional read replica URL
    "DB_WRITE_URL": os.getenv("PHOVEU_BACKEND_DB_WRITE_URL", ""),  # Optional write master URL
    "DB_READ_POOL_SIZE": int(os.getenv("PHOVEU_BACKEND_DB_READ_POOL_SIZE", "10")),
    "DB_WRITE_POOL_SIZE": int(os.getenv("PHOVEU_BACKEND_DB_WRITE_POOL_SIZE", "20")),
    
    "DB_POOL_SIZE": os.getenv("PHOVEU_BACKEND_DB_POOL_SIZE", "20"),
    "DB_MAX_OVERFLOW": os.getenv("PHOVEU_BACKEND_DB_MAX_OVERFLOW", "30"),
    "DB_POOL_TIMEOUT": os.getenv("PHOVEU_BACKEND_DB_POOL_TIMEOUT", "30"),
    "DB_POOL_RECYCLE": os.getenv("PHOVEU_BACKEND_DB_POOL_RECYCLE", "3600"),
    
    # Table Names Configuration
    "TABLE_PERMISSIONS": os.getenv("PHOVEU_BACKEND_TABLE_PERMISSIONS", "permissions"),
    "TABLE_ROLES": os.getenv("PHOVEU_BACKEND_TABLE_ROLES", "roles"),
    "TABLE_ROLE_PERMISSIONS": os.getenv("PHOVEU_BACKEND_TABLE_ROLE_PERMISSIONS", "role_permissions"),
    
    # Cookie Lifetime Configuration
    "COOKIE_LIFETIME": int(os.getenv("PHOVEU_BACKEND_COOKIE_LIFETIME", "3600")),  # Default: 1 hour in seconds
    "TABLE_HOOK_EVENTS": os.getenv("PHOVEU_BACKEND_TABLE_HOOK_EVENTS", "hook_events"),
    "TABLE_EVENT_CONFIGS": os.getenv("PHOVEU_BACKEND_TABLE_EVENT_CONFIGS", "event_configs"),
    "TABLE_APP_CONFIG": os.getenv("PHOVEU_BACKEND_TABLE_APP_CONFIG", "app_config"),
    "TABLE_CONFIG_SNAPSHOTS": os.getenv("PHOVEU_BACKEND_TABLE_CONFIG_SNAPSHOTS", "config_snapshots"),
    "TABLE_WORKERS": os.getenv("PHOVEU_BACKEND_TABLE_WORKERS", "workers"),
    "TABLE_BENCH": os.getenv("PHOVEU_BACKEND_TABLE_BENCH", "bench"),
    "TABLE_USERS": os.getenv("PHOVEU_BACKEND_TABLE_USERS", "users"),
    "TABLE_USER_SESSIONS": os.getenv("PHOVEU_BACKEND_TABLE_USER_SESSIONS", "user_sessions"),
    "TABLE_USER_TOKENS": os.getenv("PHOVEU_BACKEND_TABLE_USER_TOKENS", "user_tokens"),
    "TABLE_USER_PERMISSIONS": os.getenv("PHOVEU_BACKEND_TABLE_USER_PERMISSIONS", "user_permissions"),
    "TABLE_HOOK_CONFIGS": os.getenv("PHOVEU_BACKEND_TABLE_HOOK_CONFIGS", "hook_configs"),
    
    # JWT Configuration
    "JWT_SECRET": os.getenv("PHOVEU_BACKEND_JWT_SECRET", "your-super-secret-jwt-key-here-change-this-in-production"),
    "JWT_ALGORITHM": os.getenv("PHOVEU_BACKEND_JWT_ALGORITHM", "HS256"),
    "JWT_ACCESS_TOKEN_EXPIRY": int(os.getenv("PHOVEU_BACKEND_JWT_ACCESS_TOKEN_EXPIRY", "900")),
    "JWT_REFRESH_TOKEN_EXPIRY": int(os.getenv("PHOVEU_BACKEND_JWT_REFRESH_TOKEN_EXPIRY", "2592000")),
    
    # Credits Configuration
    "REGISTRATION_CREDITS": int(os.getenv("PHOVEU_REGISTRATION_CREDITS", "5")),

    # Billing / Payment Provider Configuration
    "PAYPAL_CLIENT_ID": os.getenv("PHOVEU_BACKEND_PAYPAL_CLIENT_ID", ""),
    "PAYPAL_SECRET": os.getenv("PHOVEU_BACKEND_PAYPAL_SECRET", ""),
    "PAYPAL_WEBHOOK_ID": os.getenv("PHOVEU_BACKEND_PAYPAL_WEBHOOK_ID", ""),
    "PAYPAL_MODE": os.getenv("PHOVEU_BACKEND_PAYPAL_MODE", "sandbox"),  # sandbox or live
    
    "STRIPE_SECRET_KEY": os.getenv("PHOVEU_BACKEND_STRIPE_SECRET_KEY", ""),
    "STRIPE_WEBHOOK_SECRET": os.getenv("PHOVEU_BACKEND_STRIPE_WEBHOOK_SECRET", ""),
    
    # Server Configuration
    "UVI_HOST": os.getenv("PHOVEU_BACKEND_UVI_HOST", "0.0.0.0"),
    "UVI_PORT": int(os.getenv("PHOVEU_BACKEND_UVI_PORT", "9000")),
    # RELOAD and LOG_LEVEL can be overridden, but default to DEBUG_MODE value if not set
    "RELOAD": os.getenv("PHOVEU_BACKEND_RELOAD", str(os.getenv("PHOVEU_BACKEND_DEBUG_MODE", "false").lower() == "true")).lower() == "true",
    "LOG_LEVEL": os.getenv("PHOVEU_BACKEND_LOG_LEVEL", "debug" if os.getenv("PHOVEU_BACKEND_DEBUG_MODE", "false").lower() == "true" else "info"),
    "LOG_OUTPUT": os.getenv("PHOVEU_BACKEND_LOG_OUTPUT", "both"),  # "stdout" | "file" | "both"
    "LOG_FORMAT": os.getenv("PHOVEU_BACKEND_LOG_FORMAT", "json"),  # "json" | "pretty" | "text"
    "LOG_EXCLUDED_PATHS": set(p.strip() for p in os.getenv("PHOVEU_BACKEND_LOG_EXCLUDED_PATHS", "/health").split(",") if p.strip()),
    "UVI_ACCESS_LOG": os.getenv("PHOVEU_BACKEND_UVI_ACCESS_LOG", "true").lower() == "true",
    "UVI_WORKERS": int(os.getenv("PHOVEU_BACKEND_UVI_WORKERS", "5")),
    "UVI_LIMIT_CONCURRENCY": int(os.getenv("PHOVEU_BACKEND_UVI_LIMIT_CONCURRENCY", "100")),
    "UVI_LIMIT_MAX_REQUESTS": int(os.getenv("PHOVEU_BACKEND_UVI_LIMIT_MAX_REQUESTS", "1000")),
    "UVI_TIMEOUT_KEEP_ALIVE": int(os.getenv("PHOVEU_BACKEND_UVI_TIMEOUT_KEEP_ALIVE", "30")),
    "UVI_TIMEOUT_GRACEFUL_SHUTDOWN": int(os.getenv("PHOVEU_BACKEND_UVI_TIMEOUT_GRACEFUL_SHUTDOWN", "30")),
    
    # Event Monitoring
    "EVENT_RETENTION_DAYS": int(os.getenv("PHOVEU_BACKEND_EVENT_RETENTION_DAYS", "30")),
    
    # CORS Configuration
    "CORS_ORIGINS": [origin.strip() for origin in os.getenv('PHOVEU_BACKEND_CORS_ORIGINS', '*').split(',')],  # Comma-separated list of allowed origins, or '*' for all
    "CORS_ALLOW_CREDENTIALS": os.getenv('PHOVEU_BACKEND_CORS_ALLOW_CREDENTIALS', 'true').lower() == 'true',  # Allow credentials in CORS requests
    "CORS_ALLOW_METHODS": [method.strip() for method in os.getenv('PHOVEU_BACKEND_CORS_ALLOW_METHODS', '*').split(',')],  # Comma-separated list of allowed HTTP methods, or '*' for all
    "CORS_ALLOW_HEADERS": [header.strip() for header in os.getenv('PHOVEU_BACKEND_CORS_ALLOW_HEADERS', '*').split(',')],  # Comma-separated list of allowed headers, or '*' for all
    "CORS_EXPOSE_HEADERS": [header.strip() for header in os.getenv('PHOVEU_BACKEND_CORS_EXPOSE_HEADERS', 'X-Track-RateLimit-Limit,X-Track-RateLimit-Remaining,X-Track-RateLimit-Reset,X-Track-RateLimit-RetryAfter,X-PRL-Attempt,X-PRL-RetryAfter,X-PRL-RequiresCaptcha').split(',') if header.strip()],  # Comma-separated list of headers to expose
    "CORS_MAX_AGE": int(os.getenv('PHOVEU_BACKEND_CORS_MAX_AGE', '600')),  # Max age for preflight requests in seconds (default: 600)
    
    # Guest Product Check Limits
    # Only applies to unauthenticated IPs when the product does not already exist in the DB.
    "GUEST_CHECK_MAX_ATTEMPTS": int(os.getenv('PHOVEU_BACKEND_GUEST_CHECK_MAX_ATTEMPTS', '5')),
    "GUEST_CHECK_TTL_SECONDS": int(os.getenv('PHOVEU_BACKEND_GUEST_CHECK_TTL_SECONDS', '86400')),

    # Proxy Header Trust Configuration
    # When False (default): get_client_ip() uses request.client.host only — prevents IP spoofing via X-Forwarded-For / X-Real-IP
    # When True: get_client_ip() reads X-Forwarded-For and X-Real-IP headers — use ONLY when behind a trusted reverse proxy (nginx, ALB, etc.)
    "TRUST_PROXY_HEADERS": os.getenv('PHOVEU_BACKEND_TRUST_PROXY_HEADERS', 'false').lower() == 'true',
    # Number of trusted reverse proxies in the chain (nginx, ALB, CDN, etc.)
    # Used to extract the real client IP from X-Forwarded-For by reading ips[len - depth]
    "TRUSTED_PROXY_DEPTH": int(os.getenv('PHOVEU_BACKEND_TRUSTED_PROXY_DEPTH', '1')),

    # Rate Limiting Configuration
    "RATE_LIMIT_ENABLED": os.getenv('PHOVEU_BACKEND_RATE_LIMIT_ENABLED', 'true').lower() == 'true',
    "RATE_LIMIT_REQUESTS": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_REQUESTS', '60')),
    "RATE_LIMIT_WINDOW": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_WINDOW', '60')),
    "RATE_LIMIT_BYPASS_KEY": os.getenv('PHOVEU_BACKEND_RATE_LIMIT_BYPASS_KEY'),
    "RATE_LIMIT_EXCLUDED_PATHS": [
        path.strip() for path in os.getenv(
            'PHOVEU_BACKEND_RATE_LIMIT_EXCLUDED_PATHS',
            '/docs,/redoc,/openapi.json,/favicon.ico,/health'
        ).split(',') if path.strip()
    ],
    "RATE_LIMIT_BYPASS_PATHS": [
        path.strip() for path in os.getenv(
            'PHOVEU_BACKEND_RATE_LIMIT_BYPASS_PATHS',
            ''
        ).split(',') if path.strip()
    ],

    # Product-add specific rate limits (tiered by verification status)
    "TRACK_RATE_LIMIT_UNVERIFIED": int(os.getenv('PHOVEU_BACKEND_TRACK_RATE_LIMIT_UNVERIFIED', '10')),
    "TRACK_RATE_LIMIT_VERIFIED": int(os.getenv('PHOVEU_BACKEND_TRACK_RATE_LIMIT_VERIFIED', '50')),
    "TRACK_RATE_LIMIT_WINDOW": int(os.getenv('PHOVEU_BACKEND_TRACK_RATE_LIMIT_WINDOW', '60')),
    
    # Notification Queue Configuration
    "NOTIFICATION_QUEUE_ENABLED": os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_ENABLED", "true").lower() == "true",
    "NOTIFICATION_QUEUE_EMAIL_CONCURRENCY": int(os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_EMAIL_CONCURRENCY", "10")),
    "NOTIFICATION_QUEUE_MAX_RETRIES": int(os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_MAX_RETRIES", "5")),
    "NOTIFICATION_QUEUE_RETRY_BASE_SECONDS": int(os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_RETRY_BASE_SECONDS", "30")),
    "NOTIFICATION_QUEUE_RETRY_MAX_SECONDS": int(os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_RETRY_MAX_SECONDS", "3600")),
    "NOTIFICATION_QUEUE_EMAIL_RATE_MAX": int(os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_EMAIL_RATE_MAX", "100")),
    "NOTIFICATION_QUEUE_EMAIL_RATE_WINDOW": int(os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_EMAIL_RATE_WINDOW", "60")),
    "NOTIFICATION_QUEUE_CONSUMER_SHUTDOWN_TIMEOUT": int(os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_CONSUMER_SHUTDOWN_TIMEOUT", "30")),
    "NOTIFICATION_QUEUE_RETRY_POLL_INTERVAL": int(os.getenv("PHOVEU_BACKEND_NOTIFICATION_QUEUE_RETRY_POLL_INTERVAL", "5")),

    # CLI Configuration
    "CLI_LOG_LEVEL": os.getenv("PHOVEU_BACKEND_CLI_LOG_LEVEL", "info"),
    "SAVE_SCRAPPED_HTML": os.getenv("PHOVEU_BACKEND_SAVE_SCRAPPED_HTML", "true").lower() == "true",
    # HTML Mode: "cleaned" (strip JS/CSS/meta/comments) or "raw" (preserve full HTML)
    # Affects both Python scraper and Go worker (via queue API response)
    "HTML_MODE": os.getenv("PHOVEU_BACKEND_HTML_MODE", "cleaned").lower(),
    "HTML_STORAGE_PATH": os.getenv("PHOVEU_BACKEND_HTML_STORAGE_PATH", "data/html"),
    "HTML_RETENTION_DAYS": int(os.getenv("PHOVEU_BACKEND_HTML_RETENTION_DAYS", "90")),
    "QUEUE_KEY": os.getenv("PHOVEU_BACKEND_QUEUE_KEY", "your-secret-queue-key"),

    # Google OAuth Configuration
    "GOOGLE_CLIENT_ID": os.getenv("PHOVEU_BACKEND_GOOGLE_CLIENT_ID", ""),

    # GitHub OAuth Configuration
    "GITHUB_CLIENT_ID": os.getenv("PHOVEU_BACKEND_GITHUB_CLIENT_ID", ""),
    "GITHUB_CLIENT_SECRET": os.getenv("PHOVEU_BACKEND_GITHUB_CLIENT_SECRET", ""),

    # Facebook OAuth Configuration
    "FACEBOOK_APP_ID": os.getenv("PHOVEU_BACKEND_FACEBOOK_APP_ID", ""),
    "FACEBOOK_APP_SECRET": os.getenv("PHOVEU_BACKEND_FACEBOOK_APP_SECRET", ""),

    # Progressive Rate Limiting (PRL) — per-endpoint configurable strategies
    # Format: comma-separated steps. Number = delay seconds, C = captcha, C<N> = captcha + delay
    # Last step repeats forever. Empty string = disabled.
    "PRL_RESEND_VERIFICATION": os.getenv("PHOVEU_BACKEND_PRL_RESEND_VERIFICATION", "1,5,30,60,600,C,C60,C3600"),
    "PRL_CONFIRM_LINK": os.getenv("PHOVEU_BACKEND_PRL_CONFIRM_LINK", "1,5,30,C,C60,C600"),
    "PRL_LOGIN": os.getenv("PHOVEU_BACKEND_PRL_LOGIN", "0,0,0,5,15,30,C,C60,C600"),

    # Account lockout — hard lock after N consecutive failed password attempts
    "ACCOUNT_LOCKOUT_THRESHOLD": int(os.getenv("PHOVEU_BACKEND_ACCOUNT_LOCKOUT_THRESHOLD", "10")),
    "ACCOUNT_LOCKOUT_DURATION": int(os.getenv("PHOVEU_BACKEND_ACCOUNT_LOCKOUT_DURATION", "300")),  # seconds (300 = 5 min)
}

# Calculate endpoint-specific rate limits after base values are defined
# This allows us to use RATE_LIMIT_REQUESTS and RATE_LIMIT_WINDOW in calculations
_base_rate_limit_requests = CONFIG["RATE_LIMIT_REQUESTS"]
_base_rate_limit_window = CONFIG["RATE_LIMIT_WINDOW"]

CONFIG["RATE_LIMITS"] = {
    "/bench": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_BENCH_MAX_REQUESTS', str(_base_rate_limit_requests))),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_BENCH_WINDOW', str(_base_rate_limit_window)))
    },
    "/auth/login": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_LOGIN_MAX_REQUESTS', str(max(1, _base_rate_limit_requests // 2)))),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_LOGIN_WINDOW', str(_base_rate_limit_window)))
    },
    "/auth/token": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_TOKEN_MAX_REQUESTS', str(_base_rate_limit_requests))),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_TOKEN_WINDOW', str(_base_rate_limit_window)))
    },
    "/auth/register": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_REGISTER_MAX_REQUESTS', str(max(1, _base_rate_limit_requests // 2)))),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_REGISTER_WINDOW', str(_base_rate_limit_window)))
    },
    "/auth/oauth/google": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_OAUTH_GOOGLE_MAX_REQUESTS', str(max(1, _base_rate_limit_requests // 2)))),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_OAUTH_GOOGLE_WINDOW', str(_base_rate_limit_window)))
    },
    "/auth/verify": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_VERIFY_MAX_REQUESTS', '5')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_VERIFY_WINDOW', '3600'))  # 1 hour
    },
    "/auth/request-password-reset": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_PASSWORD_RESET_MAX_REQUESTS', str(max(1, _base_rate_limit_requests // 2)))),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_PASSWORD_RESET_WINDOW', '300'))  # 5 minutes
    },
    "/auth/refresh": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_REFRESH_MAX_REQUESTS', str(_base_rate_limit_requests * 2))),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_AUTH_REFRESH_WINDOW', str(_base_rate_limit_window)))
    },
    # Contact form - prevent spam/abuse
    "/contact": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_CONTACT_MAX_REQUESTS', '3')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_CONTACT_WINDOW', '3600'))  # 3 per hour
    },
    # Queue endpoints - protect worker queue from abuse
    "/queue": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_QUEUE_MAX_REQUESTS', '100')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_QUEUE_WINDOW', '60'))  # 100 per minute
    },
    # LiveChat session creation - prevent session flooding
    "/livechat/session": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_LIVECHAT_SESSION_MAX_REQUESTS', '10')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_LIVECHAT_SESSION_WINDOW', '300'))  # 10 per 5 minutes
    },
    # Media file serving - prevent bandwidth abuse
    "/media/": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_MEDIA_MAX_REQUESTS', '200')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_MEDIA_WINDOW', '60'))  # 200 per minute
    },
    # Webhook endpoints - prevent DoS via signature verification flooding
    "/webhooks/stripe": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_WEBHOOK_STRIPE_MAX_REQUESTS', '60')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_WEBHOOK_STRIPE_WINDOW', '60'))  # 60 per minute
    },
    "/webhooks/paypal": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_WEBHOOK_PAYPAL_MAX_REQUESTS', '60')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_WEBHOOK_PAYPAL_WINDOW', '60'))  # 60 per minute
    },
    # Product add — tighter limit to prevent scraping abuse
    "/products/add": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_PRODUCTS_ADD_MAX_REQUESTS', '10')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_PRODUCTS_ADD_WINDOW', '60'))  # 10 per minute
    },
    # Ticket endpoints — prevent ticket/reply spam (prefix matches all /user/account/tickets/*)
    "/user/account/tickets/": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_TICKETS_MAX_REQUESTS', '30')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_TICKETS_WINDOW', '3600'))  # 30 per hour
    },
    # Guest ticket endpoints — prevent abuse from unauthenticated users
    "/guest/tickets/": {
        "max_requests": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_GUEST_TICKETS_MAX_REQUESTS', '5')),
        "window": int(os.getenv('PHOVEU_BACKEND_RATE_LIMIT_GUEST_TICKETS_WINDOW', '3600'))  # 5 per hour
    },
}

# Continue CONFIG dictionary (it was already closed, so we add remaining configs)
CONFIG.update({
    # Benchmark Configuration
    "BENCH_KEY": os.getenv("PHOVEU_BACKEND_BENCH_KEY", ""),
    
    # Test Configuration
    "TEST_MODE": os.getenv("PHOVEU_BACKEND_TEST_MODE", "false").lower() == "true",
    
    # HTTP Engine Configuration
    "HTTP_ENGINE": os.getenv("PHOVEU_BACKEND_HTTP_ENGINE", "requests"),  # requests, urllib3, sockets
    "HTTP_TIMEOUT": float(os.getenv("PHOVEU_BACKEND_HTTP_TIMEOUT", "10.0")),
    "HTTP_RETRIES": int(os.getenv("PHOVEU_BACKEND_HTTP_RETRIES", "1")),
    "HTTP_MAX_CONNECTIONS": int(os.getenv("PHOVEU_BACKEND_HTTP_MAX_CONNECTIONS", "10")),
    "USER_AGENT": os.getenv("PHOVEU_BACKEND_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    
    # Data Source Configuration
    # Options: "scraping" (real HTTP requests), "dummy" (random generated data)
    "DATA_SOURCE": os.getenv("PHOVEU_BACKEND_DATA_SOURCE", "scraping").lower(),
    
    # Tier Limits Configuration
    "LIMIT_MAX_RECIPIENTS_CONFIRMED": int(os.getenv("PHOVEU_BACKEND_LIMIT_MAX_RECIPIENTS_CONFIRMED", "5")),
    "LIMIT_MAX_RECIPIENTS_PER_ALERT": int(os.getenv("PHOVEU_BACKEND_LIMIT_MAX_RECIPIENTS_PER_ALERT", "3")),
    "LIMIT_MAX_PRICE_ALERTS_CONFIRMED": int(os.getenv("PHOVEU_BACKEND_LIMIT_MAX_PRICE_ALERTS_CONFIRMED", "5")),
    "LIMIT_MAX_TRACKED_UNCONFIRMED": int(os.getenv("PHOVEU_BACKEND_LIMIT_MAX_TRACKED_UNCONFIRMED", "5")),
    "LIMIT_MAX_TRACKED_CONFIRMED": int(os.getenv("PHOVEU_BACKEND_LIMIT_MAX_TRACKED_CONFIRMED", "5")),
    "LIMIT_MAX_TRIGGERS_PER_ALERT": int(os.getenv("PHOVEU_BACKEND_LIMIT_MAX_TRIGGERS_PER_ALERT", "5")),
    "LIMIT_MIN_NOTIFICATION_FREQUENCY_MINUTES": int(os.getenv("PHOVEU_BACKEND_LIMIT_MIN_NOTIFICATION_FREQUENCY_MINUTES", "15")),
    "PRL_RESEND_VERIFICATION": os.getenv("PHOVEU_BACKEND_PRL_RESEND_VERIFICATION", "1,5,30,60,600,C,C60,C3600"),
    
    # API Endpoint Limits Configuration
    "API_PAGE_SIZE_DEFAULT": int(os.getenv("PHOVEU_BACKEND_API_PAGE_SIZE_DEFAULT", "10")),  # Default page size for /products endpoint
    "API_PAGE_SIZE_MAX": int(os.getenv("PHOVEU_BACKEND_API_PAGE_SIZE_MAX", "100")),  # Maximum page size for /products endpoint
    
    # Authentication Configuration
    # Maps route paths/patterns to whether authentication is required
    # Supports exact paths, path patterns (with *), and route prefixes
    # True = requires authentication, False = no authentication required
    "AUTH_REQUIRED": {
        # Public endpoints (no auth required)
        "/": False,
        "/health": False,
        "/auth/login": False,
        "/auth/register": False,
        "/auth/token": False,
        "/auth/refresh": False,
        "/auth/request-password-reset": False,
        "/auth/reset-password": False,
        
        # Protected endpoints (auth required)
        #"/products": True,
        #"/products/*": True,  # All /products/* routes require auth
        "/auth/logout": True,
        "/auth/change-password": True,
        "/auth/me": True,
        "/auth/api-keys": True,
        "/auth/api-keys/*": True,
        
        # Public endpoints (no auth)
        "/config/public": False,
        "/queue": False,
        "/monitoring/*": False,
        "/currency": False,
        "/country/*": False,
        "/bench/*": False,
        "/screenshot/*": False,  # Screenshot viewing is public
        "/products": False,
        "/products/*": False,
    },
    
    # Default authentication behavior for routes not in AUTH_REQUIRED
    # True = require auth by default, False = no auth by default
    "AUTH_REQUIRED_DEFAULT": True,
    
    # Hooks Configuration
    # If true: check database for handler config (disabled if not in DB)
    # If false: use CONFIG settings below
    "HOOKS_USE_DB_CONFIG": os.getenv("PHOVEU_BACKEND_HOOKS_USE_DB_CONFIG", "false").lower() == "true",
    # Hook Handlers Configuration (used when HOOKS_USE_DB_CONFIG is false)
    "HOOK_NOTIFY_USERS_PRICE_CHECKED": os.getenv("PHOVEU_BACKEND_HOOK_NOTIFY_USERS_PRICE_CHECKED", "false").lower() == "true",
    "HOOK_NOTIFY_USERS_PRICE_NOT_CHANGED": os.getenv("PHOVEU_BACKEND_HOOK_NOTIFY_USERS_PRICE_NOT_CHANGED", "false").lower() == "true",
    # Each handler has: enabled, and handler-specific config
    "HOOKS_HANDLERS": {
        "EmailHandler": {
            "enabled": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_ENABLED", "false").lower() == "true",
            "sender": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_SENDER", ""),
            "sender_name": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_SENDER_NAME", os.getenv("PHOVEU_APP_NAME", "Phoveus")),  # Display name — defaults to APP_NAME
            "receiver": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_RECEIVER", ""),
            "username": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_USERNAME", ""),  # SMTP login username (defaults to sender if empty)
            "password": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_PASSWORD", ""),
            "smtp_host": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_SMTP_HOST", "localhost"),
            "smtp_port": int(os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_SMTP_PORT", "465")),
            # Connection type: "ssl" (direct SSL), "starttls" (upgrade to TLS), "plain" (no encryption)
            "smtp_security": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_SMTP_SECURITY", "ssl").lower(),
            "smtp_verify_ssl": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_SMTP_VERIFY_SSL", "true").lower() == "true",
            # Content encoding: "quoted-printable" (readable), "base64" (compact), "7bit" (no encoding)
            "content_encoding": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_CONTENT_ENCODING", "quoted-printable").lower(),
            # Email template set: "default", "minimal", "corporate" (custom sets supported)
            "template_set": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_TEMPLATE_SET", "default"),
            # Email templates directory (defaults to templates/email/ in project root)
            "templates_dir": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_TEMPLATES_DIR", ""),
            "notify_users": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_NOTIFY_USERS", "false").lower() == "true",
            # Email verification settings
            "notify_on_verification_requested": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_NOTIFY_VERIFICATION", "true").lower() == "true",
            # Path for email verification links (appended to DOMAIN_UI)
            # Full URL: {DOMAIN_UI}{PATH}?token=xxx
            "verification_base_url": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_VERIFICATION_PATH", "/account/verify"),
            "recipient_verification_base_url": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_RECIPIENT_VERIFICATION_PATH", "/account/verify-recipient"),
            # Password reset email settings
            "notify_on_password_reset_requested": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_NOTIFY_PASSWORD_RESET", "true").lower() == "true",
            # Path for password reset links (appended to DOMAIN_UI)
            # Full URL: {DOMAIN_UI}{PATH}?token=xxx
            "password_reset_base_url": os.getenv("PHOVEU_BACKEND_HOOK_EMAIL_PASSWORD_RESET_PATH", "/account/reset-password"),
        },
        "LogHandler": {
            "enabled": os.getenv("PHOVEU_BACKEND_HOOK_LOG_ENABLED", "true").lower() == "true",
        },
        "PriceAlertHandler": {
            "enabled": True,  # Core logic middleware, usually enabled
        },
        # Add more handlers here as needed
    },
    
    "TICKET_UPLOAD_STORAGE_PATH": os.getenv("PHOVEU_BACKEND_TICKET_UPLOAD_STORAGE_PATH", "data/uploads/tickets"),
    "LIVECHAT_UPLOAD_STORAGE_PATH": os.getenv("PHOVEU_BACKEND_LIVECHAT_UPLOAD_STORAGE_PATH", "data/uploads/livechat"),
})

# Global variable for CLI database URL override
_CLI_DATABASE_URL = None

def get_project_root() -> Path:
    """
    Get the project root directory (where api_main.py is located).
    
    Returns:
        Path object pointing to the project root
    """
    # Find api_main.py by walking up from this file
    current_file = Path(__file__).resolve()
    # Start from config.py location and walk up to find api_main.py
    current_dir = current_file.parent
    while current_dir != current_dir.parent:  # Stop at filesystem root
        api_main = current_dir / "api_main.py"
        if api_main.exists():
            return current_dir
        current_dir = current_dir.parent
    # Fallback: return directory containing config.py (should be project root)
    return current_file.parent

def settings(key: str, default: Any = None) -> Any:
    """
    Get configuration value by key, similar to os.getenv() but from centralized config.
    Can be extended to load from YAML, JSON, or other sources.
    
    Args:
        key: Configuration key
        default: Default value if key not found
        
    Returns:
        Configuration value or default
    """
    return CONFIG.get(key, default)

def set(key: str, value: Any) -> None:
    """Set configuration value by key"""
    CONFIG[key] = value

def get_database_url() -> str:
    """Get database connection string
    
    Priority order:
    1. CLI override (_CLI_DATABASE_URL) - highest priority
    2. Environment variable (os.getenv) - can be set by --database-url
    3. CONFIG["DATABASE_URL"] - fallback/default value
    """
    # Return CLI override if set (highest priority)
    if _CLI_DATABASE_URL is not None:
        return _CLI_DATABASE_URL
    # Check environment variable first (allows --database-url to override CONFIG)
    env_value = os.getenv("PHOVEU_BACKEND_DATABASE_URL")
    if env_value is not None:
        return env_value
    # Fall back to CONFIG (default value)
    return CONFIG["DATABASE_URL"]

def set_database_url(url: str) -> None:
    """Set database URL override for CLI commands"""
    global _CLI_DATABASE_URL
    # Reset cached database connections if URL is changing
    if _CLI_DATABASE_URL != url:
        try:
            from utils.database.database_session import reset_database_connection
            reset_database_connection()
        except Exception as e:
            # If reset fails, continue anyway - new connections will use new URL
            pass
    _CLI_DATABASE_URL = url

def clear_database_url_override() -> None:
    """Clear database URL override"""
    global _CLI_DATABASE_URL
    _CLI_DATABASE_URL = None

def get_api_url() -> str:
    """Get API URL for testing"""
    host = CONFIG["UVI_HOST"]
    port = CONFIG["UVI_PORT"]
    return f"http://{host}:{port}"

def get_table_name(table_key: str) -> str:
    """
    Get table name by key from configuration
    
    Args:
        table_key: Key for the table name (e.g., 'currencies', 'product_states')
        
    Returns:
        Table name as string
        
    Raises:
        KeyError: If table_key is not found in CONFIG
    """
    table_key_upper = f"TABLE_{table_key.upper()}"
    if table_key_upper not in CONFIG:
        raise KeyError(f"Table key '{table_key}' not found in CONFIG")
    return CONFIG[table_key_upper]

def get_all_table_names() -> dict:
    """
    Get all configured table names
    
    Returns:
        Dictionary of all table names
    """
    table_names = {}
    for key, value in CONFIG.items():
        if key.startswith("TABLE_"):
            table_key = key[6:].lower()  # Remove "TABLE_" prefix
            table_names[table_key] = value
    return table_names

def set_table_name(table_key: str, table_name: str) -> None:
    """
    Set table name for a specific key (useful for testing or dynamic configuration)
    
    Args:
        table_key: Key for the table name
        table_name: New table name
    """
    table_key_upper = f"TABLE_{table_key.upper()}"
    CONFIG[table_key_upper] = table_name

def get_html_cleaning_config() -> Optional[List[str]]:
    """Get HTML cleaning configuration. Returns None when HTML_MODE is 'raw'."""
    if CONFIG.get("HTML_MODE") == "raw":
        return None
    return HTML_CLEANING_CONFIG

def get_http_engine_config() -> Dict[str, Any]:
    """Get HTTP engine configuration"""
    return {
        "engine_type": CONFIG["HTTP_ENGINE"],
        "timeout": CONFIG["HTTP_TIMEOUT"],
        "retries": CONFIG["HTTP_RETRIES"],
        "max_connections": CONFIG["HTTP_MAX_CONNECTIONS"]
    }


# Future: Load from YAML/JSON files
def load_config_from_yaml(yaml_file: str) -> None:
    """Load configuration from YAML file"""
    try:
        import yaml
        with open(yaml_file, 'r') as f:
            yaml_config = yaml.safe_load(f)
        CONFIG.update(yaml_config)
        print(f"✅ Loaded configuration from {yaml_file}")
    except ImportError:
        print("⚠️  PyYAML not installed. Install with: pip install PyYAML")
    except Exception as e:
        print(f"❌ Error loading YAML config: {e}")

def load_config_from_json(json_file: str) -> None:
    """Load configuration from JSON file"""
    try:
        import json
        with open(json_file, 'r') as f:
            json_config = json.load(f)
        CONFIG.update(json_config)
        print(f"✅ Loaded configuration from {json_file}")
    except Exception as e:
        print(f"❌ Error loading JSON config: {e}")

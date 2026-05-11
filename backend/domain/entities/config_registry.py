"""
Config Registry — single source of truth for every config key the admin
UI can read or write.

Each key is declared once with its namespace, type, default value, and
flags. ConfigService resolves values DB → env → default using this
registry, and the admin UI uses it to render sections, input widgets,
and sensitivity masks.

Flag semantics:
- ``sensitive``: masked in the admin UI and excluded from JSON exports
  unless the caller explicitly asks to include them.
- ``readonly``: shown but not editable from the UI (startup-only; needs
  a process restart to take effect).
- ``bootstrap``: core infrastructure value needed *before* the config
  layer is reachable (the DB URL, Redis URL, DB pool sizing, etc.).
  MUST be env-only — storing it in the DB would be a chicken-and-egg
  bootstrap cycle. ConfigService short-circuits bootstrap keys to
  os.environ without hitting the cache. Implies readonly.

Nested structures (AUTH_REQUIRED, RATE_LIMITS, HOOKS_HANDLERS) are NOT
in the registry — they need dedicated editors rather than a flat
key/value row.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ConfigKeyDef:
    key: str
    namespace: str
    value_type: str  # "string" | "int" | "boolean" | "float" | "json"
    default: str  # always stored as string
    sensitive: bool = False
    readonly: bool = False
    bootstrap: bool = False
    description: str = ""
    examples: str = ""

    def __post_init__(self):
        # bootstrap implies readonly — enforce once at registry build time
        if self.bootstrap and not self.readonly:
            object.__setattr__(self, "readonly", True)


def _build_registry(*groups: List[ConfigKeyDef]) -> Dict[str, ConfigKeyDef]:
    registry: Dict[str, ConfigKeyDef] = {}
    for group in groups:
        for defn in group:
            if defn.key in registry:
                raise ValueError(
                    f"Duplicate config key: {defn.key} "
                    f"(namespaces: {registry[defn.key].namespace}, {defn.namespace})"
                )
            registry[defn.key] = defn
    return registry


# ── Branding ────────────────────────────────────────────────────────────────

_BRANDING = [
    ConfigKeyDef("APP_NAME", "branding", "string", "Phoveus",
                 description="Application display name shown in UI and emails.",
                 examples="Phoveus, My SaaS"),
    ConfigKeyDef("APP_LEGAL_ENTITY", "branding", "string", "Phoveus",
                 description="Legal entity name for invoices and legal pages.",
                 examples="Phoveus, Example LLC"),
    ConfigKeyDef("APP_SUPPORT_EMAIL", "branding", "string", "phoveus@maborak.com",
                 description="Support email displayed to users.",
                 examples="support@example.com"),
    ConfigKeyDef("DOMAIN_UI_SCHEME", "branding", "string", "https",
                 description="Protocol scheme for links in outbound email "
                             "(verification, password reset).",
                 examples="https, http"),
    ConfigKeyDef("DOMAIN_UI", "branding", "string", "http://localhost:3000",
                 description="Frontend/UI origin used when building email links.",
                 examples="https://app.example.com"),
    ConfigKeyDef("FRONTEND_BASE_URL", "branding", "string", "http://localhost:5173",
                 description="Public frontend URL used for sitemap.xml and canonical links.",
                 examples="https://app.example.com"),
    ConfigKeyDef("SUPPORT_OUTBOUND_SENDER_NAME", "branding", "string", "Phoveus Support",
                 description="Default display name used by the support email sender.",
                 examples="Phoveus Support, Example Support"),
]

# ── Auth ────────────────────────────────────────────────────────────────────

_AUTH = [
    ConfigKeyDef("JWT_SECRET", "auth", "string",
                 "your-super-secret-jwt-key-here-change-this-in-production",
                 sensitive=True,
                 description="Secret key used to sign JWT tokens. Rotate on compromise.",
                 examples="openssl rand -hex 32"),
    ConfigKeyDef("JWT_ALGORITHM", "auth", "string", "HS256",
                 description="JWT signing algorithm.",
                 examples="HS256, RS256"),
    ConfigKeyDef("JWT_ACCESS_TOKEN_EXPIRY", "auth", "int", "900",
                 description="Access token lifetime in seconds.",
                 examples="900 (15m), 1800 (30m), 3600 (1h)"),
    ConfigKeyDef("JWT_REFRESH_TOKEN_EXPIRY", "auth", "int", "2592000",
                 description="Refresh token lifetime in seconds.",
                 examples="604800 (7d), 2592000 (30d)"),
    ConfigKeyDef("ACCOUNT_LOCKOUT_THRESHOLD", "auth", "int", "10",
                 description="Lock an account after this many consecutive failed password attempts.",
                 examples="5, 10, 20"),
    ConfigKeyDef("ACCOUNT_LOCKOUT_DURATION", "auth", "int", "300",
                 description="Seconds an account stays locked after the threshold is hit.",
                 examples="300 (5m), 900 (15m), 3600 (1h)"),
    ConfigKeyDef("COOKIE_LIFETIME", "auth", "int", "3600",
                 description="Session cookie lifetime in seconds.",
                 examples="3600 (1h), 86400 (1d)"),
]

# ── OAuth ───────────────────────────────────────────────────────────────────

_OAUTH = [
    ConfigKeyDef("GOOGLE_CLIENT_ID", "oauth", "string", "",
                 description="Google OAuth client ID. Leave blank to disable Google sign-in.",
                 examples="123456789-abc.apps.googleusercontent.com"),
    ConfigKeyDef("GITHUB_CLIENT_ID", "oauth", "string", "",
                 description="GitHub OAuth app client ID. Leave blank to disable GitHub sign-in."),
    ConfigKeyDef("GITHUB_CLIENT_SECRET", "oauth", "string", "",
                 sensitive=True,
                 description="GitHub OAuth app client secret."),
    ConfigKeyDef("FACEBOOK_APP_ID", "oauth", "string", "",
                 description="Facebook app ID. Leave blank to disable Facebook sign-in."),
    ConfigKeyDef("FACEBOOK_APP_SECRET", "oauth", "string", "",
                 sensitive=True,
                 description="Facebook app secret."),
]

# ── Billing ────────────────────────────────────────────────────────────────

_BILLING = [
    ConfigKeyDef("PAYPAL_CLIENT_ID", "billing", "string", "",
                 description="PayPal REST client ID. Leave blank to disable PayPal."),
    ConfigKeyDef("PAYPAL_SECRET", "billing", "string", "",
                 sensitive=True,
                 description="PayPal REST client secret."),
    ConfigKeyDef("PAYPAL_WEBHOOK_ID", "billing", "string", "",
                 description="PayPal webhook ID for signature verification."),
    ConfigKeyDef("PAYPAL_MODE", "billing", "string", "sandbox",
                 description="PayPal environment.",
                 examples="sandbox, live"),
    ConfigKeyDef("STRIPE_SECRET_KEY", "billing", "string", "",
                 sensitive=True,
                 description="Stripe secret API key (sk_live_... or sk_test_...)."),
    ConfigKeyDef("STRIPE_WEBHOOK_SECRET", "billing", "string", "",
                 sensitive=True,
                 description="Stripe webhook signing secret (whsec_...)."),
    ConfigKeyDef("REGISTRATION_CREDITS", "billing", "int", "5",
                 description="Credits granted to a user on registration.",
                 examples="0, 5, 100"),
]

# ── Database (bootstrap) ────────────────────────────────────────────────────

_DATABASE = [
    ConfigKeyDef("DATABASE_URL", "database", "string",
                 "sqlite:///./database/product_cache.db",
                 sensitive=True, bootstrap=True,
                 description="Primary database connection string. Env-only — "
                             "storing this in the DB would create a bootstrap cycle.",
                 examples="postgresql://user:pass@host:5432/db"),
    ConfigKeyDef("DB_ECHO", "database", "boolean", "false",
                 readonly=True,
                 description="Log every SQL statement. Requires restart.",
                 examples="true, false"),
    ConfigKeyDef("DB_ECHO_POOL", "database", "boolean", "false",
                 readonly=True,
                 description="Log connection-pool events. Requires restart."),
    ConfigKeyDef("DB_USE_REPLICA_ENGINE", "database", "boolean", "false",
                 bootstrap=True,
                 description="Use separate read/write engines for replica routing."),
    ConfigKeyDef("DB_READ_URL", "database", "string", "",
                 sensitive=True, bootstrap=True,
                 description="Optional read-replica URL. Used when DB_USE_REPLICA_ENGINE=true."),
    ConfigKeyDef("DB_WRITE_URL", "database", "string", "",
                 sensitive=True, bootstrap=True,
                 description="Optional write-master URL. Used when DB_USE_REPLICA_ENGINE=true."),
    ConfigKeyDef("DB_READ_POOL_SIZE", "database", "int", "10",
                 bootstrap=True,
                 description="Read-pool size when the replica engine is enabled."),
    ConfigKeyDef("DB_WRITE_POOL_SIZE", "database", "int", "20",
                 bootstrap=True,
                 description="Write-pool size when the replica engine is enabled."),
    ConfigKeyDef("DB_POOL_SIZE", "database", "int", "20",
                 bootstrap=True,
                 description="SQLAlchemy pool size."),
    ConfigKeyDef("DB_MAX_OVERFLOW", "database", "int", "30",
                 bootstrap=True,
                 description="Extra connections allowed beyond DB_POOL_SIZE."),
    ConfigKeyDef("DB_POOL_TIMEOUT", "database", "int", "30",
                 bootstrap=True,
                 description="Seconds to wait for a free connection."),
    ConfigKeyDef("DB_POOL_RECYCLE", "database", "int", "3600",
                 bootstrap=True,
                 description="Recycle connections older than this many seconds."),
]

# ── Server ──────────────────────────────────────────────────────────────────

_SERVER = [
    ConfigKeyDef("UVI_HOST", "server", "string", "0.0.0.0",
                 readonly=True,
                 description="Uvicorn bind host. Requires restart."),
    ConfigKeyDef("UVI_PORT", "server", "int", "9000",
                 readonly=True,
                 description="Uvicorn bind port. Requires restart."),
    ConfigKeyDef("UVI_WORKERS", "server", "int", "5",
                 readonly=True,
                 description="Uvicorn worker count. Requires restart."),
    ConfigKeyDef("UVI_ACCESS_LOG", "server", "boolean", "true",
                 readonly=True,
                 description="Emit uvicorn access logs."),
    ConfigKeyDef("UVI_LIMIT_CONCURRENCY", "server", "int", "100",
                 readonly=True,
                 description="Max concurrent requests per worker."),
    ConfigKeyDef("UVI_LIMIT_MAX_REQUESTS", "server", "int", "1000",
                 readonly=True,
                 description="Worker recycles after this many requests."),
    ConfigKeyDef("UVI_TIMEOUT_KEEP_ALIVE", "server", "int", "30",
                 readonly=True,
                 description="Seconds to keep an idle connection open."),
    ConfigKeyDef("UVI_TIMEOUT_GRACEFUL_SHUTDOWN", "server", "int", "30",
                 readonly=True,
                 description="Seconds to wait for in-flight requests on shutdown."),
    ConfigKeyDef("RELOAD", "server", "boolean", "false",
                 readonly=True,
                 description="Uvicorn auto-reload. Dev only."),
    ConfigKeyDef("DEBUG_MODE", "server", "boolean", "false",
                 readonly=True,
                 description="Umbrella debug flag. Enables DB echo, verbose logs, auto-reload."),
    ConfigKeyDef("ENABLE_DOCS", "server", "boolean", "false",
                 description="Expose /docs, /redoc, /openapi.json."),
    ConfigKeyDef("LOG_LEVEL", "server", "string", "info",
                 description="Root logger level.",
                 examples="debug, info, warning, error"),
    ConfigKeyDef("LOG_OUTPUT", "server", "string", "both",
                 description="Where logs are written.",
                 examples="stdout, file, both"),
    ConfigKeyDef("LOG_FORMAT", "server", "string", "json",
                 description="Log record format.",
                 examples="json, pretty, text"),
]

# ── CORS ────────────────────────────────────────────────────────────────────

_CORS = [
    ConfigKeyDef("CORS_ORIGINS", "cors", "string", "*",
                 description="Comma-separated list of allowed origins, or '*' for all.",
                 examples="https://app.example.com,https://admin.example.com"),
    ConfigKeyDef("CORS_ALLOW_CREDENTIALS", "cors", "boolean", "true",
                 description="Allow credentialled CORS requests."),
    ConfigKeyDef("CORS_ALLOW_METHODS", "cors", "string", "*",
                 description="Comma-separated list of allowed methods, or '*' for all.",
                 examples="GET,POST,PUT,DELETE"),
    ConfigKeyDef("CORS_ALLOW_HEADERS", "cors", "string", "*",
                 description="Comma-separated list of allowed headers, or '*' for all."),
    ConfigKeyDef("CORS_MAX_AGE", "cors", "int", "600",
                 description="Max age for preflight requests (seconds)."),
]

# ── CAPTCHA ────────────────────────────────────────────────────────────────

_CAPTCHA = [
    ConfigKeyDef("CAPTCHA_TYPE", "captcha", "string", "none",
                 description="Active CAPTCHA provider.",
                 examples="none, recaptcha_v3, turnstile"),
    ConfigKeyDef("RECAPTCHA_V3_SECRET_KEY", "captcha", "string", "",
                 sensitive=True,
                 description="Google reCAPTCHA v3 secret key."),
    ConfigKeyDef("RECAPTCHA_V3_THRESHOLD", "captcha", "float", "0.5",
                 description="Minimum reCAPTCHA v3 score to accept (0.0–1.0).",
                 examples="0.5, 0.7"),
    ConfigKeyDef("TURNSTILE_SECRET_KEY", "captcha", "string", "",
                 sensitive=True,
                 description="Cloudflare Turnstile secret key."),
    ConfigKeyDef("CAPTCHA_TRUST_WINDOW", "captcha", "int", "300",
                 description="Seconds a successful CAPTCHA grants trust for follow-up requests."),
    ConfigKeyDef("LOGIN_CAPTCHA_THRESHOLD", "captcha", "int", "1",
                 description="Require CAPTCHA after this many failed logins. 0 disables."),
]

# ── Rate limits ────────────────────────────────────────────────────────────

_RATE_LIMITS = [
    ConfigKeyDef("RATE_LIMIT_ENABLED", "rate_limits", "boolean", "true",
                 description="Master switch for rate limiting middleware."),
    ConfigKeyDef("RATE_LIMIT_REQUESTS", "rate_limits", "int", "60",
                 description="Base request budget per window."),
    ConfigKeyDef("RATE_LIMIT_WINDOW", "rate_limits", "int", "60",
                 description="Rate-limit window length in seconds."),
    ConfigKeyDef("RATE_LIMIT_BYPASS_KEY", "rate_limits", "string", "",
                 sensitive=True,
                 description="Shared secret that bypasses rate limiting when sent as a header."),
]

# ── Email — support inbound (IMAP) ─────────────────────────────────────────

_EMAIL_SUPPORT = [
    ConfigKeyDef("SUPPORT_INBOUND_SERVER", "email_support", "string", "imap.gmail.com",
                 description="IMAP server hostname for the support inbox."),
    ConfigKeyDef("SUPPORT_INBOUND_PORT", "email_support", "int", "993",
                 description="IMAP server port."),
    ConfigKeyDef("SUPPORT_INBOUND_USERNAME", "email_support", "string", "",
                 description="IMAP login username."),
    ConfigKeyDef("SUPPORT_INBOUND_EMAIL", "email_support", "string", "",
                 description="Email address being polled."),
    ConfigKeyDef("SUPPORT_INBOUND_PASSWORD", "email_support", "string", "",
                 sensitive=True,
                 description="IMAP login password or app password."),
    ConfigKeyDef("SUPPORT_INBOUND_USE_SSL", "email_support", "boolean", "true",
                 description="Connect to IMAP over SSL."),
]

# ── Email — outbound hook (SMTP) ───────────────────────────────────────────

_EMAIL_HOOK = [
    ConfigKeyDef("HOOK_EMAIL_ENABLED", "email_hook", "boolean", "false",
                 description="Master switch for the outbound email hook."),
    ConfigKeyDef("HOOK_EMAIL_SENDER", "email_hook", "string", "",
                 description="Envelope + From address for outbound mail."),
    ConfigKeyDef("HOOK_EMAIL_SENDER_NAME", "email_hook", "string", "",
                 description="Display name used in the From header. Falls back to APP_NAME when empty."),
    ConfigKeyDef("HOOK_EMAIL_RECEIVER", "email_hook", "string", "",
                 description="Optional default recipient for system notifications."),
    ConfigKeyDef("HOOK_EMAIL_USERNAME", "email_hook", "string", "",
                 description="SMTP login username. Defaults to HOOK_EMAIL_SENDER when empty."),
    ConfigKeyDef("HOOK_EMAIL_PASSWORD", "email_hook", "string", "",
                 sensitive=True,
                 description="SMTP login password or app password."),
    ConfigKeyDef("HOOK_EMAIL_SMTP_HOST", "email_hook", "string", "localhost",
                 description="SMTP server hostname."),
    ConfigKeyDef("HOOK_EMAIL_SMTP_PORT", "email_hook", "int", "465",
                 description="SMTP server port."),
    ConfigKeyDef("HOOK_EMAIL_SMTP_SECURITY", "email_hook", "string", "ssl",
                 description="SMTP connection security.",
                 examples="ssl, starttls, plain"),
    ConfigKeyDef("HOOK_EMAIL_SMTP_VERIFY_SSL", "email_hook", "boolean", "true",
                 description="Verify SMTP TLS certificate."),
    ConfigKeyDef("HOOK_EMAIL_CONTENT_ENCODING", "email_hook", "string", "quoted-printable",
                 description="MIME content-transfer-encoding for outbound email bodies.",
                 examples="quoted-printable, base64, 7bit"),
    ConfigKeyDef("HOOK_EMAIL_TEMPLATE_SET", "email_hook", "string", "default",
                 description="Email template set to use."),
    ConfigKeyDef("HOOK_EMAIL_NOTIFY_VERIFICATION", "email_hook", "boolean", "true",
                 description="Send an email when a user requests account verification."),
    ConfigKeyDef("HOOK_EMAIL_VERIFICATION_PATH", "email_hook", "string", "/account/verify",
                 description="Relative path appended to DOMAIN_UI for verification links."),
    ConfigKeyDef("HOOK_EMAIL_RECIPIENT_VERIFICATION_PATH", "email_hook", "string",
                 "/account/verify-recipient",
                 description="Relative path for recipient verification links."),
    ConfigKeyDef("HOOK_EMAIL_NOTIFY_PASSWORD_RESET", "email_hook", "boolean", "true",
                 description="Send an email on password-reset requests."),
    ConfigKeyDef("HOOK_EMAIL_PASSWORD_RESET_PATH", "email_hook", "string",
                 "/account/reset-password",
                 description="Relative path for password reset links."),
]

# ── Notifications queue ────────────────────────────────────────────────────

_NOTIFICATIONS = [
    ConfigKeyDef("NOTIFICATION_QUEUE_ENABLED", "notifications", "boolean", "true",
                 description="Master switch for the notification queue consumer."),
    ConfigKeyDef("NOTIFICATION_QUEUE_EMAIL_CONCURRENCY", "notifications", "int", "10",
                 description="Concurrent email sends from the queue."),
    ConfigKeyDef("NOTIFICATION_QUEUE_MAX_RETRIES", "notifications", "int", "5",
                 description="Max retries before a notification is dead-lettered."),
    ConfigKeyDef("NOTIFICATION_QUEUE_RETRY_BASE_SECONDS", "notifications", "int", "30",
                 description="Base backoff between retries (seconds)."),
    ConfigKeyDef("NOTIFICATION_QUEUE_RETRY_MAX_SECONDS", "notifications", "int", "3600",
                 description="Ceiling on exponential-backoff retry delay."),
    ConfigKeyDef("NOTIFICATION_QUEUE_EMAIL_RATE_MAX", "notifications", "int", "100",
                 description="Max emails per rate window."),
    ConfigKeyDef("NOTIFICATION_QUEUE_EMAIL_RATE_WINDOW", "notifications", "int", "60",
                 description="Rate window length (seconds)."),
    ConfigKeyDef("NOTIFICATION_QUEUE_CONSUMER_SHUTDOWN_TIMEOUT", "notifications", "int", "30",
                 description="Seconds the consumer has to drain on shutdown."),
    ConfigKeyDef("NOTIFICATION_QUEUE_RETRY_POLL_INTERVAL", "notifications", "int", "5",
                 description="Seconds between retry-queue polls."),
]

# ── Security / proxy ──────────────────────────────────────────────────────

_SECURITY = [
    ConfigKeyDef("TRUST_PROXY_HEADERS", "security", "boolean", "false",
                 description="Trust X-Forwarded-For / X-Real-IP when determining client IP. "
                             "Only enable behind a trusted reverse proxy."),
    ConfigKeyDef("TRUSTED_PROXY_DEPTH", "security", "int", "1",
                 description="How many proxies deep the real client IP is in X-Forwarded-For."),
    ConfigKeyDef("PRL_LOGIN", "security", "string", "0,0,0,5,15,30,C,C60,C600",
                 description="Progressive rate limit for /auth/login. "
                             "Comma-separated steps; number = delay seconds, "
                             "C = require captcha, C<N> = captcha + delay."),
    ConfigKeyDef("PRL_RESEND_VERIFICATION", "security", "string",
                 "1,5,30,60,600,C,C60,C3600",
                 description="Progressive rate limit for resend-verification endpoint."),
    ConfigKeyDef("PRL_CONFIRM_LINK", "security", "string",
                 "1,5,30,C,C60,C600",
                 description="Progressive rate limit for verification link confirmation."),
]

# ── Events / monitoring ───────────────────────────────────────────────────

_EVENTS = [
    ConfigKeyDef("EVENT_RETENTION_DAYS", "events", "int", "30",
                 description="Days of hook-event history to retain before pruning."),
]

# ── Storage paths ─────────────────────────────────────────────────────────

_STORAGE = [
    ConfigKeyDef("TICKET_UPLOAD_STORAGE_PATH", "storage", "string", "data/uploads/tickets",
                 description="Directory where ticket attachments are written.",
                 examples="data/uploads/tickets"),
    ConfigKeyDef("LIVECHAT_UPLOAD_STORAGE_PATH", "storage", "string", "data/uploads/livechat",
                 description="Directory where livechat attachments are written.",
                 examples="data/uploads/livechat"),
]

# ── Misc ──────────────────────────────────────────────────────────────────

_MISC = [
    ConfigKeyDef("REDIS_URL", "misc", "string", "",
                 sensitive=True, bootstrap=True,
                 description="Redis connection URL. Leave blank to fall back to in-process "
                             "state for rate limiting and CAPTCHA trust.",
                 examples="redis://localhost:6379/0"),
]

# ── TikTok ──────────────────────────────────────────────────────────────────
#
# The TikTok read pipeline (TikTokLive WebCast WS) needs a signed connect
# URL. TikTok's signing is undocumented + rotating, so we delegate to one
# of two providers:
#
#   - "euler"   — EulerStream sign-as-a-service. Free tier is heavily
#                 rate-limited; an API key raises the budget.
#   - "session" — pass a TikTok `sessionid` cookie through TikTokLive's
#                 web client. TikTok signs for "logged-in" users without
#                 going through EulerStream. Bound to one TikTok account.

_TIKTOK = [
    ConfigKeyDef("TIKTOK_SIGN_PROVIDER", "tiktok", "string", "euler",
                 description="Which signer to use for TikTok WebCast WS connects: "
                             "'euler' (EulerStream sign-as-a-service), "
                             "'session' (session-authenticated EulerStream — better quotas), "
                             "or 'local' (Electron-hosted broker — zero third-party).",
                 examples="euler, session, local"),
    ConfigKeyDef("TIKTOK_LOCAL_SIGN_URL", "tiktok", "string", "http://127.0.0.1:21214",
                 description="When TIKTOK_SIGN_PROVIDER=local, the URL of the "
                             "Electron-hosted sign broker. Default points at the "
                             "loopback port the bundled client opens.",
                 examples="http://127.0.0.1:21214"),
    ConfigKeyDef("TIKTOK_EULER_API_KEY", "tiktok", "string", "",
                 sensitive=True,
                 description="EulerStream API key. Free tier works without one but is "
                             "harshly rate-limited. Sign up at https://www.eulerstream.com.",
                 examples="euler_..."),
    ConfigKeyDef("TIKTOK_SESSION_ID", "tiktok", "string", "",
                 sensitive=True,
                 description="TikTok `sessionid` cookie value, used when "
                             "TIKTOK_SIGN_PROVIDER=session. Get it from your logged-in "
                             "browser's cookies for tiktok.com. Tied to your account; "
                             "rotate on suspected ban risk.",
                 examples="(64-char hex string from tiktok.com cookies)"),
    ConfigKeyDef("TIKTOK_SESSION_TT_TARGET_IDC", "tiktok", "string", "",
                 sensitive=True,
                 description="Optional `tt-target-idc` cookie partner for TIKTOK_SESSION_ID. "
                             "Required for some accounts (typically apps in the EU/UK pool). "
                             "If unsure leave blank — TikTokLive defaults work for most.",
                 examples="useast2a, useast1a, alisg"),
]


# ── Registry build ────────────────────────────────────────────────────────

CONFIG_REGISTRY: Dict[str, ConfigKeyDef] = _build_registry(
    _BRANDING,
    _AUTH,
    _OAUTH,
    _BILLING,
    _DATABASE,
    _SERVER,
    _CORS,
    _CAPTCHA,
    _RATE_LIMITS,
    _EMAIL_SUPPORT,
    _EMAIL_HOOK,
    _NOTIFICATIONS,
    _SECURITY,
    _EVENTS,
    _STORAGE,
    _MISC,
    _TIKTOK,
)


# ── ENV_MAP: registry key → env var name ─────────────────────────────────
#
# The framework's env-var prefix is still PHOVEU_ (legacy). See MEMORY.md —
# rename to MBK_ is a pending task, handled elsewhere.

ENV_MAP: Dict[str, str] = {
    # Branding
    "APP_NAME": "PHOVEU_APP_NAME",
    "APP_LEGAL_ENTITY": "PHOVEU_APP_LEGAL_ENTITY",
    "APP_SUPPORT_EMAIL": "PHOVEU_SUPPORT_EMAIL",
    "DOMAIN_UI_SCHEME": "DOMAIN_UI_SCHEME",
    "DOMAIN_UI": "DOMAIN_UI",
    "FRONTEND_BASE_URL": "PHOVEU_FRONTEND_BASE_URL",
    "SUPPORT_OUTBOUND_SENDER_NAME": "PHOVEU_SUPPORT_OUTBOUND_SENDER_NAME",
    # Auth
    "JWT_SECRET": "PHOVEU_BACKEND_JWT_SECRET",
    "JWT_ALGORITHM": "PHOVEU_BACKEND_JWT_ALGORITHM",
    "JWT_ACCESS_TOKEN_EXPIRY": "PHOVEU_BACKEND_JWT_ACCESS_TOKEN_EXPIRY",
    "JWT_REFRESH_TOKEN_EXPIRY": "PHOVEU_BACKEND_JWT_REFRESH_TOKEN_EXPIRY",
    "ACCOUNT_LOCKOUT_THRESHOLD": "PHOVEU_BACKEND_ACCOUNT_LOCKOUT_THRESHOLD",
    "ACCOUNT_LOCKOUT_DURATION": "PHOVEU_BACKEND_ACCOUNT_LOCKOUT_DURATION",
    "COOKIE_LIFETIME": "PHOVEU_BACKEND_COOKIE_LIFETIME",
    # OAuth
    "GOOGLE_CLIENT_ID": "PHOVEU_BACKEND_GOOGLE_CLIENT_ID",
    "GITHUB_CLIENT_ID": "PHOVEU_BACKEND_GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET": "PHOVEU_BACKEND_GITHUB_CLIENT_SECRET",
    "FACEBOOK_APP_ID": "PHOVEU_BACKEND_FACEBOOK_APP_ID",
    "FACEBOOK_APP_SECRET": "PHOVEU_BACKEND_FACEBOOK_APP_SECRET",
    # Billing
    "PAYPAL_CLIENT_ID": "PHOVEU_BACKEND_PAYPAL_CLIENT_ID",
    "PAYPAL_SECRET": "PHOVEU_BACKEND_PAYPAL_SECRET",
    "PAYPAL_WEBHOOK_ID": "PHOVEU_BACKEND_PAYPAL_WEBHOOK_ID",
    "PAYPAL_MODE": "PHOVEU_BACKEND_PAYPAL_MODE",
    "STRIPE_SECRET_KEY": "PHOVEU_BACKEND_STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET": "PHOVEU_BACKEND_STRIPE_WEBHOOK_SECRET",
    "REGISTRATION_CREDITS": "PHOVEU_REGISTRATION_CREDITS",
    # Database
    "DATABASE_URL": "PHOVEU_BACKEND_DATABASE_URL",
    "DB_ECHO": "PHOVEU_BACKEND_DB_ECHO",
    "DB_ECHO_POOL": "PHOVEU_BACKEND_DB_ECHO_POOL",
    "DB_USE_REPLICA_ENGINE": "PHOVEU_BACKEND_DB_USE_REPLICA_ENGINE",
    "DB_READ_URL": "PHOVEU_BACKEND_DB_READ_URL",
    "DB_WRITE_URL": "PHOVEU_BACKEND_DB_WRITE_URL",
    "DB_READ_POOL_SIZE": "PHOVEU_BACKEND_DB_READ_POOL_SIZE",
    "DB_WRITE_POOL_SIZE": "PHOVEU_BACKEND_DB_WRITE_POOL_SIZE",
    "DB_POOL_SIZE": "PHOVEU_BACKEND_DB_POOL_SIZE",
    "DB_MAX_OVERFLOW": "PHOVEU_BACKEND_DB_MAX_OVERFLOW",
    "DB_POOL_TIMEOUT": "PHOVEU_BACKEND_DB_POOL_TIMEOUT",
    "DB_POOL_RECYCLE": "PHOVEU_BACKEND_DB_POOL_RECYCLE",
    # Server
    "UVI_HOST": "PHOVEU_BACKEND_UVI_HOST",
    "UVI_PORT": "PHOVEU_BACKEND_UVI_PORT",
    "UVI_WORKERS": "PHOVEU_BACKEND_UVI_WORKERS",
    "UVI_ACCESS_LOG": "PHOVEU_BACKEND_UVI_ACCESS_LOG",
    "UVI_LIMIT_CONCURRENCY": "PHOVEU_BACKEND_UVI_LIMIT_CONCURRENCY",
    "UVI_LIMIT_MAX_REQUESTS": "PHOVEU_BACKEND_UVI_LIMIT_MAX_REQUESTS",
    "UVI_TIMEOUT_KEEP_ALIVE": "PHOVEU_BACKEND_UVI_TIMEOUT_KEEP_ALIVE",
    "UVI_TIMEOUT_GRACEFUL_SHUTDOWN": "PHOVEU_BACKEND_UVI_TIMEOUT_GRACEFUL_SHUTDOWN",
    "RELOAD": "PHOVEU_BACKEND_RELOAD",
    "DEBUG_MODE": "PHOVEU_BACKEND_DEBUG_MODE",
    "ENABLE_DOCS": "PHOVEU_BACKEND_ENABLE_DOCS",
    "LOG_LEVEL": "PHOVEU_BACKEND_LOG_LEVEL",
    "LOG_OUTPUT": "PHOVEU_BACKEND_LOG_OUTPUT",
    "LOG_FORMAT": "PHOVEU_BACKEND_LOG_FORMAT",
    # CORS
    "CORS_ORIGINS": "PHOVEU_BACKEND_CORS_ORIGINS",
    "CORS_ALLOW_CREDENTIALS": "PHOVEU_BACKEND_CORS_ALLOW_CREDENTIALS",
    "CORS_ALLOW_METHODS": "PHOVEU_BACKEND_CORS_ALLOW_METHODS",
    "CORS_ALLOW_HEADERS": "PHOVEU_BACKEND_CORS_ALLOW_HEADERS",
    "CORS_MAX_AGE": "PHOVEU_BACKEND_CORS_MAX_AGE",
    # CAPTCHA
    "CAPTCHA_TYPE": "PHOVEU_BACKEND_CAPTCHA_TYPE",
    "RECAPTCHA_V3_SECRET_KEY": "PHOVEU_BACKEND_RECAPTCHA_V3_SECRET_KEY",
    "RECAPTCHA_V3_THRESHOLD": "PHOVEU_BACKEND_RECAPTCHA_V3_THRESHOLD",
    "TURNSTILE_SECRET_KEY": "PHOVEU_BACKEND_TURNSTILE_SECRET_KEY",
    "CAPTCHA_TRUST_WINDOW": "PHOVEU_BACKEND_CAPTCHA_TRUST_WINDOW",
    "LOGIN_CAPTCHA_THRESHOLD": "PHOVEU_BACKEND_LOGIN_CAPTCHA_THRESHOLD",
    # Rate limits
    "RATE_LIMIT_ENABLED": "PHOVEU_BACKEND_RATE_LIMIT_ENABLED",
    "RATE_LIMIT_REQUESTS": "PHOVEU_BACKEND_RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_WINDOW": "PHOVEU_BACKEND_RATE_LIMIT_WINDOW",
    "RATE_LIMIT_BYPASS_KEY": "PHOVEU_BACKEND_RATE_LIMIT_BYPASS_KEY",
    # Email — support inbound
    "SUPPORT_INBOUND_SERVER": "PHOVEU_SUPPORT_INBOUND_SERVER",
    "SUPPORT_INBOUND_PORT": "PHOVEU_SUPPORT_INBOUND_PORT",
    "SUPPORT_INBOUND_USERNAME": "PHOVEU_SUPPORT_INBOUND_USERNAME",
    "SUPPORT_INBOUND_EMAIL": "PHOVEU_SUPPORT_INBOUND_EMAIL",
    "SUPPORT_INBOUND_PASSWORD": "PHOVEU_SUPPORT_INBOUND_PASSWORD",
    "SUPPORT_INBOUND_USE_SSL": "PHOVEU_SUPPORT_INBOUND_USE_SSL",
    # Email — outbound hook
    "HOOK_EMAIL_ENABLED": "PHOVEU_BACKEND_HOOK_EMAIL_ENABLED",
    "HOOK_EMAIL_SENDER": "PHOVEU_BACKEND_HOOK_EMAIL_SENDER",
    "HOOK_EMAIL_SENDER_NAME": "PHOVEU_BACKEND_HOOK_EMAIL_SENDER_NAME",
    "HOOK_EMAIL_RECEIVER": "PHOVEU_BACKEND_HOOK_EMAIL_RECEIVER",
    "HOOK_EMAIL_USERNAME": "PHOVEU_BACKEND_HOOK_EMAIL_USERNAME",
    "HOOK_EMAIL_PASSWORD": "PHOVEU_BACKEND_HOOK_EMAIL_PASSWORD",
    "HOOK_EMAIL_SMTP_HOST": "PHOVEU_BACKEND_HOOK_EMAIL_SMTP_HOST",
    "HOOK_EMAIL_SMTP_PORT": "PHOVEU_BACKEND_HOOK_EMAIL_SMTP_PORT",
    "HOOK_EMAIL_SMTP_SECURITY": "PHOVEU_BACKEND_HOOK_EMAIL_SMTP_SECURITY",
    "HOOK_EMAIL_SMTP_VERIFY_SSL": "PHOVEU_BACKEND_HOOK_EMAIL_SMTP_VERIFY_SSL",
    "HOOK_EMAIL_CONTENT_ENCODING": "PHOVEU_BACKEND_HOOK_EMAIL_CONTENT_ENCODING",
    "HOOK_EMAIL_TEMPLATE_SET": "PHOVEU_BACKEND_HOOK_EMAIL_TEMPLATE_SET",
    "HOOK_EMAIL_NOTIFY_VERIFICATION": "PHOVEU_BACKEND_HOOK_EMAIL_NOTIFY_VERIFICATION",
    "HOOK_EMAIL_VERIFICATION_PATH": "PHOVEU_BACKEND_HOOK_EMAIL_VERIFICATION_PATH",
    "HOOK_EMAIL_RECIPIENT_VERIFICATION_PATH": "PHOVEU_BACKEND_HOOK_EMAIL_RECIPIENT_VERIFICATION_PATH",
    "HOOK_EMAIL_NOTIFY_PASSWORD_RESET": "PHOVEU_BACKEND_HOOK_EMAIL_NOTIFY_PASSWORD_RESET",
    "HOOK_EMAIL_PASSWORD_RESET_PATH": "PHOVEU_BACKEND_HOOK_EMAIL_PASSWORD_RESET_PATH",
    # Notifications
    "NOTIFICATION_QUEUE_ENABLED": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_ENABLED",
    "NOTIFICATION_QUEUE_EMAIL_CONCURRENCY": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_EMAIL_CONCURRENCY",
    "NOTIFICATION_QUEUE_MAX_RETRIES": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_MAX_RETRIES",
    "NOTIFICATION_QUEUE_RETRY_BASE_SECONDS": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_RETRY_BASE_SECONDS",
    "NOTIFICATION_QUEUE_RETRY_MAX_SECONDS": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_RETRY_MAX_SECONDS",
    "NOTIFICATION_QUEUE_EMAIL_RATE_MAX": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_EMAIL_RATE_MAX",
    "NOTIFICATION_QUEUE_EMAIL_RATE_WINDOW": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_EMAIL_RATE_WINDOW",
    "NOTIFICATION_QUEUE_CONSUMER_SHUTDOWN_TIMEOUT": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_CONSUMER_SHUTDOWN_TIMEOUT",
    "NOTIFICATION_QUEUE_RETRY_POLL_INTERVAL": "PHOVEU_BACKEND_NOTIFICATION_QUEUE_RETRY_POLL_INTERVAL",
    # Security / proxy
    "TRUST_PROXY_HEADERS": "PHOVEU_BACKEND_TRUST_PROXY_HEADERS",
    "TRUSTED_PROXY_DEPTH": "PHOVEU_BACKEND_TRUSTED_PROXY_DEPTH",
    "PRL_LOGIN": "PHOVEU_BACKEND_PRL_LOGIN",
    "PRL_RESEND_VERIFICATION": "PHOVEU_BACKEND_PRL_RESEND_VERIFICATION",
    "PRL_CONFIRM_LINK": "PHOVEU_BACKEND_PRL_CONFIRM_LINK",
    # Events / monitoring
    "EVENT_RETENTION_DAYS": "PHOVEU_BACKEND_EVENT_RETENTION_DAYS",
    # Storage
    "TICKET_UPLOAD_STORAGE_PATH": "PHOVEU_BACKEND_TICKET_UPLOAD_STORAGE_PATH",
    "LIVECHAT_UPLOAD_STORAGE_PATH": "PHOVEU_BACKEND_LIVECHAT_UPLOAD_STORAGE_PATH",
    # Misc
    "REDIS_URL": "PHOVEU_REDIS_SERVER",
    # TikTok
    "TIKTOK_SIGN_PROVIDER": "PHOVEU_BACKEND_TIKTOK_SIGN_PROVIDER",
    "TIKTOK_EULER_API_KEY": "PHOVEU_BACKEND_TIKTOK_EULER_API_KEY",
    "TIKTOK_SESSION_ID": "PHOVEU_BACKEND_TIKTOK_SESSION_ID",
    "TIKTOK_SESSION_TT_TARGET_IDC": "PHOVEU_BACKEND_TIKTOK_SESSION_TT_TARGET_IDC",
    "TIKTOK_LOCAL_SIGN_URL": "PHOVEU_BACKEND_TIKTOK_LOCAL_SIGN_URL",
}


def get_namespaces() -> List[str]:
    """Sorted list of unique namespaces in the registry."""
    return sorted({d.namespace for d in CONFIG_REGISTRY.values()})


def get_keys_for_namespace(namespace: str) -> List[ConfigKeyDef]:
    """All ConfigKeyDefs in a namespace, sorted by key name."""
    return sorted(
        (d for d in CONFIG_REGISTRY.values() if d.namespace == namespace),
        key=lambda d: d.key,
    )

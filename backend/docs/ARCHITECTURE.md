# Architecture

## Overview

The backend is a Python FastAPI application following hexagonal architecture (ports and adapters). The application entry point is `api_main.py`, which wires all services and mounts all routers. The ASGI server is Uvicorn, listening on port 9000 by default (`UVI_PORT` in `config.py`).

## Directory Structure

```
api_main.py                    # Application entry point, service wiring, middleware
config.py                      # Centralized CONFIG dict
routes/
  main.py                      # Router registration and mounting
  auth.py                      # /auth/* endpoints
  queue.py                     # /queue/* endpoints (worker protocol)
  webhooks.py                  # /webhooks/paypal, /webhooks/stripe
  products.py                  # /products/* endpoints
  user/
    account/
      billing.py               # /user/account/billing/*
      tracked_products.py      # /user/account/tracked-products/*
      price_alerts.py          # /user/account/price-alerts/*
      recipients.py            # /user/account/recipients/*
      info.py                  # /user/account/info/*
      models.py                # Pydantic request/response models for account routes
  admin/
    billing.py                 # /admin/billing/*
    users.py                   # /admin/users/*
    tickets.py                 # /admin/tickets/*
    rbac.py                    # /admin/rbac/*
    payment_gateways.py        # /admin/payment-gateways/*
    general.py                 # /admin/general/*
    countries.py               # /admin/countries/*
    cookies.py                 # /admin/cookies/*
    scraper.py                 # /admin/scraper/*
    synthetics.py              # /admin/synthetics/*
ports/
  auth.py                      # AuthPort, UserManagementPort, SessionManagementPort, ApiKeyManagementPort, AuthorizationPort, UserProductPort
  data_persistence.py          # DataPersistencePort (70+ abstract methods)
  payment_gateway.py           # PaymentGatewayPort
  product_data.py              # ProductDataSourcePort
  display.py                   # DisplayPort
  screenshot.py                # ScreenshotPort
domain/
  entities/
    auth_models.py             # User, UserSession, ApiKey, UserRole, AuthStatus, AuthContext
    billing_models.py          # CreditPackage, PaymentTransaction, Invoice, CreditLedgerEntry, PaymentProvider, PaymentStatus, LedgerSource
    models.py                  # Product, Currency, Country, ProductState, ShippingInfo, ProductCheckResult, MonitoringConfig
    price_alert_models.py      # PriceAlert, PriceAlertTrigger, ProductTrack, PriceAlertHistory, TriggerType, TriggerTarget, LogicOperator
    queue_schemas.py           # QueueTaskResponse, QueueSubmissionRequest, TaskDetail, LastPriceInfo, CheckResultData
    rbac_models.py             # Permission, RolePermission, UserPermission
    recipient_models.py        # Recipient, RecipientType
    ticket_models.py           # Ticket, TicketStatus, TicketPriority, TicketOrigin, LiveChatSession, LiveChatMessage
  services/
    auth_service.py            # AuthService (login, register, JWT, sessions, impersonation)
    credit_service.py          # CreditService (balance, consume, renew_track)
    payment_service.py         # PaymentService (initialize, capture, webhook processing)
    price_alert_manager.py     # PriceAlertManager (evaluate_alert, _evaluate_trigger)
    product_service.py         # ProductService (add_product_to_user, process_remote_submission)
    ticket_service.py          # TicketService
    monitoring_service.py      # MonitoringService
    monitor_system.py          # MonitorSystem
    services.py                # Service container / factory
  exceptions.py                # ProductNotFoundError, CaptchaDetectedError
adapters/
  auth_persistence.py          # Implements AuthPort and related auth ports
  database_persistence.py      # Implements DataPersistencePort (primary DB adapter)
  stripe_payment.py            # Implements PaymentGatewayPort for Stripe
  paypal_payment.py            # Implements PaymentGatewayPort for PayPal
  web_scraping.py              # Implements ProductDataSourcePort
  http_engine.py               # HTTP client utilities
  hooks/
    price_alert_handler.py     # PriceAlertHandler (HookHandler subclass)
    email_handler.py           # EmailHandler (HookHandler subclass)
    log_handler.py             # LogHandler (HookHandler subclass)
database/
  core/
    base.py                    # SQLAlchemy declarative Base
    engine.py                  # Engine creation, read/write separation
  auth/
    models.py                  # User, UserSession, ApiKey, EmailVerification, PasswordReset
    rbac_models.py             # RBAC SQLAlchemy models
  billing/
    models.py                  # CreditPackageModel, PaymentTransactionModel, CreditLedgerModel, InvoiceModel, PaymentGatewayConfigModel
  price_alerts/
    models.py                  # Recipient, RecipientVerification, PriceAlert, PriceAlertTrigger, ProductTrack, PriceAlertHistoryModel
  user_products/
    models.py                  # UserProduct (legacy)
    visits.py                  # Visit history models
  product/
    models.py                  # Product cache models
  tickets/
    models.py                  # Ticket models
  monitoring/
    models.py                  # Monitoring models
  price/
    models.py                  # Price history models
  hooks/
    models.py                  # Hook event models
  cookie/
    models.py                  # Cookie/session storage models
  scraper/
    models.py                  # Scraper config models
  synthetics/
    models.py                  # Synthetic check models
  logging/
    models.py                  # Application log models
  performance/
    models.py                  # Performance metric models
  currency/
    models.py                  # Currency models
  country/
    models.py                  # Country models
  migrations/
    add_price_alert_history.py # Migration: add price_alert_history table
utils/
  security/
    captcha.py                 # CaptchaValidator (supports none/recaptcha_v3/turnstile)
    rbac.py                    # RBACDependency, singleton rbac instance
  database/
    schema_checker.py          # Schema validation utilities
templates/
  email/
    {template_set}/            # Jinja2 email templates
```

## Application Startup

`api_main.py` defines a `lifespan` context manager and `initialize_services()` function. At startup:

1. `initialize_services()` is called, which instantiates all adapters and services and calls `setup_routes(app)`.
2. `setup_routes()` in `routes/main.py` registers all sub-routers with their path prefixes.
3. Middleware is applied in this order: CORS, security headers, rate limiting, request logging.

The `main()` CLI entrypoint is implemented with `click`, enabling `python api_main.py` to start the server.

## Hexagonal Architecture

The application follows hexagonal architecture with the following boundaries:

**Ports** (abstract interfaces in `ports/`):
- `DataPersistencePort` — all database read/write operations
- `AuthPort`, `UserManagementPort`, `SessionManagementPort`, `ApiKeyManagementPort`, `AuthorizationPort`, `UserProductPort` — authentication operations
- `PaymentGatewayPort` — payment provider operations
- `ProductDataSourcePort` — external product data fetching

**Adapters** (concrete implementations in `adapters/`):
- `DatabaseDataPersistenceAdapter` implements `DataPersistencePort` (SQLAlchemy + SQLite/configurable)
- `AuthPersistenceAdapter` implements auth ports
- `StripePaymentAdapter` and `PayPalPaymentAdapter` implement `PaymentGatewayPort`
- `WebScrapingAdapter` implements `ProductDataSourcePort`

**Domain Services** receive ports via constructor injection and contain all business logic.

### Architectural Violation (FIXED)

~~`adapters/hooks/price_alert_handler.py` instantiates `DatabaseDataPersistenceAdapter()` directly~~ — now constructor-injected via `DataPersistencePort`.

## Database

Default: SQLite at `sqlite:///./database/product_cache.db`. Configurable via environment variable `PHOVEU_BACKEND_DATABASE_URL`.

Read/write separation is supported. When `DB_USE_REPLICA_ENGINE=true`, a separate replica engine is used for read operations.

All SQLAlchemy models inherit from `database.core.base.Base`.

## Middleware Stack

Registered in `api_main.py` in this order:

1. **CORS** — default allows all origins (`*`), configurable via `CORS_ORIGINS` in `config.py`
2. **Security headers** — adds standard security HTTP headers
3. **Rate limiting** — in-memory, 20 requests per 60 seconds by default (`RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW`)
4. **Request logging** — logs all incoming requests

## Hook / Event System

`HookManager` fires named events. Hook handlers (`HookHandler` subclasses) subscribe to specific event names.

Active handlers:
- `PriceAlertHandler` — evaluates price alert triggers and records history
- `EmailHandler` — sends email notifications via SMTP
- `LogHandler` — logs events

Event names used in the system include: `PRICE_SAVED`, `PRICE_CHECKED`, `PRICE_NEW`, `PRICE_CHANGED`, `PRICE_UPDATED`, `PRICE_NOT_CHANGED`, `PRODUCT_AVAILABLE`, `PRODUCT_UNAVAILABLE`, `USER_PRICE_ALERT`, `USER_VERIFICATION_REQUESTED`, `USER_PASSWORD_RESET_REQUESTED`, `ADMIN_NOTIFICATION`, `TICKET_CREATED`, `TICKET_UPDATED`.

## Worker / Queue Protocol

External scraping workers communicate with the backend via two endpoints:

- `GET /queue` — workers poll for tasks; authenticated by `X-Queue-Key` header
- `POST /queue/submit` — workers submit scrape results; authenticated by `X-Queue-Key` header

See `docs/WORKER_PROTOCOL.md` for the full contract.

## Configuration

All configuration is centralized in `config.py` as a `CONFIG` dict. Environment variables override defaults. Critical values with insecure defaults:

| Key | Default | Notes |
|-----|---------|-------|
| `JWT_SECRET` | `"your-super-secret-jwt-key-here-change-this-in-production"` | MUST be changed |
| `QUEUE_KEY` | `"your-secret-queue-key"` | MUST be changed |
| `CAPTCHA_TYPE` | `"none"` | No CAPTCHA enforcement by default |
| `CORS_ORIGINS` | `["*"]` | Wildcard CORS |
| `UVI_PORT` | `9000` | Server listen port |
| `JWT_ALGORITHM` | `"HS256"` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRY` | `900` | 15 minutes |
| `JWT_REFRESH_TOKEN_EXPIRY` | `2592000` | 30 days |
| `RATE_LIMIT_REQUESTS` | `20` | Per window |
| `RATE_LIMIT_WINDOW` | `60` | Seconds |

## Public vs. Authenticated Routes

The `config.py` auth-required map marks `/queue`, `/products`, and `/products/*` as `False` (public/unauthenticated). All other routes require authentication unless overridden.

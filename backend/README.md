# Phoveus - Backend

A production-ready Python backend foundation built with **FastAPI** and **Hexagonal Architecture** (Ports and Adapters). Provides authentication, billing, RBAC, notifications, and more out of the box.

## Architecture

The backend follows **Hexagonal Architecture** principles with dependency injection and modular route organization.

```
backend/
├── adapters/           # Infrastructure implementations
│   ├── auth_persistence.py
│   ├── database_persistence.py
│   ├── http_engine.py
│   ├── stripe_payment.py
│   ├── paypal_payment.py
│   ├── rbac_adapter.py
│   ├── password_hasher.py
│   ├── google_token_verifier.py
│   ├── github_token_verifier.py
│   ├── facebook_token_verifier.py
│   ├── notification_delivery/
│   ├── notification_queue/
│   └── persistence/
├── domain/             # Business logic
│   ├── entities/       # Data models (auth, billing, RBAC, tickets, etc.)
│   ├── services/       # Domain services (Auth, Payment, Ticket, OAuth, etc.)
│   ├── api_models/     # Request/response schemas
│   └── exceptions.py
├── ports/              # Interface contracts
│   ├── auth.py
│   ├── billing_persistence.py
│   ├── data_persistence.py
│   ├── payment_gateway.py
│   ├── notification_delivery.py
│   ├── notification_queue.py
│   ├── oauth.py
│   ├── rbac.py
│   ├── ticket_persistence.py
│   ├── app_config.py
│   └── event_config.py
├── routes/             # API endpoints
│   ├── auth.py         # Login, register, password reset, 2FA
│   ├── billing.py      # Billing & subscriptions
│   ├── livechat.py     # Live chat support
│   ├── contact.py
│   ├── media.py
│   ├── webhooks.py
│   ├── general.py
│   ├── admin/          # Admin operations
│   └── user/           # User profile management
├── database/           # Schema definitions & migrations
├── utils/              # Shared utilities (logging, email, security, middleware)
├── tests/              # Test suite
├── cli/                # CLI tools
├── scripts/            # Utility scripts
├── templates/          # Email templates (Jinja2)
├── api_main.py         # Application entry point
├── config.py           # Configuration management
└── Makefile            # Development commands
```

### Database Read/Write Separation

The framework includes built-in query routing for read replicas:

- **RoutingSession** automatically routes queries based on decorators and operation type
- `@require_read_db` forces queries to the read replica
- `@require_write_db` forces queries to the write master
- INSERT/UPDATE/DELETE and transactions always go to the write master

## Tech Stack

| Category | Technology |
|----------|-----------|
| Framework | FastAPI 0.128.0 + Uvicorn 0.40.0 |
| ORM | SQLAlchemy 2.0 (PostgreSQL, MySQL, SQLite) |
| Validation | Pydantic 2.12 |
| Auth | JWT (PyJWT), OAuth (Google, GitHub, Facebook) |
| Payments | Stripe, PayPal |
| CAPTCHA | reCAPTCHA v3, Cloudflare Turnstile |
| Testing | Pytest + pytest-asyncio |
| Code Quality | Ruff (lint/format), MyPy (types) |
| Templates | Jinja2 (emails) |
| Cache | Redis (async) |

## Built-in Features

- **Authentication**: JWT, OAuth social login (Google, GitHub, Facebook), 2FA, password recovery
- **Authorization**: Role-Based Access Control (RBAC)
- **Billing**: Stripe and PayPal payment processing, subscriptions, credits
- **Notifications**: Delivery and queue system
- **Live Chat**: Real-time support system
- **Support Tickets**: Ticket management
- **Admin Panel**: User management, app config, event monitoring
- **Email**: Templated emails via Jinja2
- **Security**: Password hashing, CAPTCHA, rate limiting
- **Observability**: Structured JSON logging with context filtering

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL (recommended) or SQLite for development

### Installation

```bash
# Install all dependencies
make install

# Or production only
make install-prod
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your database, branding, and service credentials
```

Key environment variables:

| Variable | Description |
|----------|-------------|
| `PHOVEU_APP_NAME` | Application display name |
| `PHOVEU_APP_LEGAL_ENTITY` | Legal entity name |
| `PHOVEU_SUPPORT_EMAIL` | Support email address |
| `DOMAIN_UI` | Frontend domain (for email links) |
| `DOMAIN_UI_SCHEME` | Protocol scheme (`http` or `https`) |
| `PHOVEU_BACKEND_DATABASE_URL` | Database connection string |
| `PHOVEU_BACKEND_CAPTCHA_TYPE` | CAPTCHA provider (`none`, `recaptcha_v3`, `turnstile`) |

### Running

```bash
# Development
uvicorn api_main:app --reload --port 8000

# Or with Docker
make docker-build
make docker-run
```

## Development

### Code Quality

```bash
make check        # Run all checks (lint + format + types)
make fix          # Auto-fix all issues
make test         # Run test suite
make test-coverage # Tests with coverage report
make clean        # Clean cache files and build artifacts
```

### CI/CD

GitHub Actions workflow included at `.github/workflows/docker-build-push.yml`:

- Triggers on push to `main` or manual dispatch
- Builds multi-architecture Docker images (amd64, arm64)
- Pushes to Docker Hub

Required GitHub secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`

## License

[Add your license information here]

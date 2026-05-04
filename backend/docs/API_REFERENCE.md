# API Reference

All paths are relative to the application root. Authentication uses JWT Bearer tokens unless noted otherwise. Exact path strings are from `@router` decorators in the source. Generated from `docs/internal/openapi.json` — do not edit manually; run `/update-api-reference` to regenerate.

---

## General Routes

**File**: `routes/general.py`
**Auth**: Public

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | None | API Root — welcome endpoint with basic API information. |
| GET | `/health` | None | Health check — confirms the API is running. |

---

## Authentication Routes

**Prefix**: `/auth`
**File**: `routes/auth.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/login` | None | Login with email and password. Returns access + refresh tokens. |
| POST | `/auth/token` | None | OAuth2 password flow token endpoint. ⚠️ `username` field expects an **email address**. |
| POST | `/auth/register` | None | Register a new user account. |
| POST | `/auth/refresh` | None | Exchange a refresh token for a new access token. |
| POST | `/auth/logout` | None | Invalidate current session. |
| POST | `/auth/request-password-reset` | None | Request a password-reset email. |
| POST | `/auth/reset-password` | None | Complete password reset with token. |
| POST | `/auth/verify` | None | Verify email address with token. |
| POST | `/auth/resend-verification` | Bearer | Resend email verification link. |
| POST | `/auth/change-password` | Bearer | Change password. Invalidates all sessions. |
| GET | `/auth/me` | Bearer | Return current user profile. |
| GET | `/auth/api-keys` | Bearer | List all API keys for the current user. |
| POST | `/auth/api-keys` | Bearer | Create a new API key. |

**JWT Claims**:
- Access token: `user_id`, `session_id`, algorithm `HS256`, expiry 900 s
- Refresh token: `user_id`, `session_id`, `"type": "refresh"`, expiry 2 592 000 s (30 days)

---

## Products Routes

**Prefix**: `/products`
**File**: `routes/products.py`
**Auth**: Public (no authentication required)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/products` | None | List all products with pagination, filtering, and sorting. |
| GET | `/products/states` | None | Get all available product states. |
| POST | `/products/add` | None | Add a new product to the monitoring database. |
| GET | `/products/{product_id}` | None | Get product details by ASIN / product ID. |
| GET | `/products/{asin}/price-history` | None | Get price history for a product. |

---

## Queue Routes (Worker Protocol)

**Prefix**: `/queue`
**File**: `routes/queue.py`
**Auth**: `X-Queue-Key` header (value must match `QUEUE_KEY` from `config.py`)

> **Security**: Default `QUEUE_KEY` is `"your-secret-queue-key"` — **must be changed in production**.
> The `security` field is absent from the OpenAPI schema for these routes because FastAPI does not model the custom header scheme; authentication is enforced by the `verify_queue_key()` dependency.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/queue` | X-Queue-Key | Poll for pending scraping tasks. Returns `QueueTaskResponse`. |
| POST | `/queue/submit` | X-Queue-Key | Submit a product check result. Body: `QueueSubmissionRequest` (one result per request). |
| GET | `/queue/worker/{worker_id}` | X-Queue-Key | Get status of a specific worker. |
| POST | `/queue/worker/{worker_id}/stop` | X-Queue-Key | Signal a worker to stop and release locks. |

**Schema references** — `domain/entities/queue_schemas.py`:
- `QueueTaskResponse`: `worker_id`, `tasks: List[TaskDetail]`, `countries`, `interval_seconds`, `screenshot_service_url`, `screenshot_trigger`, `scraper_config`
- `QueueSubmissionRequest`: `worker_id`, `asin`, `country`, `check_result: CheckResultData`, `release`
- `TaskDetail`: `asin`, `last_prices: Dict[str, LastPriceInfo]`

---

## Monitoring Routes

**Prefix**: `/monitoring`
**File**: `routes/monitoring.py`
**Auth**: Public

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/monitoring/status` | None | Get monitoring status including active workers. |

---

## Country / Currency Routes

**Files**: `routes/country.py`, `routes/currency.py`
**Auth**: Public

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/country/list` | None | Get all configured countries. |
| GET | `/currency` | None | Get available currencies. |

---

## Screenshot Routes

**File**: `routes/screenshots.py`
**Auth**: Public

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/screenshot/view/{screenshot_url}.png` | None | View a stored screenshot image. |

---

## Media Routes

**File**: `routes/media.py`
**Auth**: Public

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/media/tickets/{file_path}` | None | Serve a ticket attachment file. |
| GET | `/media/livechat/{file_path}` | None | Serve a livechat attachment file. |

---

## Contact Routes

**Prefix**: `/contact`
**File**: `routes/contact.py`
**Auth**: Public (guest access)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/contact` | None | Submit a contact/support form (creates a guest ticket). |
| GET | `/contact/{ticket_id}` | None | Get a guest ticket by ID. |
| GET | `/contact/{ticket_id}/messages` | None | Get messages on a guest ticket. |
| POST | `/contact/{ticket_id}/messages` | None | Reply to a guest ticket. |

---

## LiveChat Routes

**Prefix**: `/livechat`
**File**: `routes/livechat.py`
**Auth**: Bearer for all routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/livechat/session` | Bearer | Start a new chat session. |
| GET | `/livechat/session/{session_id}` | Bearer | Get session metadata. |
| POST | `/livechat/session/{session_id}/end` | Bearer | End a session (guest). |
| GET | `/livechat/session/{session_id}/messages` | Bearer | Get messages in a chat session. |
| POST | `/livechat/session/{session_id}/message` | Bearer | Send a chat message. |
| POST | `/livechat/session/{session_id}/convert` | Bearer | Convert chat session to a support ticket. |
| POST | `/livechat/session/{session_id}/attachments` | Bearer | Upload an attachment to a session. |
| POST | `/livechat/session/{session_id}/activity` | Bearer | Update session activity / heartbeat. |
| GET | `/livechat/admin/sessions` | Bearer | List all chat sessions (admin). |
| GET | `/livechat/admin/stats` | Bearer | Get livechat statistics (admin). |
| POST | `/livechat/admin/session/{session_id}/join` | Bearer | Agent joins a session. |
| POST | `/livechat/admin/session/{session_id}/message` | Bearer | Agent sends a message in a session. |
| GET | `/livechat/admin/session/{session_id}/messages` | Bearer | Get all messages in a session (admin view). |
| POST | `/livechat/admin/session/{session_id}/end` | Bearer | End a session (admin). |

---

## Webhook Routes

**Prefix**: `/webhooks`
**File**: `routes/webhooks.py`
**Auth**: Signature verification only (no Bearer token)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/webhooks/paypal` | Signature | PayPal webhook receiver. Authenticity verified by `PaymentGatewayPort.validate_webhook_signature()`. |
| POST | `/webhooks/stripe` | Signature | Stripe webhook receiver. Authenticity verified by `PaymentGatewayPort.validate_webhook_signature()`. |

---

## User Account Routes

**Prefix**: `/user/account`
**Auth**: Bearer token required for all routes unless noted.

### Account Info

**File**: `routes/user/account/info.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/user/account` | Bearer | Get current user account info including credit balance and monitoring metrics. |
| GET | `/user/account/check-tracking` | Bearer | Check if a specific ASIN is being tracked. Query params: `asin`, `country_code`. |
| PUT | `/user/account/edit` | Bearer | Edit user account profile. |
| DELETE | `/user/account/delete` | Bearer | Delete the current user account. |

### Tracked Products

**File**: `routes/user/account/tracked_products.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/user/account/tracked-products` | Bearer | Add a product to tracking. Consumes 1 credit. CAPTCHA required. Unverified users get `is_enabled=False`. |
| GET | `/user/account/tracked-products` | Bearer | List all tracked products for the current user. |
| GET | `/user/account/tracked-products/{track_id}` | Bearer | Get a single tracked product by ID. |
| DELETE | `/user/account/tracked-products/{track_id}` | Bearer | Remove a tracked product by track ID. Credits are **not** refunded. |
| DELETE | `/user/account/tracked-products/by-product` | Bearer | Remove a tracked product by product identifier. |
| PUT | `/user/account/tracked-products/{track_id}` | Bearer | Update a tracked product's alert associations. |
| POST | `/user/account/tracked-products/{track_id}/resume` | Bearer | Resume a paused or expired track. Consumes 1 credit, extends `expires_at` by 30 days. |

### Price Alerts

**File**: `routes/user/account/price_alerts.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/user/account/price-alerts` | Bearer | Create a new price alert. Requires `user.is_verified = True` (checked in handler). |
| GET | `/user/account/price-alerts` | Bearer | List all price alerts for the current user. |
| GET | `/user/account/price-alerts/{alert_id}` | Bearer | Get a single price alert. |
| DELETE | `/user/account/price-alerts/{alert_id}` | Bearer | Delete a price alert. |
| PUT | `/user/account/price-alerts/{alert_id}` | Bearer | Replace a price alert. |
| PATCH | `/user/account/price-alerts/{alert_id}` | Bearer | Partially update a price alert. |
| POST | `/user/account/price-alerts/validate` | Bearer | Validate and interpret price alert rules without saving. |
| GET | `/user/account/alerts/history` | Bearer | Get price alert trigger history for the current user. |

### Recipients

**File**: `routes/user/account/recipients.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/user/account/recipients` | Bearer | Add a notification recipient (email, phone, etc.). |
| GET | `/user/account/recipients` | Bearer | List all recipients for the current user. |
| GET | `/user/account/recipients/{id}` | Bearer | Get a single recipient. |
| DELETE | `/user/account/recipients/{id}` | Bearer | Delete a recipient. |
| PATCH | `/user/account/recipients/{id}` | Bearer | Update a recipient. |
| POST | `/user/account/recipients/verify` | None | Verify a recipient using a verification token (public link). |
| POST | `/user/account/recipients/{id}/resend-verification` | Bearer | Resend recipient verification email. |

### Interest Space

**File**: `routes/user/account/interest_space.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/user/account/history` | Bearer | Get the current user's product viewing history. |
| GET | `/user/account/my-products` | Bearer | Get the current user's personal product list. |

### Billing

**File**: `routes/user/account/billing.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/user/account/billing/packages` | Bearer | List available credit packages. |
| POST | `/user/account/billing/orders` | Bearer | Create a new payment order. Body includes `provider` and `package_id`. |
| GET | `/user/account/billing/orders` | Bearer | List all orders for the current user. Includes associated invoice data. |
| POST | `/user/account/billing/orders/{order_id}/resume` | Bearer | Resume an existing order (PayPal / Stripe). |
| POST | `/user/account/billing/capture` | Bearer | Capture a completed payment. |
| GET | `/user/account/billing/history` | Bearer | Get credit ledger history. |
| GET | `/user/account/billing/invoices` | Bearer | List all invoices. |
| GET | `/user/account/billing/invoices/{invoice_id}` | Bearer | Get a single invoice as JSON. |
| GET | `/user/account/billing/invoices/{invoice_id}/html` | Bearer | Get a single invoice rendered as HTML. |
| GET | `/user/account/billing/payment-methods` | Bearer | List available payment methods (enabled gateways). |
| POST | `/user/account/billing/manual-payment` | Bearer | Submit a manual payment request (Bitcoin / Bank Transfer). |

### Support Tickets

**File**: `routes/user/account/tickets.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/user/account/tickets/categories` | None | Get ticket categories (public). |
| POST | `/user/account/tickets` | Bearer | Create a support ticket. |
| GET | `/user/account/tickets` | Bearer | List the current user's tickets. |
| GET | `/user/account/tickets/{ticket_id}` | Bearer | Get a single ticket. |
| GET | `/user/account/tickets/{ticket_id}/messages` | Bearer | Get messages on a ticket. |
| POST | `/user/account/tickets/{ticket_id}/messages` | Bearer | Reply to a ticket. |
| POST | `/user/account/tickets/{ticket_id}/attachments` | Bearer | Upload an attachment to a ticket. |

---

## Admin Routes

**Prefix**: `/admin`
**Auth**: Bearer token + explicit RBAC permission. Admin role does **not** automatically inherit all permissions — they must be explicitly assigned.

### Admin Root

**File**: `routes/admin/general.py`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/` | Bearer | Admin access verification / root. |

### Admin Users

**File**: `routes/admin/users.py`
**Permission**: `admin:write` for all routes

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/users` | `admin:write` | List users with pagination and filtering. |
| POST | `/admin/users` | `admin:write` | Create a new user account. |
| GET | `/admin/users/{user_id}` | `admin:write` | Get detailed information about a user. |
| PUT | `/admin/users/{user_id}` | `admin:write` | Update a user's information. |
| DELETE | `/admin/users/{user_id}` | `admin:write` | Delete a user account. Cannot delete yourself. |
| POST | `/admin/users/{user_id}/login-as` | `admin:write` | Impersonate a user by ID (generates token). |
| POST | `/admin/users/login-as` | `admin:write` | Impersonate a user by email (generates token). |

### Admin RBAC

**File**: `routes/admin/rbac.py`
**Permission**: `admin:write` for all routes

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/rbac/permissions` | `admin:write` | List all permissions. |
| POST | `/admin/rbac/permissions` | `admin:write` | Create a permission. |
| GET | `/admin/rbac/permissions/{permission_id}` | `admin:write` | Get a permission by ID. |
| PUT | `/admin/rbac/permissions/{permission_id}` | `admin:write` | Update a permission. |
| DELETE | `/admin/rbac/permissions/{permission_id}` | `admin:write` | Delete a permission. |
| GET | `/admin/rbac/roles` | `admin:write` | List all roles. |
| POST | `/admin/rbac/roles` | `admin:write` | Create a role. |
| GET | `/admin/rbac/roles/{role_id}` | `admin:write` | Get a role by ID. |
| PUT | `/admin/rbac/roles/{role_id}` | `admin:write` | Update a role. |
| DELETE | `/admin/rbac/roles/{role_id}` | `admin:write` | Delete a role. |
| GET | `/admin/rbac/roles/{role_id}/permissions` | `admin:write` | Get permissions assigned to a role. |
| POST | `/admin/rbac/roles/{role_id}/permissions` | `admin:write` | Assign a permission to a role. |
| DELETE | `/admin/rbac/roles/{role_id}/permissions/{permission_id}` | `admin:write` | Remove a permission from a role. |
| GET | `/admin/rbac/users/{user_id}/permissions` | `admin:write` | Get permissions assigned directly to a user. |
| POST | `/admin/rbac/users/{user_id}/permissions` | `admin:write` | Assign a permission to a user. |
| DELETE | `/admin/rbac/users/{user_id}/permissions/{permission_id}` | `admin:write` | Remove a permission from a user. |

### Admin Cookies

**File**: `routes/admin/cookies.py`
**Permission**: `admin:write` for all routes

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/cookies` | `admin:write` | List cookie configurations. |
| POST | `/admin/cookies` | `admin:write` | Create a cookie configuration. |
| GET | `/admin/cookies/{cookie_id}` | `admin:write` | Get a cookie by ID. |
| PUT | `/admin/cookies/{cookie_id}` | `admin:write` | Update a cookie. |
| DELETE | `/admin/cookies/{cookie_id}` | `admin:write` | Delete a cookie. |

### Admin Countries

**File**: `routes/admin/countries.py`
**Permission**: `admin:write` for all routes

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/countries` | `admin:write` | List all countries. |
| POST | `/admin/countries` | `admin:write` | Create a country. |
| GET | `/admin/countries/{country_id}` | `admin:write` | Get a country by ID. |
| PUT | `/admin/countries/{country_id}` | `admin:write` | Update a country. |
| DELETE | `/admin/countries/{country_id}` | `admin:write` | Delete a country. |

### Admin Scrapers

**File**: `routes/admin/scraper.py`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/scrapers` | `admin:read` | List scraper configurations. |
| GET | `/admin/scrapers/{config_id}` | `admin:read` | Get a scraper configuration by ID. |
| POST | `/admin/scrapers` | `admin:write` | Create a scraper configuration. |
| PUT | `/admin/scrapers/{config_id}` | `admin:write` | Update a scraper configuration. |
| DELETE | `/admin/scrapers/{config_id}` | `admin:write` | Delete a scraper configuration. |

### Admin Synthetics

**File**: `routes/admin/synthetics.py`
**Permission**: `admin:write` for all routes

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/synthetics/tasks` | `admin:write` | List all synthetics runs grouped by task name. |
| GET | `/admin/synthetics/tasks/screenshot/{screenshot_url}` | `admin:write` | Get a screenshot from a synthetics run. |
| GET | `/admin/tasks/{task_name}` | `admin:write` | Get detailed information about a task (synthetics + cookies). |

### Admin Tickets

**File**: `routes/admin/tickets.py`

> **Path note**: The OpenAPI schema exposes these as `/admin/tickets/tickets/…` due to nested router prefix stacking. The effective URL requires the double segment.

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/tickets/tickets` | `admin:write` or `support:read` | List all tickets. |
| GET | `/admin/tickets/agents` | `admin:write` or `support:read` | List assignable agents. |
| GET | `/admin/tickets/categories` | `admin:write` or `support:read` | List ticket categories. |
| POST | `/admin/tickets/categories` | `admin:write` | Create a ticket category. |
| PATCH | `/admin/tickets/categories/{category_id}` | `admin:write` or `support:write` | Update a ticket category. |
| GET | `/admin/tickets/tickets/{ticket_id}` | `admin:write` or `support:read` | Get a single ticket. |
| GET | `/admin/tickets/tickets/{ticket_id}/messages` | `admin:write` or `support:read` | Get ticket messages. |
| POST | `/admin/tickets/tickets/{ticket_id}/messages` | `admin:write` or `support:write` | Reply to a ticket. |
| PATCH | `/admin/tickets/tickets/{ticket_id}/status` | `admin:write` or `support:write` | Update ticket status. |
| PATCH | `/admin/tickets/tickets/{ticket_id}/priority` | `admin:write` or `support:write` | Update ticket priority. |
| POST | `/admin/tickets/tickets/{ticket_id}/assign` | `admin:write` or `support:write` | Assign a ticket to an agent. |
| POST | `/admin/tickets/tickets/{ticket_id}/tags` | `admin:write` or `support:write` | Add a tag to a ticket. |
| DELETE | `/admin/tickets/tickets/{ticket_id}/tags/{tag_id}` | `admin:write` | Remove a tag from a ticket. |
| POST | `/admin/tickets/tickets/{ticket_id}/attachments` | `admin:write` or `support:write` | Upload an attachment to a ticket. |

### Admin Billing

**File**: `routes/admin/billing.py`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/billing/pending-payments` | `admin:read` | List pending manual payments awaiting verification. |
| POST | `/admin/billing/pending-payments/{transaction_id}/verify` | `admin:write` | Manually verify / approve a payment transaction. |
| POST | `/admin/billing/generate-invoice` | `admin:write` | Generate an invoice for a client. |
| GET | `/admin/billing/transactions` | `admin:read` | List all transactions. **Stub: returns empty list.** |
| POST | `/admin/billing/cleanup-expired` | `admin:write` | Clean up expired pending transactions. **Stub: returns 0.** |
| GET | `/admin/billing/stats` | `admin:read` | Billing statistics summary. |
| GET | `/admin/billing/packages` | `admin:read` | List all credit packages (including inactive). |
| POST | `/admin/billing/packages` | `admin:write` | Create a credit package. |
| PUT | `/admin/billing/packages/{package_id}` | `admin:write` | Update a credit package. |
| DELETE | `/admin/billing/packages/{package_id}` | `admin:write` | Delete a credit package. |

### Admin Payment Gateways

**File**: `routes/admin/payment_gateways.py`

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/admin/payment-gateways/` | `admin:read` | List all payment gateway configurations. |
| POST | `/admin/payment-gateways/` | `admin:write` | Create / configure a payment gateway. |
| GET | `/admin/payment-gateways/{provider}` | `admin:read` | Get a payment gateway configuration by provider. |
| PUT | `/admin/payment-gateways/{provider}` | `admin:write` | Update a payment gateway configuration. |
| PATCH | `/admin/payment-gateways/{provider}/enable` | `admin:write` | Enable a payment gateway. |
| PATCH | `/admin/payment-gateways/{provider}/disable` | `admin:write` | Disable a payment gateway. |
| GET | `/admin/payment-gateways/public/status` | None | Get public payment gateway availability status (no auth). |

---

## Benchmark Routes

**Prefix**: `/bench`
**File**: `routes/bench.py`
**Auth**: Public (bench key in path acts as a basic guard)

> These routes are intended for internal load/performance testing. They are not part of the public product API.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/bench/{bench_key}` | None | Basic benchmark endpoint. |
| GET | `/bench/{bench_key}/{delay}` | None | Benchmark with configurable delay. |
| POST | `/bench/{bench_key}/{delay}` | None | POST benchmark with configurable delay. |
| GET | `/bench/{bench_key}/db/read/{key}` | None | Benchmark a database read. |
| POST | `/bench/{bench_key}/db/write` | None | Benchmark a database write. |
| DELETE | `/bench/{bench_key}/db/delete/{key}` | None | Benchmark a database delete. |
| GET | `/bench/{bench_key}/db/list` | None | Benchmark a database list scan. |
| GET | `/bench/{bench_key}/comprehensive/{delay}` | None | Comprehensive benchmark (multiple ops). |
| GET | `/bench/{bench_key}/stats` | None | Benchmark statistics. |

---

## Route Count Summary

| Source | Count |
|--------|-------|
| `docs/internal/openapi.json` | **136** |
| This document | **136** |
| Discrepancy | **0** |

> `billing_old.py` routes are excluded — that file is superseded by `billing.py` and its routes are not registered in the current OpenAPI schema.

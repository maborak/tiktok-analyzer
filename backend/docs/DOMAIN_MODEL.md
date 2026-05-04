# Domain Model

All domain entities are Python dataclasses defined in `domain/entities/`. SQLAlchemy ORM models are in `database/` and are separate from domain entities. This document covers the domain layer only.

---

## Core Product Entities

**File**: `domain/entities/models.py`

### Currency
Fields: standard currency representation (code, symbol, name).

### ProductState
Enum values representing the availability state of a product.

### Product
Core product domain entity. Fields include product identifier, ASIN or equivalent, title, price breakdown (base price, shipping fee, import fees, total price), availability state, country code, currency, and timestamps.

### ShippingInfo
Shipping-specific fields associated with a product.

### ProductCheckResult
Result of a single price check operation. Contains the product snapshot plus metadata about what changed.

### MonitoringConfig
Configuration for how often a product should be checked. Used by the worker queue system.

---

## Authentication Entities

**File**: `domain/entities/auth_models.py`

### UserRole
```
USER
MODERATOR
ADMIN
```

### AuthStatus
```
SUCCESS
FAILED
LOCKED
EXPIRED
INVALID
```

### User
Fields: `id`, `email`, `username`, `password_hash`, `salt`, `role` (UserRole), `is_active`, `is_verified`, `created_at`, `updated_at`, `credits` (legacy — do not use for balance; see CreditLedgerEntry).

### UserSession
Fields: `id`, `user_id`, `session_id`, `token`, `refresh_token`, `created_at`, `expires_at`, `is_active`.

### ApiKey
Fields: `id`, `user_id`, `key_hash`, `name`, `created_at`, `last_used_at`, `is_active`.

### UserProduct (legacy)
The legacy product tracking entity. **Superseded by `ProductTrack`**. Still exists in `database/user_products/models.py` (`user_products` table) but should not be used for new features.

### AuthContext
Computed from a validated JWT. Fields include `user_id`, `user`, `session_id`, `permissions`. Method `can_access_product` always returns `True` for users with the `products:read` permission — this is an incomplete IDOR check that does not verify product ownership.

### Account Lockout
After 5 consecutive failed login attempts, the account is locked for 30 minutes.

### Request / Response Models
`LoginRequest`, `LoginResponse`, `RegisterRequest`, `RegisterResponse`, `ChangePasswordRequest`, `ChangePasswordResponse`, `PasswordResetRequest`, `PasswordResetResponse`, `CreateApiKeyRequest`, `CreateApiKeyResponse`, `JWTToken`, `TokenPayload`.

---

## Billing Entities

**File**: `domain/entities/billing_models.py`

### PaymentProvider
```
STRIPE
PAYPAL
OTHER
BITCOIN
BANK_TRANSFER
```
`STRIPE` and `PAYPAL` are automated (webhook-driven). `BITCOIN` and `BANK_TRANSFER` are manual (require admin verification).

### PaymentStatus
```
AWAITING_PAYMENT
PENDING
COMPLETED
FAILED
REFUNDED
```

### LedgerSource
```
registration
purchase
admin_grant
track_product
```

### CreditPackage
Fields: `id`, `name`, `credits`, `price`, `currency`, `is_active`, `description`.

### PaymentTransaction
Fields: `id`, `user_id`, `provider` (PaymentProvider), `provider_transaction_id`, `amount`, `currency`, `status` (PaymentStatus), `package_id`, `created_at`, `updated_at`.

### Invoice
Fields: `id`, `user_id`, `transaction_id`, `invoice_number`, `amount`, `currency`, `tax_rate` (always `0.0` from `_create_enterprise_invoice`), `items`, `created_at`.

### CreditLedgerEntry
Fields: `id`, `user_id`, `amount` (positive for grants, negative for consumption), `source` (LedgerSource), `transaction_id`, `expires_at`.

**Balance formula**: `SUM(amount) FROM credit_ledgers WHERE user_id = ? AND expires_at > NOW()`

Positive entries come from `registration`, `purchase`, `admin_grant`. Negative entries come from `track_product` (value `-1` each) with a 10-year expiry.

### PaymentGatewayConfig
Fields: `id`, `provider` (PaymentProvider), `is_enabled`, `config_json` (provider-specific keys stored as JSON).

---

## Price Alert Entities

**File**: `domain/entities/price_alert_models.py`

### TriggerType
```
value_up
value_down
percent_up
percent_down
time_interval
becomes_available
becomes_unavailable
price_saved
price_checked
```
Note: Both the domain entity and database model now include `price_checked` — enum parity is maintained.

### TriggerTarget
```
total_price
base_price
shipping_fee
import_fees
product
```

### LogicOperator
```
and
or
```

### PriceAlertTrigger
Fields: `id`, `price_alert_id`, `trigger_type` (TriggerType), `trigger_value` (optional float), `target_field` (TriggerTarget).

### RecipientInfo
Lightweight recipient snapshot embedded in `PriceAlert`. Fields: `id`, `type`, `value`, `name` (optional), `is_verified`, `is_enabled`.

### PriceAlert
Fields: `id`, `user_id`, `name`, `recipient_ids` (List[int]), `logic_operator` (LogicOperator, default `or`), `is_active`, `cooldown_minutes` (default `60`), `triggers` (list of PriceAlertTrigger), `recipients` (List[RecipientInfo]).

Backward-compatibility properties (return first item or None): `recipient_id` (`@property`), `recipient` (`@property`).

**Database relationship**: Many-to-many with `Recipient` via the `price_alert_recipients` junction table. The legacy `recipient_id` FK column on `price_alerts` is nullable and retained for backward compatibility.

**Junction table**: `price_alert_recipients` — columns: `price_alert_id` (FK to `price_alerts.id`, ON DELETE CASCADE), `recipient_id` (FK to `recipients.id`, ON DELETE CASCADE). Composite primary key on both columns.

**Limit**: `LIMIT_MAX_RECIPIENTS_PER_ALERT` (default `3`) in `config.py`.

### ProductTrack
The **authoritative** product tracking entity. Supersedes `UserProduct`.

Fields: `id`, `user_id`, `product_id`, `country_code`, `price_alert_id` (optional, links to PriceAlert), `is_enabled`, `last_notified_at`, `expires_at`, `status` (string: `"active"` or `"paused"`), `created_at`.

Database unique constraint: `(user_id, product_id, country_code, price_alert_id)` — table `product_tracks`, constraint name `uix_user_product_country_alert`.

### PriceAlertHistory
Fields: `id`, `user_id`, `price_alert_id`, `product_id`, `country_code`, `recipient_id`, `trigger_type` (TriggerType), `trigger_value` (optional float), `target_field` (TriggerTarget), `old_value` (string, optional), `new_value` (string, optional), `created_at`.

---

## Queue / Worker Entities

**File**: `domain/entities/queue_schemas.py`

### LastPriceInfo
Carries the last known price snapshot for a product. Passed to workers so they can compute diffs.

### TaskDetail
Fields: product identifier, country code, monitoring config, last price info.

### QueueTaskResponse
The response body returned by `GET /queue`. Contains a list of `TaskDetail` items.

### CheckResultData
The result payload within a queue submission. Contains the new product data snapshot plus `price_extraction_status` (one of: `"ok"`, `"captcha_blocked"`, `"price_hidden"`, `"no_price_extracted"`, `"unavailable_in_region"`).

### QueueSubmissionRequest
The request body for `POST /queue/submit`. Contains `worker_id`, `asin`, `country`, `check_result` (CheckResultData), and `release` (bool).

---

## Product Detail API Models

**File**: `domain/api_models/product_models.py`

### CountryStats
Per-country aggregated statistics returned in the product detail response (`GET /products/{asin}?country=ALL`).
Fields: `price_min`, `price_max`, `price_avg`, `lowest_price_at`, `highest_price_at`, `total_checks`, `days_tracked`, `availability_rate`, `watchers_count`, `price_trend` (`"up"` | `"down"` | `"stable"`), `trend_percent`.

Computed by 3 batch queries in `ProductService.get_product_data_by_countries()`:
1. Stats + extremes — single aggregation on `price_history` with conditional MIN/MAX/AVG
2. Trends — reads from `product_country_states` materialized view
3. Watchers — counts active `product_tracks` per country

### CountryData
Contains `prices: List[dict]` (price history entries) and optional `stats: CountryStats`.

---

## RBAC Entities

**File**: `domain/entities/rbac_models.py`

### Permission
Fields: `id`, `name` (string, e.g. `"admin:read"`, `"admin:write"`, `"products:read"`).

### RolePermission
Maps a `UserRole` to a `Permission`.

### UserPermission
Maps a `user_id` to a `Permission` (direct user-level permission assignment).

Permission strings follow the pattern `<resource>:<action>`. Known permission strings include `admin:read`, `admin:write`, `products:read`.

Admin role does **not** automatically inherit all permissions — permissions must be explicitly assigned via `RolePermission` or `UserPermission`.

---

## Recipient Entities

**File**: `domain/entities/recipient_models.py`

### RecipientType
```
email
slack
webhook
```

### Recipient
Fields: `id`, `user_id`, `type` (RecipientType), `value`, `is_verified`, `is_enabled`, `subject_tag`, `name`, `created_at`.

---

## Ticket / Support Entities

**File**: `domain/entities/ticket_models.py`

### TicketStatus
```
OPEN
PENDING_CUSTOMER
IN_PROGRESS
RESOLVED
CLOSED
```

### TicketPriority
```
LOW
NORMAL
HIGH
URGENT
```

### TicketOrigin
```
WEB
EMAIL
API
LIVECHAT
CONTACT_FORM
```

### LiveChatStatus
```
WAITING
ACTIVE
ENDED
```

### LiveChatSenderType
```
USER
AGENT
SYSTEM
```

### Key Dataclasses
`TicketCategoryDef`, `TicketTag`, `Ticket`, `TicketAttachment`, `TicketMessage`, `TicketInboundConfig`, `LiveChatAttachment`, `LiveChatSession`, `LiveChatMessage`, `LiveChatMacro`.

---

## Entity Relationships

```
User (1) ──────────────── (N) ProductTrack
User (1) ──────────────── (N) PriceAlert
User (1) ──────────────── (N) Recipient
User (1) ──────────────── (N) PaymentTransaction
User (1) ──────────────── (N) CreditLedgerEntry
User (1) ──────────────── (N) Ticket
User (1) ──────────────── (N) PriceAlertHistory
User (1) ──────────────── (N) UserSession
User (1) ──────────────── (N) ApiKey

PriceAlert (1) ─────────── (N) PriceAlertTrigger
PriceAlert (1) ─────────── (N) ProductTrack (optional link)
PriceAlert (N) ─────────── (M) Recipient    [via price_alert_recipients junction table]

ProductTrack (N) ───────── (1) PriceAlert (optional)

PaymentTransaction (1) ─── (1) Invoice
PaymentTransaction (1) ─── (N) CreditLedgerEntry

UserProduct [LEGACY] — superseded by ProductTrack
User.credits [LEGACY] — superseded by CreditLedgerEntry balance formula
```

---

## Domain Service Summary

| Service | File | Responsibility |
|---------|------|----------------|
| `AuthService` | `domain/services/auth_service.py` | Login, register, JWT, sessions, impersonation (`login_as_user`, `login_as_user_by_email`) |
| `CreditService` | `domain/services/credit_service.py` | Credit balance calculation, consume, renew_track |
| `PaymentService` | `domain/services/payment_service.py` | Payment initialization, capture, webhook processing, invoice creation |
| `PriceAlertManager` | `domain/services/price_alert_manager.py` | Trigger evaluation with AND/OR logic, cooldown enforcement |
| `ProductService` | `domain/services/product_service.py` | Product addition, track management, batch data fetch |
| `TicketService` | `domain/services/ticket_service.py` | Support ticket and live chat management |
| `MonitoringService` | `domain/services/monitoring_service.py` | Monitoring job management |
| `EventConfigService` | `domain/services/event_config_service.py` | Hook event config management: per-event-type handler enable/disable, in-memory cache with DB sync |
| `MonitorSystem` | `domain/services/monitor_system.py` | Top-level monitoring: CAPTCHA rate, failure rate, worker liveness, zero-price rate health checks |

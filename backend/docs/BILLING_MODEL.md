# Billing Model

---

## Overview

The billing system is credit-based. Users purchase credit packages; each credit allows tracking one product for one 30-day period. Credits are tracked in a ledger table (`credit_ledgers`) using double-entry accounting principles: positive entries represent grants, negative entries represent consumption.

---

## Credit Ledger

### Table

`credit_ledgers` — SQLAlchemy model: `CreditLedgerModel` in `database/billing/models.py`.

### Balance Formula

```
balance = SUM(amount) FROM credit_ledgers
          WHERE user_id = <user_id>
          AND expires_at > NOW()
```

Implemented in `CreditService.get_credit_balance()` in `domain/services/credit_service.py`.

### Entry Types

| LedgerSource | amount | Description |
|-------------|--------|-------------|
| `registration` | positive | Credits granted on account creation |
| `purchase` | positive | Credits from a completed payment |
| `admin_grant` | positive | Credits manually granted by admin |
| `track_product` | `-1` | Credit consumed when a product is tracked |

Deduction entries (`track_product`) are written with an `expires_at` of `NOW() + 10 years`. This effectively means deductions never expire and always count against the balance as long as the corresponding grant entries are also valid.

### Legacy Field

The `users` table has a `credits` integer column (default `10`). This column is **stale/legacy** and must not be used to determine a user's balance. Always use `CreditService.get_credit_balance()`.

---

## Credit Packages

### Table

`credit_packages` — SQLAlchemy model: `CreditPackageModel` in `database/billing/models.py`.

### Fields

`id`, `name`, `credits` (integer count), `price` (decimal), `currency`, `is_active`, `description`.

### Management

- Users list active packages via `GET /user/account/billing/packages`.
- Admins can create, update, and delete packages via `/admin/billing/packages` (requires `admin:write`).

---

## Payment Providers

### PaymentProvider Enum

```
STRIPE       — automated, webhook-driven
PAYPAL       — automated, webhook-driven
OTHER        — generic
BITCOIN      — manual, requires admin verification
BANK_TRANSFER — manual, requires admin verification
```

### Automated Providers (Stripe, PayPal)

Flow:
1. `POST /user/account/billing/orders` — `PaymentService.initialize_payment()` creates a `PaymentTransaction` with status `AWAITING_PAYMENT` and calls the provider adapter to create the order.
2. User completes payment on provider's UI.
3. Provider sends a webhook to `/webhooks/stripe` or `/webhooks/paypal`.
4. `PaymentService.process_webhook()` validates signature, checks idempotency, and if payment is successful: sets transaction status to `COMPLETED`, adds a positive `CreditLedgerEntry` with `LedgerSource.purchase`, and creates an `Invoice`.
5. Alternatively, `POST /user/account/billing/capture` — `PaymentService.capture_payment()` performs synchronous capture (used for some PayPal flows).
6. `POST /user/account/billing/orders/{order_id}/resume` — resumes an existing order for both PayPal and Stripe.

### Manual Providers (Bitcoin, BankTransfer)

Flow:
1. `POST /user/account/billing/manual-payment` — user submits payment claim.
2. Creates a `PaymentTransaction` with status `AWAITING_PAYMENT`.
3. Admin reviews via `GET /admin/billing/pending-payments`.
4. Admin manually verifies via `POST /admin/billing/verify-payment/{transaction_id}` (requires `admin:write`).
5. On verification: transaction status set to `COMPLETED`, credits provisioned via ledger entry, invoice created.

---

## Payment Transaction

### Table

`payment_transactions` — SQLAlchemy model: `PaymentTransactionModel` in `database/billing/models.py`.

### Fields

`id`, `user_id`, `provider` (PaymentProvider), `provider_transaction_id`, `amount`, `currency`, `status` (PaymentStatus), `package_id`, `created_at`, `updated_at`.

### PaymentStatus Enum

```
AWAITING_PAYMENT — order created, payment not yet received
PENDING          — payment submitted, awaiting confirmation
COMPLETED        — payment confirmed, credits provisioned
FAILED           — payment failed
REFUNDED         — payment refunded
```

### Order List Payload

`GET /user/account/billing/orders` returns transactions with associated invoice data included (not just transaction fields).
`GET /user/account/billing/orders` and `GET /user/account/billing/orders/{order_id}/resume` include original order quantity and currency.

### Idempotency

`PaymentService.process_webhook()` is designed to be idempotent: it checks whether a transaction has already been processed before provisioning credits. Duplicate webhook calls for the same transaction will not double-provision.

---

## Invoices

### Table

`invoices` — SQLAlchemy model: `InvoiceModel` in `database/billing/models.py`.

### Fields

`id`, `user_id`, `transaction_id`, `invoice_number`, `amount`, `currency`, `tax_rate`, `items`, `created_at`.

### Tax

`_create_enterprise_invoice()` in `PaymentService` always sets `tax_rate = 0.0`. Tax calculation is not currently implemented.

### Admin Invoice Generation

Admins can generate invoices manually via `POST /admin/billing/generate-invoice` (requires `admin:write`). `PaymentService.create_pending_invoice()` is used for admin-generated invoices.

### Invoice Access

- User: `GET /user/account/billing/invoices`, `GET /user/account/billing/invoices/{invoice_id}` (JSON), `GET /user/account/billing/invoices/{invoice_id}/html` (HTML render).

---

## Payment Gateway Configuration

### Table

`payment_gateway_configs` — SQLAlchemy model: `PaymentGatewayConfigModel` in `database/billing/models.py`.

### Fields

`id`, `provider` (PaymentProvider), `is_enabled`, `config_json` (provider-specific credentials and settings stored as JSON).

### Management

Admins manage gateway configurations via `/admin/payment-gateways` (full CRUD). The `config_json` field contains provider credentials (API keys, webhook secrets, etc.) and must be handled carefully.

---

## Credit Consumption

Credit consumption is implemented in `CreditService`:

- **Track product**: `CreditService.consume_credit()` writes a `CreditLedgerEntry` with `amount=-1`, `source=LedgerSource.TRACK_PRODUCT`, `expires_at=NOW()+10years`. Called when:
  - `POST /user/account/tracked-products` (add a product to tracking)
  - `POST /user/account/tracked-products/{track_id}/resume` (resume a track via `ProductService.resume_track`)

- **Renew track**: `CreditService.renew_track(user_id, track_id)` consumes 1 credit and extends the track's `expires_at` by 30 days. If the track is already expired, renewal starts from `NOW()`. If not expired, it extends from the current expiry.

- **Insufficient credits**: `consume_credit()` raises `ValueError("Insufficient credits to track product.")` if balance is 0 or negative.

---

## Monitoring Metrics

`CreditService.get_monitoring_metrics(user_id)` returns:

```json
{
  "credits": <integer balance>,
  "active_tracks": <count>,
  "paused_tracks": <count>,
  "total_tracks": <active + paused>,
  "recipients": <count>,
  "alerts": <count>,
  "monthly_consumption": <active_tracks>,
  "estimated_duration": "<string>"
}
```

`estimated_duration` is a human-readable string: `"No active monitoring"`, `"About N days"`, or `"About N months"`.

---

## Known Issues

1. `list_all_transactions` in `routes/admin/billing.py` is a stub that returns an empty list. Admins cannot currently browse all transactions via the admin UI.
2. `cleanup_expired_pending_transactions` in `routes/admin/billing.py` is a stub that returns 0 cleaned. Expired pending transactions accumulate indefinitely.
3. `tax_rate` is hardcoded to `0.0` — no tax calculation is implemented.

# API Changelog

## 2026-03-03
### Changes
- **Resources Added**:
  - `Billing` Endpoints (Admin & User) for handling credit packages, orders, invoices, payment method fetching, and capturing payments (Stripe, PayPal, etc.).
  - `Tickets` Endpoints (Admin & User & Public) for managing support categories, creating/viewing/replying to tickets, and handling attachments.
  - `Live Chat Session` Endpoints (Admin, User & Guest) for initializing sessions, polling status, and sending messages.
  - `Contact/Guest` Endpoints for submitting public contact forms and retrieving ticket metadata without full authentication.
- **Schemas**: New TypeScript interfaces for `SessionMetadataResponse`, `AdminTicketMessageResponse`, `CreditPackage`, `OrderResponse`, `CapturePaymentResponse`, `InvoiceDetail`, `PaymentMethod`, etc. reflect the expanded `openapi.json`.

### Impact on UI
- UI flows for purchasing credits, tracking order success, viewing invoices, and contacting support have been fully enabled by these new endpoints.
- Authentication modals can now intelligently prompt session initialization via the new robust session lifecycle endpoints.

## 2026-02-01
### Changes
- **Resources Added**:
  - `Recipients` (`/user/account/recipients`): Manage notification channels (Email, Slack, Webhook).
  - `Price Alerts` (`/user/account/price-alerts`): manage reusable alert logic (triggers, cooldowns).
  - `Tracked Products` (`/user/account/tracked-products`): Manage monitored items (replaces Favorites).
- **Resources Removed**:
  - `/user/account/favorites` (Replaced by `tracked-products`).
  - `/user/account/notifications` (Replaced by `price-alerts`).
- **Pagination**: Standardized response format (`pagination` object with `total`, `page`, `page_size`, etc.) across all new lists.

### Impact on UI
- **Favorites**: Feature removed. UI must now use "Track" button and `TrackedProducts` list.
- **Notifications**: "Rules" are now "Price Alerts". UI must allow creating alerts and *then* linking them to tracked products.
- **Recipients**: New UI section required to manage where alerts are sent.

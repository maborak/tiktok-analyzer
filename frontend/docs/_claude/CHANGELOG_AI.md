# AI Changelog

## 2026-03-03
### Summary
Added comprehensive frontend features for billing, support tickets, and live chat systems, bridging customer service and payment flows.

### Files modified
- **Billing**: Added packages, invoices, checking out (`src/modules/user/infrastructure/ui/pages/billing/*`), and admin package and gateway management (`src/modules/admin/infrastructure/ui/pages/billing/*`). Integrated Stripe and PayPal components.
- **Tickets**: Added ticket creation and detailed view for both users (`src/modules/user/infrastructure/ui/pages/TicketsPage.tsx`, `TicketDetailPage.tsx`) and admins (`src/modules/admin/infrastructure/ui/pages/TicketsAdminPage.tsx`, `TicketAdminDetailPage.tsx`, `TicketCategoriesPage.tsx`), plus a guest ticket portal (`src/modules/public/infrastructure/ui/pages/GuestTicketPortal.tsx`).
- **Live Chat**: Introduced `LiveChatWidget.tsx` for users and a dedicated `LiveChatAdminConsolePage.tsx` interface for admins to handle real-time support.
- **Auth/Public**: Refactored `LoginPage` and `RegisterPage` to be more modular with `AuthModal`, `LoginForm`, `RegisterForm`. Added `ContactPage.tsx` and `CheckEmailPage.tsx`.
- **Infrastructure**: Added related API clients for billing, tickets, live chat sessions, and contact endpoints across admin, user, and public modules. Modified existing routing and URL utilities.

### Behavioral/UI impact
- **User Capabilities**: Users can now purchase credits (via Stripe/PayPal), view their invoices, submit support tickets, and access real-time live chat assistance directly from the UI.
- **Admin Capabilities**: Admins have new dedicated pages to manage credit packages, payment gateways, handle support tickets, and conduct live chat sessions with users/guests.
- **Auth Flow**: Authentication views are cleaner through the use of dedicated components and modals, streamlining the login/registration process.

### Notes
- Ensure backend services (Stripe/PayPal webhooks, live chat websockets, ticket system database) are properly configured to support these frontend additions.

## 2026-02-03
### Summary
Refactored DataTables to enforce manual search and fixed Admin Impersonation functionality.

### Files modified
- **Admin**: `src/modules/admin/infrastructure/api/index.ts` (Fixed impersonation endpoint).
- **UI Pages**: `PriceAlertsPage.tsx`, `RecipientsPage.tsx`, `CookiesList.tsx`, `CountriesList.tsx`, `PermissionsList.tsx`, `SyntheticsTasksList.tsx` (Refactored to manual search).
- **New Components**: `src/modules/user/infrastructure/ui/components/TrackedProductAlertsModal.tsx`.
- **Cleaned Up**: `TrackedProductsPage.tsx`.

### Behavioral/UI impact
- **Search**: All data tables now require explicit search trigger (Enter key or "Search" button). "Search" button added to all search inputs.
- **Admin Impersonation**: "Login As" feature on Users List now functions correctly (redirects to dashboard as target user).
- **Tracked Products**: Alert management logic moved to a dedicated modal (`TrackedProductAlertsModal`).

### Notes
- Impersonation endpoint corrected to `/admin/users/{id}/login-as`.

## 2026-01-28
### Summary
Initial documentation snapshot generation and Screenshot Modal UI overhaul.

### Files modified
- `docs/PROJECT_CONTEXT.md` (New): Created high-level architectural documentation.
- `docs/API_CONTEXT.md` (New): Created API contract documentation based on `openapi.json`.
- `src/components/ScreenshotModal.tsx`: Major UI update implementing a macOS-style window design.

### Behavioral/UI impact
- **Screenshot Modal**: Now presents images within a styled window frame featuring traffic-light controls (visual only) and a mock address bar showing the Amazon URL. Added a floating glass-style footer for navigation controls (Next/Prev, Status indicators).
- **Documentation**: Established baseline project and API context files.

### Notes
## 2026-01-28
### Summary
Global UI rebranding ("Products" to "Explore"), account verification flow fix, and introduction of Favorites and Notification Rules.

### Files modified
- **Branding/UI**: Updated `Dashboard.tsx`, `Layout.tsx`, `Login.tsx`, `ProductDetail.tsx`, `Products.tsx`, `ProductsList.tsx`, `Register.tsx`, `UserForm.tsx`, `VerifyAccount.tsx`.
- **Account Verification**: `src/components/VerifyAccount.tsx`, `src/components/Login.tsx`.
- **New Features**: 
  - `src/components/Favorites.tsx`, `src/components/FavoriteButton.tsx`, `src/contexts/FavoritesContext.tsx`.
  - `src/components/NotificationRules.tsx`.
- **Infrastructure**: `src/services/dynamicApiClient.ts`, `src/types/api.ts`, `src/routes/router.tsx`.
- **API**: `openapi.json` (metadata/synchronization).

### Behavioral/UI impact
- **Explore Rebranding**: All user-facing labels changed from "Product" to "Explore" or "Item". Navigation icon updated to search. URLs remain `/products` for backward compatibility.
- **Verification Redirect**: Success flow now redirects to `/login?verified=true`, displaying a confirmation toast on the login page to avoid 401/4xx errors on protected routes.
- **Favorites & Notifications**: Users can now mark products as favorites and configure notification rules (price change triggers, cooldowns).

### Notes
- API entrypoints synchronized with backend contract.
- Added `FavoritesContext` for global management of user favorites.

## 2026-02-01
### Summary
Major overhaul of User Account UI and logic: Replaced "Favorites" with "Tracked Products" and "Notification Rules" with "Price Alerts" & "Recipients".

### Files modified
- **New Components**: `TrackedProducts.tsx`, `PriceAlerts.tsx`, `Recipients.tsx`, `DataTable.tsx`, `TrackButton.tsx`.
- **Deleted**: `Favorites.tsx`, `NotificationRules.tsx`.
- **Infrastructure**: `TrackedProductsContext.tsx` (replaced FavoritesContext), `dynamicApiClient.ts`, `loaders.ts`.
- **API Contract**: `openapi.json` updated to refactor user account management endpoints.

### Behavioral/UI impact
- **Tracked Products**: Replaces Favorites. Now supports detailed price monitoring, assignment of alerts, and country-specific tracking.
- **Price Alerts**: Decoupled from products. Users create alert rules (e.g., "Price dropped by 10%") and assign them to tracked products.
- **Recipients**: New view to manage notification channels (Email, Slack, Webhook).
- **Data Tables**: Unified list experience (Tracked/Alerts/Recipients) with server-side pagination, search, filtering, and bulk actions.
- **Context Optimization**: `TrackedProductsContext` optimized to reduce API calls (skips fetch on main list page).

### Notes
- "Favorites" concept is entirely removed in favor of "Tracking".
- API heavily refactored: `/user/account/favorites` and `/user/account/notifications` are replaced by distinct resources.

## 2026-02-01
### Summary
Implemented Admin User Impersonation to allow administrators to log in as other users for support and debugging purposes. Also stabilized page layouts to prevent content shifts.

### Files modified
- `src/components/AdminQuickLogin.tsx` (New): Component for handling admin impersonation actions.
- `src/components/UsersList.tsx`: Added "Login As" button to user rows.
- `src/components/Layout.tsx`: Added global banner showing active impersonation state.
- `src/contexts/AuthContext.tsx`: Added `impersonate` and `stopImpersonation` methods.
- `src/services/dynamicApiClient.ts`: Added `loginAsUser` API integration.
- `src/components/PriceAlerts.tsx`, `src/components/Recipients.tsx`, `src/components/TrackedProducts.tsx`: Hoisted headers to fix layout shifts.

### Behavioral/UI impact
- **Admin Impersonation**: Admins can now start a session as any user from the Users List.
- **Visual Feedback**: A persistent banner appears at the top of the app while impersonating, with an "Exit" button.
- **Layout Stability**: Page headers now remain stable during data loading on list pages.

### Notes
- Impersonation requires Admin role.
- New API endpoint used: `/admin/users/{id}/login-as` (handled in client).

## 2026-02-02
### Summary
Refactoring to Modular/Hexagonal Architecture to improve code organization and scalability.

### Files modified
- **Modules Created**: `src/modules/admin`, `src/modules/auth`, `src/modules/products`, `src/modules/user`.
- **Infrastructure**: Moved pages and components into `infrastructure/ui` within each module.
- **Routing**: Updated `src/App.tsx` and `src/routes/router.tsx` to use module-based routes.

### Behavioral/UI impact
- No visible UI changes (pure refactor).
- Improved code integrity and separation of concerns (Domain/Application/Infrastructure layers).

### Notes
- `openapi.json` shows trivial changes (whitespace), effectively no API contract change.

## 2026-02-04
### Summary
Implemented bulk delete functionality for Price Alerts and Recipients lists, and refined Price Alert trigger options logic.

### Files modified
- **Price Alerts**: `src/modules/user/infrastructure/ui/pages/PriceAlertsPage.tsx` (Added bulk delete, conditional trigger options).
- **Recipients**: `src/modules/user/infrastructure/ui/pages/RecipientsPage.tsx` (Added bulk delete).
- **Domain**: `src/modules/user/domain/PriceAlert.ts`.

### Behavioral/UI impact
- **Bulk Actions**: Users can now select multiple Price Alerts or Recipients and delete them in a batch operation with a confirmation modal and progress indicator.
- **Form Simplification**: Price Alert creation form now conditionally hides irrelevant options (e.g., price-based triggers are hidden when "Back in Stock" is the target).

### Notes
- Bulk delete uses a client-side iteration with an `AbortController` to handle multiple delete requests.

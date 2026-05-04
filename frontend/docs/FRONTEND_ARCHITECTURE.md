# Frontend Architecture

**Source of truth**: the code. This document is generated from static analysis. When code conflicts with this document, the code wins.

---

## Stack

| Concern | Technology |
|---------|-----------|
| Framework | React 19 |
| Language | TypeScript 5.9 |
| Build tool | Vite 7 |
| Routing | React Router v7 (`createBrowserRouter`) |
| Styling | Tailwind CSS v4 |
| HTTP client | Axios 1.x (via `src/api/client.ts`) |
| Forms | react-hook-form + zod |
| Icons | lucide-react |
| Toasts | react-hot-toast |
| Charts | chart.js + react-chartjs-2 |
| Payments | @stripe/react-stripe-js, @paypal/react-paypal-js |
| Date utils | date-fns |

---

## Layered Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Pages                                                      │
│  src/modules/*/infrastructure/ui/pages/                     │
│  src/components/Dashboard.tsx                               │
│  Thin orchestrators — compose components, call loaders      │
├─────────────────────────────────────────────────────────────┤
│  Components                                                 │
│  src/modules/*/infrastructure/ui/components/                │
│  src/components/                                            │
│  src/components/ui/   ← Design system primitives           │
│  Pure UI — receive props, emit events, no API calls         │
├─────────────────────────────────────────────────────────────┤
│  Route Loaders                                              │
│  src/routes/loaders.ts                                      │
│  Pre-fetch data before page render — may call apiRequest    │
├─────────────────────────────────────────────────────────────┤
│  Repository Ports (Interfaces)                              │
│  src/modules/*/application/ports/                           │
│  Abstract contracts — TypeScript interfaces only            │
├─────────────────────────────────────────────────────────────┤
│  Repository Implementations                                 │
│  src/modules/*/infrastructure/api/                          │
│  Implement ports — use apiRequest exclusively               │
├─────────────────────────────────────────────────────────────┤
│  API Client                                                 │
│  src/api/client.ts  → apiRequest()                         │
│  Axios instance with auth interceptor, retry, cache, dedupe │
├─────────────────────────────────────────────────────────────┤
│  Backend API                                                │
│  FastAPI, port 8000                                        │
│  ../maborak-framework-backend/                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
src/
├── api/
│   ├── client.ts          # Axios instance + apiRequest() — THE entry point for all HTTP
│   └── cache.ts           # In-memory TTL cache + in-flight deduplication
├── components/
│   ├── guards/
│   │   ├── RequireAuth.tsx    # Redirects to / if not authenticated
│   │   ├── RequireAdmin.tsx   # Redirects to / if not admin
│   │   └── RequireGuest.tsx   # Redirects logged-in users away from auth pages
│   ├── ui/
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Select.tsx
│   │   ├── Modal.tsx
│   │   ├── FormField.tsx
│   │   ├── LoadingState.tsx
│   │   ├── EmptyState.tsx
│   │   ├── Skeleton.tsx
│   │   ├── TableSkeleton.tsx
│   │   ├── ProductsListSkeleton.tsx
│   │   ├── RecipientsSkeleton.tsx
│   │   ├── Switch.tsx
│   │   ├── ProgressBar.tsx
│   │   └── StackedProgressBar.tsx
│   ├── Layout.tsx             # App shell — sidebar + top bar
│   ├── Dashboard.tsx          # Public dashboard (product list)
│   ├── AddProduct.tsx         # Add product to watchlist
│   ├── DataTable.tsx          # Shared table component
│   └── (legacy components)   # PriceAlerts.tsx, Recipients.tsx, MyAccount.tsx
├── config/
│   ├── env.ts             # All VITE_ env vars — import configuration from here only
│   └── appConfig.ts       # APP_CONFIG with typed API endpoint registry
├── hooks/
│   ├── useApiClient.ts        # Connectivity-aware API hook
│   ├── useApiConnectivity.ts  # Backend health check
│   └── useCaptcha.ts          # CAPTCHA token management (recaptcha_v3 / turnstile / none)
├── modules/
│   ├── auth/
│   │   ├── domain/
│   │   │   ├── AuthUser.ts
│   │   │   └── AuthTokens.ts
│   │   ├── application/ports/AuthRepository.ts
│   │   └── infrastructure/
│   │       ├── api/AuthRepositoryImpl.ts
│   │       └── ui/pages/    # LoginPage, RegisterPage, ForgotPasswordPage, ResetPasswordPage, VerifyAccountPage
│   ├── user/
│   │   ├── domain/
│   │   │   ├── User.ts
│   │   │   ├── TrackedProduct.ts
│   │   │   ├── PriceAlert.ts
│   │   │   └── Recipient.ts
│   │   ├── application/ports/
│   │   │   ├── UserRepository.ts
│   │   │   ├── TrackingRepository.ts
│   │   │   ├── PriceAlertRepository.ts
│   │   │   └── RecipientRepository.ts
│   │   └── infrastructure/
│   │       ├── api/
│   │       │   ├── UserRepositoryImpl.ts
│   │       │   ├── TrackingRepositoryImpl.ts
│   │       │   ├── PriceAlertRepositoryImpl.ts
│   │       │   ├── RecipientRepositoryImpl.ts
│   │       │   ├── billing.ts     # Flat API functions for billing
│   │       │   └── tickets.ts     # Flat API functions for tickets
│   │       └── ui/
│   │           ├── pages/         # TrackedProductsPage, PriceAlertsPage, RecipientsPage, MyAccountPage, etc.
│   │           └── components/    # TrackedProductAlertsModal, billing components
│   ├── admin/
│   │   ├── domain/types.ts
│   │   ├── application/ports/index.ts
│   │   └── infrastructure/
│   │       ├── api/           # billing.ts, tickets.ts, mappers.ts (flat API functions)
│   │       ├── adminRoutesImpl.tsx    # All admin route definitions
│   │       ├── adminRoutesStub.ts     # Empty stub for client-mode builds
│   │       ├── routes.tsx             # Exports adminRoutes (impl or stub based on VITE_APP_MODE)
│   │       └── ui/pages/      # UsersList, UserDetail, RolesList, CountriesList, PendingPaymentsPage, etc.
│   ├── products/
│   │   ├── domain/            # entities.ts, dtos.ts
│   │   ├── application/ports/productRepository.ts
│   │   └── infrastructure/
│   │       ├── api/productRepositoryImpl.ts
│   │       ├── routes.tsx     # Product module routes (ProductListPage, ProductDetailPage)
│   │       └── ui/pages/      # ProductListPage, ProductDetailPage
│   ├── public/
│   │   └── infrastructure/
│   │       ├── api/contact.ts
│   │       └── ui/pages/      # ContactPage, GuestTicketPortal
│   └── livechat/
│       └── infrastructure/
│           ├── api/session.ts
│           └── ui/components/ # LiveChatWidget
├── routes/
│   ├── router.tsx         # createBrowserRouter — all route definitions
│   └── loaders.ts         # Route loader functions (pre-fetch data)
├── types/
│   └── api.ts             # All API request/response TypeScript interfaces
└── utils/
    ├── cn.ts              # clsx + tailwind-merge
    ├── dateUtils.ts
    ├── imageUtils.ts
    ├── url.ts
    ├── appRoutes.ts
    └── roles.ts
```

---

## Routing

### Router Configuration

`src/routes/router.tsx` uses `createBrowserRouter` with three access levels:

```
/ (Layout shell)
├── Public (no auth required)
│   ├── /                     → Dashboard
│   ├── /products             → ProductListPage
│   └── /products/:id         → ProductDetailPage
├── RequireAuth (JWT required)
│   ├── /{userPrefix}         → MyAccountPage
│   ├── /{userPrefix}/tracked-products   → TrackedProductsPage
│   ├── /{userPrefix}/price-alerts       → PriceAlertsPage
│   ├── /{userPrefix}/recipients         → RecipientsPage
│   ├── /{userPrefix}/visit-history      → VisitHistoryPage
│   ├── /{userPrefix}/tickets            → TicketsPage
│   ├── /{userPrefix}/billing/*          → Billing pages
│   └── watch-product                    → AddProduct
└── RequireAdmin (admin role required)
    └── /{adminPrefix}/*      → Admin pages

Guest-only (redirects logged-in users):
├── /login
├── /register
└── /forgot-password
```

### Route Prefix Obfuscation

```typescript
// src/routes/router.tsx
const U = appConfig.userRoutePrefix;    // default: 'account', configurable via VITE_USER_ROUTE_PREFIX
const A = appConfig.adminRoutePrefix;  // default: 'management', configurable via VITE_ADMIN_ROUTE_PREFIX
```

This means `/account/tracked-products` can become `/a9b3c1/tracked-products` in production — path enumeration mitigation.

### Route Loaders

Loaders in `src/routes/loaders.ts` pre-fetch data before the page renders:

- `dashboardLoader` — recent products
- `myAccountLoader` — user account info
- `recipientsListLoader` — paginated recipients
- `trackedProductsLoader` — tracked products + price alerts (parallel)
- `priceAlertsLoader` — price alerts + recipients (parallel)
- `visitHistoryLoader` — visit history

Loaders are skipped (set to `undefined`) when `VITE_LOADER_TYPE=shimmer|skeleton` — data loads client-side.

### withLoader Helper

```typescript
const withLoader = (loaderFn) =>
  (uiConfig.loaderType === 'shimmer' || uiConfig.loaderType === 'skeleton')
    ? undefined
    : loaderFn;
```

---

## API Client

### `apiRequest` Function (`src/api/client.ts`)

The single entry point for all HTTP requests:

```typescript
apiRequest<T>(config: AxiosRequestConfig, options?: RequestOptions): Promise<T>
```

**Options:**
- `signal?: AbortSignal` — cancellation (passed from loader `request.signal`)
- `cacheTtlMs?: number` — in-memory response cache TTL in milliseconds
- `dedupe?: boolean` — if true, concurrent identical requests share one promise
- `cacheKey?: string` — custom cache key override

**Interceptors:**
- Request: attaches `Authorization: Bearer {auth_token}` from localStorage
- Response 401: clears auth tokens, dispatches `auth:unauthorized`, redirects to `/`
- Response 403: dispatches `auth:forbidden`
- Retry: exponential backoff for network errors and 5xx on idempotent methods

---

## Authentication

- JWT HS256 (access 900s, refresh 2592000s)
- Stored in `localStorage`:
  - `auth_token` — access token
  - `refresh_token` — refresh token
  - `auth_user` — serialized user object
- Auth check: presence of `auth_token` in localStorage
- No automatic token refresh implemented — 401 triggers full logout

---

## Admin Module Build Modes

Controlled by `VITE_APP_MODE`:

| Mode | Admin Routes | User Routes |
|------|-------------|-------------|
| `full` | ✅ all | ✅ all |
| `client` | ❌ none (stub) | ✅ all |
| `admin` | ✅ all | ❌ none |

`src/modules/admin/infrastructure/routes.tsx` exports either `adminRoutesImpl.tsx` or `adminRoutesStub.ts` based on build mode.

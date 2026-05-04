# API Usage

**Source of truth**: `../maborak-framework-backend/.claude/CLAUDE.md` for backend contracts.
**Frontend implementation**: `src/api/client.ts`, `src/types/api.ts`, `src/modules/*/infrastructure/api/`.

---

## API Client

### The `apiRequest` Function

All HTTP calls must go through `apiRequest` from `src/api/client.ts`. This is the only permitted HTTP entry point.

```typescript
import { apiRequest } from '../../../../api/client';

const response = await apiRequest<ApiResponse<TrackedProductResponse>>({
  method: 'GET',
  url: '/user/account/tracked-products',
  params: { page: 1, page_size: 10 },
});
```

**Never call `axios.get()`, `fetch()`, or any raw HTTP directly in a component or repository.**

### Request Options

```typescript
const response = await apiRequest<T>(config, {
  signal: request.signal,  // AbortSignal from loader — cancels on navigation
  dedupe: true,            // deduplicate concurrent identical requests
  cacheTtlMs: 10000,       // cache response for 10 seconds
  cacheKey: 'custom-key',  // override auto-generated cache key
});
```

---

## Authentication

### Token Storage

Auth tokens are stored in `localStorage`:

| Key | Content |
|-----|---------|
| `auth_token` | JWT access token (expires in 900s) |
| `refresh_token` | JWT refresh token (expires in 2592000s) |
| `auth_user` | Serialized user object |

### Automatic Token Injection

The Axios request interceptor in `src/api/client.ts` automatically attaches the token:

```
Authorization: Bearer {auth_token}
```

No manual header setting is needed in repository implementations.

### 401 Handling

On any 401 response from a non-auth endpoint:
1. All three localStorage keys are cleared
2. A `CustomEvent('auth:unauthorized')` is dispatched on `window`
3. Browser redirects to `/`

Repository implementations do not need to handle 401 — the interceptor handles it globally.

### Public Endpoints (No Auth)

These endpoints are called without a token:
- `GET /products` — product list
- `GET /products/{id}` — product detail
- `POST /auth/login`
- `POST /auth/register`
- `POST /auth/forgot-password`
- `GET /health`

The interceptor only attaches the token if it exists in localStorage — absent token = no header.

---

## Request/Response Envelope

Most backend endpoints wrap responses in:

```json
{
  "success": true,
  "message": "OK",
  "data": { ... }
}
```

Use the `unwrap` helper (defined in `src/routes/loaders.ts`):

```typescript
const unwrap = <T>(res: any): T => {
  if (res && typeof res === 'object' && 'success' in res && 'data' in res) {
    return res.data;
  }
  return res as T;
};
```

The frontend type `ApiResponse<T>` models this envelope:

```typescript
export interface ApiResponse<T = any> {
  success: boolean;
  message: string;
  data?: T;
}
```

**Some endpoints do NOT wrap** (e.g., `PUT /user/account/edit` may return the user object directly). Repository implementations handle this with normalization guards.

---

## Pagination

### Backend Pagination Shape

All paginated endpoints return:

```json
{
  "pagination": {
    "total": 100,
    "page": 1,
    "page_size": 10,
    "total_pages": 10
  }
}
```

The array key varies by endpoint:
- `/user/account/tracked-products` → `tracks: []`
- `/user/account/price-alerts` → `price_alerts: []`
- `/user/account/recipients` → `recipients: []`
- `/user/account/visits` → `visits: []`
- `/products` → `products: []`
- `/admin/users` → `users: []`
- `/admin/billing/invoices` → `items: []`

### Frontend Pagination Types

```typescript
export interface PaginationMeta {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}
```

`has_next` and `has_previous` are computed by `TrackingRepositoryImpl.list()` — not returned by backend directly.

### Requesting a Page

Always pass pagination params:

```typescript
await apiRequest({
  method: 'GET',
  url: '/user/account/tracked-products',
  params: {
    page: 1,
    page_size: 10,
    search: '',
    country_code: 'BO',
  }
});
```

---

## Error Handling

### HTTP Errors

Axios throws on non-2xx responses. Repository implementations should let errors propagate to the caller:

```typescript
// In repository implementation — do NOT catch errors silently
async list(): Promise<ApiResponse<...>> {
  return apiRequest({ method: 'GET', url: this.baseUrl });
  // If apiRequest throws, let it bubble up to the component or loader
}
```

### In Page Components

```tsx
const handleDelete = async (id: number) => {
  try {
    const repo = new TrackingRepositoryImpl();
    await repo.remove(id);
    toast.success('Track removed');
    // refresh list
  } catch (err: any) {
    const message = err?.response?.data?.detail || err?.message || 'Failed to remove track';
    toast.error(message);
  }
};
```

### Backend Error Shape

```json
{
  "detail": "Error message from backend"
}
```

Access via `err?.response?.data?.detail`.

### In Route Loaders

Loaders should NOT catch 401 errors — the interceptor handles those. They should catch and re-throw other errors or return `null`:

```typescript
export const myLoader = async ({ request }: LoaderFunctionArgs) => {
  try {
    const response = await apiRequest(..., { signal: request.signal });
    return unwrap(response);
  } catch (error: any) {
    if (error?.response?.status === 401 || error?.code === 'ERR_CANCELED') {
      return null; // interceptor will redirect
    }
    throw error; // RouteErrorBoundary will catch this
  }
};
```

---

## Endpoint Reference by Module

### Auth (`/auth`)

| Action | Method | Path | Auth |
|--------|--------|------|------|
| Login | POST | `/auth/login` | None |
| Register | POST | `/auth/register` | None |
| Forgot password | POST | `/auth/forgot-password` | None |
| Reset password | POST | `/auth/reset-password` | None |
| Change password | POST | `/auth/change-password` | Bearer |
| Verify account | GET | `/auth/verify?token=` | None |
| Resend verification | POST | `/auth/resend-verification` | Bearer |

### User Account (`/user/account`)

| Action | Method | Path | Auth |
|--------|--------|------|------|
| Get profile | GET | `/user/account` | Bearer |
| Edit profile | PUT | `/user/account/edit` | Bearer |
| Delete account | DELETE | `/user/account/delete` | Bearer |
| List visit history | GET | `/user/account/visits` | Bearer |

### Tracked Products (`/user/account/tracked-products`)

| Action | Method | Path | Notes |
|--------|--------|------|-------|
| List | GET | `/user/account/tracked-products` | Params: `page`, `page_size`, `search`, `country_code` |
| Add | POST | `/user/account/tracked-products` | Costs 1 credit; requires captcha |
| Get | GET | `/user/account/tracked-products/{id}` | |
| Update alerts | PUT | `/user/account/tracked-products/{id}` | Body: `{ country_code, price_alert_ids[] }` |
| Delete | DELETE | `/user/account/tracked-products/{id}` | No body; credit NOT refunded |
| Resume | POST | `/user/account/tracked-products/{id}/resume` | Costs 1 credit; extends 30 days |

**Important:** `add` sends `price_alert_id` (singular, optional) not `price_alert_ids`.

### Price Alerts (`/user/account/price-alerts`)

| Action | Method | Path | Notes |
|--------|--------|------|-------|
| List | GET | `/user/account/price-alerts` | Params: `page`, `page_size`, `search`, `is_active` |
| Create | POST | `/user/account/price-alerts` | Requires verified user |
| Get | GET | `/user/account/price-alerts/{id}` | |
| Update | PUT | `/user/account/price-alerts/{id}` | |
| Delete | DELETE | `/user/account/price-alerts/{id}` | |

**`TriggerType` values (frontend):** `value_up`, `value_down`, `percent_up`, `percent_down`, `becomes_available`, `becomes_unavailable`, `price_saved`

### Recipients (`/user/account/recipients`)

| Action | Method | Path |
|--------|--------|------|
| List | GET | `/user/account/recipients` |
| Create | POST | `/user/account/recipients` |
| Update | PUT | `/user/account/recipients/{id}` |
| Delete | DELETE | `/user/account/recipients/{id}` |
| Verify | POST | `/user/account/recipients/{id}/verify` |
| Resend verification | POST | `/user/account/recipients/{id}/resend-verification` |

### Billing (`/user/account/billing`)

| Action | Method | Path |
|--------|--------|------|
| List packages | GET | `/user/account/billing/packages` |
| Get payment methods | GET | `/user/account/billing/payment-methods` |
| Create order | POST | `/user/account/billing/orders` |
| Capture payment | POST | `/user/account/billing/orders/{id}/capture` |
| List invoices | GET | `/user/account/billing/invoices` |
| Get invoice | GET | `/user/account/billing/invoices/{id}` |
| List transactions | GET | `/user/account/billing/transactions` |

### Products (`/products`) — Public

| Action | Method | Path |
|--------|--------|------|
| List | GET | `/products` |
| Get by ID | GET | `/products/{id}` |
| Add | POST | `/products/add` |
| Check | POST | `/products/check` |
| Price history | GET | `/products/{id}/price-history` |

### Admin (`/admin`)

| Section | Base Path | Key Actions |
|---------|-----------|-------------|
| Users | `/admin/users` | CRUD, impersonation |
| RBAC Roles | `/admin/roles` | CRUD, assign permissions |
| RBAC Permissions | `/admin/permissions` | CRUD |
| Countries | `/admin/countries` | CRUD, enable/disable |
| Cookies | `/admin/cookies` | CRUD |
| Synthetics | `/admin/synthetics` | list, task details |
| Billing packages | `/admin/billing/packages` | CRUD |
| Billing pending | `/admin/billing/pending-payments` | list, approve/reject |
| Payment gateways | `/admin/payment-gateways` | read, update, enable/disable |
| Tickets | `/admin/tickets` | list, detail, reply, assign |
| Live chat | `/admin/livechat/sessions` | list, detail, respond |

---

## CAPTCHA

When `VITE_CAPTCHA_PROVIDER` is not `none`, include `captcha_token` in:
- `POST /auth/register` → `body.captcha_token`
- `POST /user/account/tracked-products` → `query.captcha_token` AND `body.captcha_token`
- `POST /auth/forgot-password` → `body.captcha_token`
- `POST /user/account/recipients/{id}/verify` → `body.captcha_token`

Use `useCaptcha` from `src/hooks/useCaptcha.ts` to obtain tokens.

When provider is `none`, pass `captcha_token: undefined` — backend accepts missing token.

---

## Parallel Fetching

Always fetch independent endpoints in parallel:

```typescript
const [alertsRes, recipientsRes] = await Promise.all([
  apiRequest({ url: '/user/account/price-alerts', ... }),
  apiRequest({ url: '/user/account/recipients', ... }),
]);
```

Never await them sequentially — sequential fetches add latency proportional to N × RTT.

---

## Caching Strategy

| Data | cacheTtlMs | Rationale |
|------|-----------|-----------|
| Dashboard products | 10,000 ms | Changes infrequently |
| User account | 10,000 ms | Credit balance updates matter — keep short |
| Recipients | `apiConfig.defaultCacheTtl` | User-configured default |
| Price alerts | `apiConfig.defaultCacheTtl` | User-configured default |
| Tracked products | `apiConfig.defaultCacheTtl` | User-configured default |
| Billing packages | 30,000+ ms | Rarely changes |
| Countries list | 60,000+ ms | Almost never changes |

`apiConfig.defaultCacheTtl` defaults to `0` (no cache) unless `VITE_API_CACHE_TTL` is set.

---

## Request Deduplication

Use `dedupe: true` in loaders to prevent duplicate requests when multiple components mount simultaneously:

```typescript
await apiRequest(config, { signal: request.signal, dedupe: true, cacheTtlMs: 10000 });
```

With `dedupe: true`, concurrent identical requests share a single in-flight promise — the second caller waits for the first's response.

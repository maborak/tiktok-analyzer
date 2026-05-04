# Phoveus — Architecture & Conventions

This file is loaded as project context by Claude Code. Read it first.

## What this repo is

A SaaS-style template: FastAPI backend (Python 3.12+, hexagonal: ports
/ adapters / domain / routes), React frontend (TypeScript, Vite,
TanStack Router, Tailwind), and an admin dashboard. Each new project
forks this repo via `scripts/new-project.sh` — see top-level README.

If you're working on a fork of this framework, brand strings and the
env-var prefix have already been renamed by `scripts/new-project.sh`;
the **architecture and conventions in this file still apply**.

## Quick start

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # edit DATABASE_URL, JWT_SECRET, etc.
uvicorn api_main:app --reload

# Frontend
cd frontend && npm install && npm run dev

# DB migrations live in backend/database/migrations/. They run
# automatically at startup; see initialize_services() in api_main.py.
```

## Architecture overview

Backend follows hexagonal architecture. The contract layer is **ports**;
implementations are **adapters**. Business logic is **domain services**
that depend on port interfaces, never on adapters or the framework.

```
┌────────────────────────────────────────────┐
│  routes/  (FastAPI APIRouter, thin)        │
│      ↓ depend on                            │
│  domain/services/  (business logic)         │
│      ↓ depend on (port abstractions)        │
│  ports/  (ABC interfaces)                   │
│      ↑ implemented by                       │
│  adapters/  (SQLAlchemy, HTTP, queue, etc.) │
│  database/  (models, migrations)            │
└────────────────────────────────────────────┘
```

Routes know about services, services know about ports, adapters know
about ports + the outside world (DB, HTTP). Don't shortcut this — if a
route imports an adapter directly, that's a smell.

## Backend layout

```
backend/
├── api_main.py                  # FastAPI app + initialize_services()
├── config.py                    # CONFIG dict (env-bootstrapped)
├── adapters/
│   ├── persistence/             # SQLAlchemy adapters per port
│   ├── paypal_payment.py        # PaymentGatewayPort impls
│   ├── stripe_payment.py
│   ├── rbac_adapter.py
│   └── notification_queue/      # Redis-backed
├── ports/                       # ABC interfaces — one per concern
├── domain/
│   ├── entities/                # dataclasses + the typed config registry
│   └── services/                # business logic (auth, ticket, payment, …)
├── database/
│   ├── core/                    # engine, base, session
│   ├── config/                  # AppConfigModel, ConfigSnapshotModel, …
│   ├── migrations/              # idempotent CREATE / ALTER scripts
│   └── hooks/                   # post-init hooks (seed RBAC etc.)
└── routes/
    ├── main.py                  # setup_routes() — DI dispatcher
    ├── auth.py / user/ / admin/ / billing.py / webhooks.py / …
    └── admin/                   # admin endpoints; one module per area
```

### DI wiring (the chain you'll touch most)

1. `api_main.py:initialize_services()` builds every adapter + service
   into a `_services` dict. Add new services here.
2. `routes/main.py:setup_routes(...)` accepts the services as kwargs
   and dispatches them to per-module globals.
3. `routes/admin/__init__.py:set_dependencies(...)` assigns to module-
   level globals like `admin_configuration.config_service = …`. Routes
   read from those globals (set to `None` at import time).

When you add a new service, you must touch all three: `initialize_services`,
`setup_routes` signature, and `admin.set_dependencies`. Skipping any
leaves the route's module global `None` and you'll get a 503.

### Auth + RBAC

Every admin route uses `Depends(get_admin_user_dependency)` from
`routes/admin/general.py`. That dependency:
- Accepts JWT via OAuth2 or `Authorization: Bearer …`
- Validates via `auth_service.get_auth_context(token)`
- Refuses with 401 on missing/invalid token
- Refuses with 403 unless the resolved AuthContext has `admin:write`

User-facing routes follow the same pattern with `get_current_user_dep`
and per-permission checks (`has_permission("billing:read")` etc.).
Permissions live in the RBAC tables, seeded by `seed_database()`.

OAuth providers (Google, GitHub, Facebook) plug into the same
`AuthService` via the `OAuthService` abstraction. Captcha (recaptcha v3
or Turnstile) gates the login + register flows when configured.

### Typed config (the Configuration feature)

Three layers:
1. `domain/entities/config_registry.py` — `CONFIG_REGISTRY` (108 keys
   across 16 namespaces) + `ENV_MAP` (key → PHOVEU_-prefixed env var
   name). Each `ConfigKeyDef` carries `value_type`, `default`,
   `sensitive`, `readonly`, `bootstrap` flags.
2. `domain/services/config_service.py` — `ConfigService`. Resolution
   chain for non-bootstrap keys is **DB → env → default**. Bootstrap
   keys (`DATABASE_URL`, `REDIS_URL`, `DB_*_POOL_*`) are env-only —
   the service can't reach the DB before they're resolved. Cache is
   warm at startup, write-through on every set/bulk_set/import/restore.
3. `routes/admin/configuration.py` — admin endpoints under
   `/admin/configuration/*`. UI at `/admin/settings/configuration`
   in the frontend.

The legacy `CONFIG` dict in `backend/config.py` is still the live
runtime source for most modules. Migrating consumers to read through
`config_service.get(key)` is a pending project — not yet done.

Distinct from `/admin/config` (raw `app_config` table CRUD), which
predates the typed feature and stays in place for namespace-keyed
generic settings.

### Event hooks

`ports/hooks/hook_manager` is a configured-at-startup singleton:

```python
hook_manager.configure(
    data_persistence=data_persistence_adapter,
    event_config_service=event_config_service,
    notification_queue=notification_queue,
)
```

Services fire events (`hook_manager.fire("user.registered", payload)`),
handlers subscribe by name, and the `EventConfigService` decides per
`(event_type, handler)` whether the handler runs (default: enabled).
The admin "Events" page exposes the matrix.

### Notifications

Redis-backed queue (`adapters/notification_queue/redis_queue.py`).
When `NOTIFICATION_QUEUE_ENABLED=true`, transactional emails enqueue
and a consumer drains them with rate-limiting + retry-with-backoff.
When disabled, sends are synchronous on the request thread.

### Database

- SQLAlchemy 2 with Declarative `Base`. Tables are namespaced via
  `get_table_name("…")` so a single deployment can host multiple
  apps in one DB if you set the prefix.
- Engines: SQLite (dev) and PostgreSQL (prod). Migrations branch on
  dialect where syntax differs.
- Migrations are **idempotent CREATE TABLE IF NOT EXISTS / ALTER…IF
  NOT EXISTS** scripts — no Alembic. Each is a top-level Python file
  in `database/migrations/`. Adding one: write the script, register
  it from the migration runner, and add a snapshot test if non-trivial.

## Frontend layout

```
frontend/src/
├── App.tsx
├── main.tsx
├── api/
│   ├── client.ts             # axios + retry + dedupe + cache + 401 refresh
│   └── cache.ts
├── routes/                   # TanStack file-based routes
│   ├── _app/admin/…lazy.tsx
│   └── _public/…
├── modules/
│   ├── admin/{pages,services,components,types}
│   ├── auth/
│   ├── livechat/
│   └── user/
├── components/
│   ├── ui/                   # Button, Input, Select, Modal, Switch,
│   │                         #   PageShell, EmptyState, LoadingState, …
│   └── sidebar/Sidebar.tsx
├── contexts/                 # AuthContext, ThemeContext
├── hooks/
└── styles/                   # tokens.css, themes.css, mono treatment
```

### Routing

TanStack Router file-based. Adding a new admin route:

1. Create the page component in `modules/admin/pages/MyPage.tsx`
2. Create `routes/_app/admin/.../mypage.lazy.tsx` with
   `createLazyFileRoute(...)({ component: MyPage })`
3. The Vite plugin regenerates `routeTree.gen.ts` (gitignored)
4. Add a sidebar item in `components/sidebar/Sidebar.tsx`

### API service pattern

One file per backend area, e.g. `modules/admin/services/configuration.ts`:

```ts
export const configurationApi = {
  listSections: () => apiRequest({ method: "GET", url: "/admin/configuration/sections" }),
  setKey: (key: string, value: unknown) =>
    apiRequest({ method: "PUT", url: `/admin/configuration/keys/${key}`, data: { value } }),
};
```

`apiRequest<T>` handles auth header injection, JWT refresh on 401,
exponential-backoff retry on 5xx + 429, optional in-flight dedupe and
TTL caching.

### UI conventions (mono display treatment)

- Pages: `<PageShell>` + `<PageHeader title icon description actions>`
- Column headers + small uppercase labels: `className="auth-mono-label"`
- Headings use JetBrains Mono Variable (configured globally — don't
  set font-family inline)
- Source/flag pills: `font-mono text-[10px]`, semantic color tones
  (primary=db, amber=env, rose=sensitive, gray=default/locked)
- Locked rows / disabled inputs get a `<Lock>` icon + a left-border
  accent rather than a "DISABLED" pill (badge-soup avoidance)

### Dark mode rules — read this before adding `dark:*`

The framework defines a CSS-variable gray scale that **auto-inverts
in dark mode**. So `text-gray-900` resolves to near-white in dark mode
*on its own*. **Do not add explicit `dark:text-gray-100`** — that
overrides the inversion and gives you dark-on-dark.

Rules of thumb:
- For text/borders on the gray scale: write the **light-mode** class
  only (`text-gray-700`, `border-gray-200`). Let the inversion do its
  job. The framework's dark-mode auditor will flag explicit dark
  variants on neutral grays as bugs.
- For accent colors that don't participate in the inversion (amber,
  rose, primary), write both: `bg-amber-50 dark:bg-amber-500/10`.
- For surface elevations in dark mode, prefer
  `dark:bg-gray-100/30` over `dark:bg-gray-800/40` — the latter
  produces a too-bright wash because gray-800 is *already inverted*.

## Recipes

### Add a typed config key

1. Add a `ConfigKeyDef(...)` to the appropriate namespace list in
   `domain/entities/config_registry.py`.
2. Add the env-var mapping to `ENV_MAP` in the same file.
3. Add a sane default to `os.getenv("PHOVEU_…", default)` in
   `backend/config.py` so the legacy `CONFIG` dict picks it up too,
   *if* the key is read by code that hasn't migrated to
   `config_service.get(...)` yet.
4. The admin UI surfaces the key automatically — no frontend changes.

### Add an admin endpoint

1. Either extend an existing module under `routes/admin/` or create a
   new one. Each module: a `router = APIRouter(prefix="/x", tags=["…"])`,
   module-level globals for any injected services (default `None`),
   and route handlers using `Depends(get_admin_user_dependency)`.
2. In `routes/admin/__init__.py`: import the module, include its
   router, and assign `admin_x.my_service = my_service_instance` in
   `set_dependencies(...)`.
3. In `routes/main.py`: thread the service through `setup_routes`.
4. In `api_main.py:initialize_services()`: build the service and add
   it to the `_services` dict + the `setup_routes(...)` call.

### Add a domain event

1. Pick a name (`thing.happened`).
2. Fire from the service: `hook_manager.fire("thing.happened", payload)`.
3. Register a handler. Handlers can route to email, audit log, etc.
4. The handler appears automatically in the admin Events matrix —
   admins can disable it without a deploy.

### Add an admin page (frontend)

1. `modules/admin/services/<area>.ts` — typed API client with one
   method per backend route.
2. `modules/admin/pages/<Page>.tsx` — `PageShell` + `PageHeader`,
   `auth-mono-label` headers, type-aware inputs from
   `components/ui/*`. Avoid hardcoded grays — see dark-mode rules.
3. `routes/_app/admin/.../<page>.lazy.tsx` — TanStack lazy route.
4. Sidebar entry in `components/sidebar/Sidebar.tsx`.

## Core vs module

What every project keeps:
- `users`, `auth`, `rbac`, typed `config`, `event_hooks`, audit log,
  rate limiting, transactional email + notification queue, the admin
  shell + theme + Configuration UI

What's a module (delete if not needed):
- `tickets/` — support ticket CRUD + categories + UI
- `billing/` — credit packages, payment gateways, invoices, Stripe +
  PayPal adapters; the abstractions stay, the gateway adapters can be
  pruned per project
- `livechat/` — chat widget + admin queue
- specific OAuth providers (Google/GitHub/Facebook) — keep the
  abstraction, drop unused providers

When you delete a module, also clean up imports in `api_main.py:
initialize_services`, `routes/main.py:setup_routes`,
`routes/admin/__init__.py`, the sidebar, and the related route files.

## Pitfalls

- **Hardcoded `bg-gray-*` / `text-gray-*` without dark variant on user-
  visible surfaces** — the auto-inversion handles neutrals; explicit
  `dark:text-gray-100` is the *bug*, not the fix. Run
  `/frontend_dark-mode-audit` before claiming UI work done.
- **Skipping the port/adapter split** — never import an adapter into a
  service or route; depend on the port ABC. Keeps the test surface clean.
- **Forgetting the third leg of DI wiring** — `set_dependencies` is
  easy to miss after `setup_routes`. The route handler returns 503
  ("not available") because the module global is still `None`.
- **Writing to bootstrap config keys at runtime** — `ConfigService`
  refuses `DATABASE_URL`, `REDIS_URL`, `DB_*_POOL_*` writes by design;
  these need an env-var change + restart.
- **Editing `routeTree.gen.ts` by hand** — it's gitignored and
  regenerated by the Vite plugin. Touch the file route definitions
  instead.
- **Solo-grepping for frontend bugs** — the project has dedicated
  audit agents (`frontend-dark-mode-auditor`, `ai-slop-detector`).
  Dispatch them; they catch what grep misses (e.g. CSS-variable
  inversion traps).

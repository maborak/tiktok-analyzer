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
1. `domain/entities/config_registry.py` — `CONFIG_REGISTRY` (116 keys
   across 17 namespaces, TikTok included) + `ENV_MAP` (key →
   PHOVEU_-prefixed env var name). Each `ConfigKeyDef` carries
   `value_type`, `default`, `sensitive`, `readonly`, `bootstrap` flags.
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
- `tiktok/` — TikTok-bot: subscribes to creator lives, persists events,
  posts chat back via Electron client. See "TikTok module" below.
- specific OAuth providers (Google/GitHub/Facebook) — keep the
  abstraction, drop unused providers

## TikTok module (read + write to TikTok lives)

**Deep-dive docs** (read these when touching the TikTok module):
- `backend/docs/DB_ARCHITECTURE.md` — engine routing, hexagonal layers,
  schema layout, caching tiers, migration strategy.
- `backend/docs/WORKER.md` — listener-pool deployment, capacity + claim
  model, lifecycle, recycle logic, the known stuck-slot bug.
- `backend/docs/EVENTS_LOGGER.md` — event capture pipeline, dedup,
  pre-aggregation, two-channel fan-out (legacy events + Phase 9 state
  deltas), failure modes.

This is the project's primary feature module. Architecturally it
follows the framework conventions — but it has one unusual constraint:
**posting to TikTok must happen on the user's machine** (their
authenticated browser session + residential IP), so we ship a
companion Electron client at `client/` that loads the framework's web
UI and adds posting capabilities via a preload-injected `window.api`.

Layout:
- Backend module: `domain/services/tiktok_service.py`, ports in
  `ports/tiktok_*.py`, adapters in `adapters/persistence/
  tiktok_persistence.py` and `adapters/tiktok_live_client.py`,
  database in `database/tiktok/`, routes in `routes/admin/tiktok.py`.
  Wired through `initialize_services` + `setup_routes` +
  `set_dependencies` like every other service.
- Frontend module: `modules/admin/services/tiktok.ts`,
  `modules/admin/pages/TikTokLives.tsx`, route at
  `routes/_app/admin/tiktok/index.lazy.tsx`, sidebar entry "TikTok".
  React detects `window.api?.sendComment` at runtime — posting UI is
  conditionally rendered only when running inside the Electron client.
- Electron client: `client/` at the repo root. Separate npm project.
  Loads the framework's web UI (Vite dev server in dev, deployed URL
  in prod) and uses a hidden BrowserWindow with `contextIsolation:false`
  to run a bridge preload that calls TikTok's `webcast/room/chat/` API
  via `fetch()`. CSP strip + CORS rewrite + CSRF preflight forge are
  installed on the partition's `webRequest` hooks.

The read pipeline (TikTokLive WebCast listener, multi-handle pool, DB
persistence, WS fan-out) lives entirely in the framework backend —
multi-tenant safe, can be deployed anywhere. The write pipeline lives
in the Electron client only.

`docs/tikfinity-analysis.md` contains the static-analysis research that
informed this architecture. Refer to it when posting breaks — the
list of webRequest header rewrites and bytedance:// protocol cancel is
there.

### Listener-pool deployment modes

The TikTokLive listener pool can run in one of two shapes, gated by the
env var `PHOVEU_BACKEND_TIKTOK_LISTENER_MODE` (default `in_process`):

- **`in_process`** — listeners run inside uvicorn alongside the API.
  Simplest, no extra processes, no Redis required. Catch: every uvicorn
  restart (e.g. `--reload` on a code change) drops every TikTokLive
  WebSocket and the in-memory `_active_match` battle state with it.
- **`worker`** — listeners run in a separate process started via
  `python cli.py system tiktok run-listener` (or `./build.sh worker`).
  The API's `tiktok_service` is constructed in **passive mode**:
  subscription CRUD endpoints still write to `tiktok_subscriptions`,
  but session lifecycle (`_start_session` / `_stop_session` /
  `start_all_enabled` / `stop_all`) is a no-op. The worker reconciles
  its in-memory listener pool against the DB every N seconds (default
  10s) — it picks up new handles, stops removed/disabled ones. Event
  fan-out goes through Redis pub/sub on channel `tiktok:events`. The
  WebSocket route at `/admin/tiktok/ws` detects worker mode and
  subscribes to that channel instead of registering an in-process
  listener.

Worker mode requires Redis (already a framework dep). Trade-off vs
in-process: API hot-reload no longer interrupts ingestion, listeners
survive API redeploys, but you operate two processes.

The split lives in:
- `adapters/tiktok_event_bus.py` — `EventPublisher` (worker → Redis)
  and `subscribe_events()` (API → Redis). Both no-op gracefully when
  Redis is down (DB persistence still works; WS fan-out is degraded).
- `cli/commands/system/tiktok.py` — the `run-listener` CLI command.
  Boots Redis + DB + service, registers the publisher, runs
  `start_all_enabled()`, then spins a reconcile loop until SIGINT.
- `domain/services/tiktok_service.py` — `passive=True` flag wired by
  `api_main.py` based on the env var.
- `routes/admin/tiktok.py` — `_ws_pump_from_service` for in-process,
  `_ws_pump_from_redis` for worker mode.

### Lives-list page rollup (`/lives/bundle`)

The `/admin/tiktok` Lives page reads `GET /admin/tiktok/lives/bundle`
on cold mount and every 30s poll. The endpoint returns
`{subs, summary, totals}` in a single round-trip — replacing what was
once three separate endpoints (`/lives`, `/lives/summary`,
`/lives/totals`). The bundle handler runs `list_subscriptions()` once
and threads the handle list into `get_lives_summary` + `get_lives_totals`
running in parallel via `asyncio.gather` + `to_thread`.

`/lives` is kept as a thin "subs-only" endpoint for the five other
consumers that enumerate handles without needing summary aggregates
(match-events modal, gifter modal, live-detail rival pills, history,
single-handle lookup). The lives page itself never hits it.

Service-layer caches:
- `_LIVES_SUMMARY_TTL_S = 60.0` — per-handle-set TTL with singleflight
  lock. Bumped from 35 s so the 30 s frontend poll always hits warm
  cache in steady state. Cold miss only on backend restart or ≥60 s idle.
- `_LIVES_TOTALS_TTL_S = 60.0` — same shape, single slot.

Wire payload is trimmed:
- `_BUNDLE_OMIT_SUMMARY_FIELDS` deny-list strips nine fields the React
  card never reads (`daily_buckets`, `top_gifter`, `comments_per_min_*`,
  `momentum_label`, `avg_*`, `n_rooms_30d`, `median_diamonds_30d`).
- `last_broadcasts` is sliced to `[0:1]` — frontend only reads the
  most-recent broadcast.
- Public endpoint (`/public/tiktok/lives`) trims the same fields via
  the `_PUBLIC_SUMMARY_FIELDS` allowlist + the same `[0:1]` slice.

### Pre-aggregated diamonds (`tiktok_event_hour_counts.diamonds`)

`get_lives_totals` reads the 24 h diamond sum from
`tiktok_event_hour_counts.diamonds` (≤79 × 25 row indexed scan)
instead of scanning gift events directly (millions of rows on a busy
install with a JSONB heap-fetch per row). The column is bumped inline
by `_bump_event_hour_count(event_type, payload)` in the persist path
for gift events. Migration: `add_event_hour_counts_diamonds.py`
(idempotent ADD COLUMN + backfill from `tiktok_events`).

Note: orphan gift events with `host_unique_id IS NULL` are correctly
excluded from this total (you can't attribute them to a tracked host).

### RBAC token cache

`adapters/auth_persistence.py:AuthPersistenceAdapter` keeps a 30 s
TTL cache keyed by `SHA256(token | ip | ua)`. Every authenticated
request previously paid 3–4 DB round-trips inside `get_auth_context`;
the cache short-circuits all of them on a repeat hit within 30 s.
TTL-only invalidation is acceptable since logout-revoked sessions
disappear within one poll cycle anyway.

### Index coverage for the lives-summary call graph

`add_tiktok_lives_summary_indexes.py` (idempotent
`CREATE INDEX CONCURRENTLY`) adds four indexes the call graph needs
at scale:
1. `ix_tiktok_rooms_host_active` — partial `(host_unique_id, last_seen_at DESC) WHERE ended_at IS NULL`
2. `ix_tiktok_rooms_host_first_seen` — `(host_unique_id, first_seen_at DESC NULLS LAST)`
3. `ix_tiktok_events_room_type_ts` — `(room_id, type, ts DESC)`
4. `ix_tiktok_worker_log_detail_host` — partial expression on `((detail->>'host')) WHERE event = 'session_reconnect'`

At current scale (~63 rooms/host) the wins are minor; these are
insurance against growth past ~1000 rooms/host.

### Perf benchmarking — `python cli.py system tiktok perf`

`backend/cli/commands/system/perf.py` exposes two commands for
before/after measurement of the lives-list endpoint:
- `perf endpoints --label <name> --json-out <path>` — captures one
  cold-miss timing + N warm batches; writes a JSON snapshot.
- `perf compare <baseline.json> <current.json>` — diff with per-row
  ms delta and a colored verdict.

Requires admin JWT via `$PHOVEU_ADMIN_TOKEN` or `--token`. Snapshots
live in `.claude/tracking/perf/`; baseline + each phase is committed
so future changes have a comparable starting point. See
`.claude/tracking/perf/REPORT.md` for the running history.

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

## Discipline rules (learned the hard way)

Each rule below is here because we hit the bug in production. They
override "looks like it should work" intuition.

- **Every `async def` FastAPI route that calls sync SQL MUST use
  `asyncio.to_thread`.** Single-user benchmarks won't surface the
  bug; concurrent users serialize on the event loop. `/lives/bundle`
  is the canonical pattern (`asyncio.gather + asyncio.to_thread`).
- **When you create a new shared component or helper, migrate ≥1
  call site in the same commit.** A new SafeAvatar with zero
  consumers is worse than no SafeAvatar — operators believe the fix
  is shipped when it isn't. See `feedback_migrate_when_creating`.
- **Audit pre-existing modifications when you commit them.** Files
  in the work tree at session start that you didn't write get the
  SAME audit rigor as new code. Bundling them under a commit message
  that describes only new work hides them from future audits. The
  `open_match` FK-flood was exactly this miss.
- **Same logical question → ONE source of truth.** When you find
  the third implementation of "is X live?" or "who are top
  gifters?", consolidate or document the difference explicitly.
  Drift between read paths is invisible until a user spots an
  inconsistency in the UI.
- **Never ship `avg × N × 0.5`-style approximations for unknown
  distributions.** Either compute the real value or omit the
  derived field. The pie's bogus "Others" slice rendered the #1
  gifter as 0% because the heuristic was 1000× wrong at production
  scale. See `feedback_no_unmeasured_approximations`.
- **State caches that depend on "every change fires an event"
  always break.** Workers drop silently, `live_end` events go
  missing, network blips happen. Every cache overlay needs an SQL-
  authority gate at read time AND a periodic sweeper at the
  storage layer. The 2026-05-16 fix shipped both.
- **Heavy children of pages with high-frequency state churn need
  `React.memo`.** The detail page's 5046-line tree reconciling on
  every WS event was an always-on cost masked by other latency
  wins. Memoize early.
- **Run `/audit` before claiming work is done.** The slash command
  exists for this exact reason. Its Step-5 landmine catalogue
  accumulates every bug class we've hit; re-running it on each
  commit costs ~2 minutes and saves hours of regression.

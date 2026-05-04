Export this full-stack project as a replicable base project at {TARGET_PATH}/.

## Goal

Create a domain-agnostic full-stack project skeleton that replicates 100% of the
architecture, infrastructure, and patterns from this codebase — both backend AND
frontend. The exported project should work as a starting point for ANY SaaS — the
next developer just fills in their domain entities, routes, and UI modules.

The backend and frontend must be in sync: API contracts, auth flow, environment
variables, route prefixes, and type definitions must match across both codebases.

---

## Phase 1 — Scan

### Backend (backend/)

Map the entire backend:
- List every directory and file under backend/
- Identify all Python packages (directories with __init__.py)
- Read the composition root (the file that creates the app and wires
  dependencies) to understand the full dependency graph
- Read the configuration module to understand all config keys and env variables
- Read .env or .env.example for all environment variables

Launch parallel agents — one per top-level package discovered. Each agent must:
- Read EVERY file in its assigned package
- Extract: all classes (with base classes and methods), all functions, all enums,
  all dataclasses, all Pydantic models, all SQLAlchemy models (with columns,
  relationships, constraints, indexes), all route definitions (method, path, auth,
  request/response types), all abstract methods, all imports
- Identify which architectural layer the package belongs to and what patterns it uses
- Note any cross-cutting concerns (events, middleware, DI, hooks)

### Frontend (frontend/)

Map the entire frontend:
- List every directory and file under frontend/src/
- Read package.json for all dependencies and scripts
- Read the Vite/build config for aliases, env modes, and build optimizations
- Read the environment config (env.ts or equivalent) for all VITE_* variables
- Read .env or .env.example for all environment variables

Launch parallel agents — one per top-level directory under src/. Each agent must:
- Read EVERY TypeScript/TSX file in its assigned directory
- Extract: all React components (with props interfaces), all contexts and what state
  they manage, all route definitions and loaders, all repository port interfaces and
  their implementations, all TypeScript types/interfaces (especially the shared API
  types file), all utility functions, all guard components, all UI design system
  components, all form validation schemas
- Identify which architectural layer each module belongs to (domain, application,
  infrastructure) and the module's internal hexagonal structure
- Note the API client implementation (interceptors, caching, deduplication, retry,
  token refresh)

---

## Phase 2 — Generate

### Backend code at {TARGET_PATH}/backend/

For every package discovered, generate the equivalent:
- Same directory structure and architectural layers
- All infrastructure code copied as-is (retry logic, session management,
  connection pooling, middleware, rate limiting, auth, RBAC, event system,
  password hashing, configuration, CLI scaffolding)
- Domain-specific code (entities, models, services, routes) exported as
  generic examples with one sample domain (e.g., "items" or "resources")
  demonstrating the pattern for each layer — enough to show how to add
  a new domain area by following the example
- Every generated Python file must be importable with real implementations
- **backend/.env.example** — every environment variable discovered, organized
  by section, with sensible defaults and comments marking production-critical ones

### Frontend code at {TARGET_PATH}/frontend/

For every module and package discovered, generate the equivalent:
- Same directory structure: src/api/, src/components/, src/config/, src/contexts/,
  src/modules/, src/routes/, src/types/, src/utils/, src/styles/, src/hooks/
- All infrastructure code copied as-is:
  - API client with interceptors (auth token, refresh, retry, rate limit headers)
  - Request cache and in-flight deduplication
  - Auth context (login, logout, register, OAuth, token refresh, session expiry,
    impersonation)
  - All other contexts discovered (theme, connectivity, progress, etc.)
  - Route guards (RequireAuth, RequireAdmin, RequireGuest)
  - UI design system components (Button, Input, Modal, Select, DataTable, Skeleton,
    EmptyState, LoadingState, FormField, etc.)
  - Route configuration with lazy loading and loaders
  - Environment config with typed AppConfig
  - Utility functions (cn, date, price, url, roles)
- Module structure: for each module discovered, export the hexagonal pattern:
  - domain/ (entities, DTOs)
  - application/ports/ (repository interfaces)
  - infrastructure/api/ (repository implementations using apiRequest)
  - infrastructure/ui/pages/ and infrastructure/ui/components/
  - index.ts barrel export with singleton repository instance
- Domain-specific modules exported as generic examples with one sample module
  demonstrating the full pattern (port → impl → page → components)
- Shared API types file (types/api.ts) with base types for auth, billing, pagination,
  and the sample domain — matching the backend's response models exactly
- **frontend/.env.example** — every VITE_* variable discovered, with defaults
  that point to the backend's default port/URL
- **package.json** — all dependencies
- **vite.config.ts** — build config with any aliases or mode-based optimizations
- **tsconfig.app.json** — TypeScript config
- **tailwind.config.js** / CSS config

### Contract sync between backend and frontend

The exported project must have these aligned across both codebases:
- Auth flow: JWT token names in localStorage must match backend's token format
- API base URL: frontend's default VITE_API_BASE_URL must point to backend's
  default port
- Route prefixes: frontend's VITE_ADMIN_ROUTE_PREFIX and VITE_USER_ROUTE_PREFIX
  must match any backend path conventions
- API types: every TypeScript interface in types/api.ts must have a matching
  Pydantic model in domain/api_models/
- Auth endpoints: frontend's AuthRepository methods must match backend's /auth/* routes
- Error handling: frontend's 401/403 interceptor behavior must match backend's
  JWT error responses
- Rate limit headers: frontend must read the same X-RateLimit-* headers the
  backend sends
- OAuth providers: frontend's OAuth buttons/callbacks must match backend's
  /auth/oauth/* routes
- Environment variables: document which backend PHOVEU_* variables correspond to
  which frontend VITE_* variables

### Architecture docs at {TARGET_PATH}/

- **CLAUDE.md** — full-stack architecture context (backend layer rules, frontend
  module rules, composition root pattern, API client pattern, every infrastructure
  pattern discovered, config checklist for BOTH backend and frontend, known issues,
  architectural strengths, backend↔frontend contract sync points)
- **ARCHITECTURE_BLUEPRINT.md** — code examples for every layer in both backend
  and frontend
- **DOMAIN_MODEL_EXPORT.md** — base entities (auth, billing, RBAC, tickets,
  config, hooks) with all relationships, indexes, business rules, and their
  corresponding frontend TypeScript types
- **LESSONS_LEARNED.md** — architectural decisions, anti-patterns found,
  patterns that proved valuable, known issues discovered in the scan

---

## Rules

- Do NOT hardcode which files or packages exist. Discover everything dynamically.
- Do NOT teach how to write code. Export architecture, practices, mistakes, strengths.
- Infrastructure is copied exactly. Domain logic is genericized as examples.
- Use parallel agents — one per discovered top-level package minimum, for BOTH
  backend and frontend simultaneously.
- Preserve every pattern found — the goal is 100% architectural replication.
- Backend and frontend must be contract-synced — types, routes, env vars, auth flow.
- Both .env.example files must be complete with every variable discovered.

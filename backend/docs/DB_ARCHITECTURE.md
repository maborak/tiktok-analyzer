# Database Architecture

This document describes the database layer for the TikTok-bot fork of
the Phoveus framework — its physical shape, the access patterns built
on top, the read/write strategy, the caching tiers, and the reasons
behind each decision. Last revised 2026-05-14.

For TikTok-specific data flow see `EVENTS_LOGGER.md`. For the
listener-pool process model see `WORKER.md`.

---

## 1. Engine + connection layout

### 1.1 Two engines (read-replica routing)

The framework supports an OPTIONAL read replica via the
`DB_USE_REPLICA_ENGINE` config flag. When enabled:

| Engine | Role |
|---|---|
| **Write engine** | Connects to the primary. All UPDATEs, INSERTs, DDL, and DDL-equivalent advisory locks go here. |
| **Read engine** | Connects to a replica DSN if configured (`DB_REPLICA_URL`), otherwise reuses the write DSN. Bulk SELECT-only paths (aggregations, list pages, exports) route here. |

The routing decision is per-session, not per-statement. Code that
needs replica routing wraps its work in `with get_routing_session() as s`
which picks the engine based on the operation about to happen.

Pool config keys (env-bootstrapped, refuse runtime mutation):
- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE` — primary
- `DB_REPLICA_POOL_SIZE`, `DB_REPLICA_MAX_OVERFLOW` — replica

`utils/database/database_session.py` owns the engine factories +
session makers. Adapters never construct engines themselves; they
call `get_routing_session_maker()` or `get_write_engine()`.

### 1.2 Why two engines?

Pros:
- Bulk read paths (the TikTok lives bundle, the events search page,
  the matches list) can use a stale-tolerant replica without contending
  with the write-heavy event-persist transaction pool.
- Pgbouncer in transaction-pooling mode behaves differently against
  the two; routing through distinct DSNs lets us tune
  `transaction_pool_size` independently.

Cons:
- Replica lag must be ≤ a few seconds for the read paths that
  immediately follow a write (e.g. "create subscription → list it").
  We don't currently enforce this — we trust the operator's deployment.
- Connection complexity doubles. Two pools means two failure modes.
- Architectural violation risk: a careless adapter could `session.add`
  on a read-routed session and the write would land on the replica
  (which would fail). The routing-session abstraction guards against
  this by binding each session to its intended role.

---

## 2. Hexagonal layering

### 2.1 The contract

```
routes/        ──depends on──▶  domain/services/  ──depends on──▶  ports/
                                                                       ▲
                                                                       │
                                                                       │ implements
                                                                       │
                                                            adapters/persistence/
```

- **Routes** (`routes/`) are FastAPI APIRouter modules. They depend
  on **services** + **ports** for type hints. They never import
  `adapters.*` or `database.*` directly.
- **Domain services** (`domain/services/`) contain business logic.
  They depend on **port ABCs** (`ports/`), never on adapters.
- **Ports** (`ports/`) are ABCs defining the contracts the service
  needs. One port per concern (auth, persistence, billing, etc.).
- **Adapters** (`adapters/`) implement ports. They're the only
  layer that talks to `sqlalchemy`, `redis`, HTTP, etc.

### 2.2 Why hexagonal?

Pros:
- Tests can swap real adapters for in-memory fakes by satisfying the
  port ABC. The service code doesn't need to know.
- Migrating a port to a new backing store (e.g., Postgres → Redis,
  RDBMS → embedded SQLite) is local to one adapter file.
- The dependency direction is one-way: domain knows nothing about
  the framework. Refactor risk is bounded.

Cons:
- Boilerplate per concern (port + adapter + DI wiring per service).
- Multiple-DI-touch-points: adding a service requires changes in
  `initialize_services()`, `setup_routes()`, and
  `set_dependencies()`. Forget any of the three → route returns 503
  because the module global is `None`.

### 2.3 Known violations

The `tiktok_service.py` has 6 lazy adapter imports inside method
bodies (line 340, 928, 1080, 1657, 1751, 1978) — `_apply_sign_globals`,
`gap_tracker`, `fetch_public_profile`, etc. These are documented in
`.claude/tracking/OPEN_ISSUES.md` as `ARC-2 — Domain services import
adapters directly`. The fix shape: extract `TikTokSignEnginePort`,
`TikTokOffsetTrackerPort`, `TikTokProfileScraperPort` and inject
through `initialize_services()`. Deferred; lazy imports limit the
blast radius.

`routes/admin/security.py:13` directly imports
`database.auth.models.User`, and `routes/user/account/oauth.py:169`
imports `database.auth.utils` (lazy). These are tracked as ARC-1.

---

## 3. Schema layout (TikTok module)

The TikTok module owns 9 tables under the `tiktok_*` prefix
(declared in `backend/database/tiktok/models.py`). The framework owns
the rest (`users`, `user_sessions`, `app_config`, `notifications`,
`rbac_*`, billing tables, etc.).

### 3.1 Inventory

| Model | Table | Purpose |
|---|---|---|
| `WorkerModel` | `tiktok_workers` | One row per listener worker process. UNIQUE `worker_key`, heartbeat, capacity, status. |
| `WorkerLogModel` | `tiktok_worker_log` | Append-only audit trail — startup, session_start, session_terminal, session_reconnect, etc. |
| `SubscriptionModel` | `tiktok_subscriptions` | Tracked TikTok creators (`@handle`). Carries `is_live`, `live_checked_at`, `assigned_worker_id`, `assignment_lease_until`, `is_public`, profile fields. |
| `RoomModel` | `tiktok_rooms` | One row per live broadcast. `room_id` (TikTok's 64-bit id), `host_unique_id`, `first_seen_at`, `last_seen_at`, `ended_at`. |
| `TikTokViewerModel` | `tiktok_viewers` | Every TikTok user we've ever seen — gifters, commenters, joiners. `user_id` (TikTok's 64-bit), `unique_id`, `nickname`, `avatar_url`. |
| `TikTokGiftModel` | `tiktok_gifts` | Gift catalog (TikTok's static gift IDs → names → diamond values). Seeded on startup. |
| `TikTokMatchModel` | `tiktok_matches` | One row per PK battle. Has `opponents`, `winning_team`, `started_at`, `ended_at`, score columns. |
| `TikTokEventModel` | `tiktok_events` | Every event from every live (gift, comment, like, join, follow, share, viewer, envelope, match_*, ...). The fact table. |
| `TikTokEventHourCountModel` | `tiktok_event_hour_counts` | Pre-aggregated count+diamonds per (host, hour). Bumped inline by the persist path. |

There's also `tiktok_user_host_summary` (cross-session ledger per
gifter × host) — defined in a migration, not currently mapped as a
SQLAlchemy model. The persist path writes it via raw SQL.

### 3.2 Hot tables — what makes them hot

**`tiktok_events`** — write-heavy. Every gift/comment/like/etc. inserts
a row. At peak (popular creator going live with active gifting), one
host can produce 50-100 events/sec. With ~10-15 concurrent active
lives, the table grows by ~1M rows/day.

Indexes:
- `(room_id, type)` — covers room-scoped event-type aggregations.
- `(room_id, ts)` — covers room-scoped time-window queries.
- `(room_id, type, ts DESC)` (Phase 9.3) — strict superset of the
  two above, lets time-bucketed queries stop scanning at the boundary.
- `(type, ts DESC)` — covers cross-host event-type filters.
- `(user_id, room_id, type, ts DESC)` — covers user-scoped gift
  aggregations (the user-host leaderboard).
- Partial unique index on `(room_id, message_id) WHERE message_id IS NOT NULL`
  — dedup for TikTokLive's WS reconnect cursor replay.

**`tiktok_rooms`** — read-heavy. Every list-page query joins to it.
At ~5K rooms across all history, the table itself is small, but the
join fan-out from events is significant.

Indexes added in Phase 9.3 (`add_tiktok_lives_summary_indexes.py`):
- Partial `(host_unique_id, last_seen_at DESC) WHERE ended_at IS NULL`
  — currently-active rooms only.
- `(host_unique_id, first_seen_at DESC NULLS LAST)` — last-broadcasts
  window function can walk in order.

**`tiktok_subscriptions`** — small (~80 rows) but read-heavy. Every
admin page hits it. Cached at the service layer.

**`tiktok_event_hour_counts`** — pre-agg (≤79 hosts × 25 hours = ~2K
rows). Phase 9 added a `diamonds` column so `get_lives_totals` reads
this instead of scanning gift events.

**`tiktok_user_host_summary`** — grows linearly with distinct
(gifter × host) pairs. PK on `(user_id, host_unique_id)`. Read by the
"first-time gifter this session" check.

---

## 4. Migration strategy

### 4.1 Idempotent scripts, no Alembic

Migrations live in `backend/database/migrations/` (45+ files as of
2026-05-14). Each is a top-level Python script using
`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE … IF NOT EXISTS` /
`CREATE INDEX IF NOT EXISTS`. There's no central version table, no
Alembic, no auto-generated diffs.

The runner is the migration script itself — operators invoke it
directly: `python database/migrations/add_event_hour_counts_diamonds.py`.
The migration prints what it did + skips no-ops.

### 4.2 Why no Alembic?

Pros of the current approach:
- Re-running a migration is safe (idempotent) — no "version mismatch"
  fights when two operators land changes in different orders.
- Migration is "just a Python script" — same patterns as the rest of
  the codebase, easy to dry-run, easy to grep for.
- No `alembic env.py` boilerplate; no autogenerated noise.
- Operator can hot-fix a botched migration by editing the script.
- Multi-app deployments (multiple Phoveus forks sharing one DB via
  the `get_table_name("…")` namespace prefix) don't need separate
  Alembic histories.

Cons:
- No formal version history. To know "what's been applied here," you
  inspect the schema, not a metadata table.
- Down migrations don't exist. Rollback = manual SQL.
- Test migrations in isolation is harder — no easy way to "run
  everything up to migration N" automatically.
- For SQLite vs Postgres divergence, each migration carries its own
  branching. Some are Postgres-only and no-op on SQLite by design.

### 4.3 Branch-on-dialect

Postgres-only features (`CREATE INDEX CONCURRENTLY`, partial expression
indexes, JSONB ops, advisory locks, `INSERT ... ON CONFLICT`) are
guarded:

```python
if engine.dialect.name != "postgresql":
    logger.info("migration X: dialect=%s — skipping (Postgres only).",
                engine.dialect.name)
    return
```

SQLite stays usable as a dev path for the framework's auth/billing/
tickets surface. The TikTok module is functionally Postgres-only —
`get_lives_summary` short-circuits with empty results on SQLite. This
is intentional: production deployments are Postgres; SQLite is for
fast-iteration auth flow work where the TikTok module isn't exercised.

### 4.4 Notable migrations

| File | What it does |
|---|---|
| `add_tiktok_tables.py` | The base schema — subscriptions, rooms, events, gifts, viewers, matches. |
| `add_tiktok_worker_registry.py` | Workers table + assignment columns on subscriptions. |
| `add_event_hour_counts.py` | The hourly pre-agg table + initial backfill. |
| `add_event_hour_counts_diamonds.py` | Phase 9 — `diamonds` column on the pre-agg; lets `get_lives_totals` skip the JSONB heap walk. |
| `add_user_host_summary.py` | Cross-session ledger for "first-time gifter" detection. |
| `optimize_tiktok_indexes.py` | Dropped 2 zero-scan indexes; added the user-room-type-ts composite. |
| `add_tiktok_lives_summary_indexes.py` | Phase 9 — 4 new indexes (rooms partial-active, rooms first_seen, events room+type+ts, worker_log JSONB host). |
| `tz_aware_tiktok_timestamps.py` | Bulk ALTER to timestamptz for the TikTok module. |
| `dedupe_existing_events.py` | One-time DELETE of duplicate events introduced before the (room_id, message_id) unique index. |

---

## 5. Caching tiers

The DB is the source of truth. Above it sit four cache layers, each
with a different invalidation strategy.

### 5.1 Service-layer TTL caches

`tiktok_service.py` holds two cache dicts:

```python
_LIVES_SUMMARY_TTL_S = 60.0     # bumped from 35s in Phase 7
_lives_summary_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_lives_summary_locks: dict[tuple[str, ...], threading.Lock] = {}
_lives_summary_meta_lock = threading.Lock()

_LIVES_TOTALS_TTL_S = 60.0
_lives_totals_cache: tuple[float, dict[str, Any]] | None = None
_lives_totals_lock = threading.Lock()
```

**Pattern**: read → check TTL → return cached or grab per-key lock
→ double-checked read → SQL fan-out → populate cache.

Single-flight on cold miss: when N concurrent callers race for the
same key, only one runs the SQL; the rest block on the lock then
read the now-populated cache. Critical during startup when the
framework's warmup task + the first user request collide.

### 5.2 Pre-aggregation tables

The `tiktok_event_hour_counts` table is a write-time pre-agg. Every
`record_event` call inline-bumps the (host, current-hour) row's
`n` counter and (for gift events) the `diamonds` column. The
read path then reads ≤2K rows instead of scanning millions of events.

Trade-off:
- Pro: read paths become PK lookups; the `get_lives_totals` 24h
  diamond sum used to do a multi-million-row JSONB heap walk, now
  it's `SUM(diamonds) FROM tiktok_event_hour_counts WHERE hour_bucket > NOW() - 24h`.
- Con: write amplification. Each event = 1 INSERT to `tiktok_events`
  + 1 UPSERT to `tiktok_event_hour_counts` + 1 UPSERT to
  `tiktok_user_host_summary`. The persist path is now 3-4 writes
  per event.

### 5.3 Phase 9 state cache

A per-host runtime cache, keyed by handle, holding the same shape
`get_lives_summary` returns. Two adapters:

- `TikTokStateCacheInProc` — `dict + threading.Lock` (in-process
  mode).
- `TikTokStateCacheRedis` — `tiktok:lives:state:<handle>` JSON blob
  + `tiktok:lives:version:<handle>` counter (worker mode, shared
  across processes).

Mutated by the persist path on every event (Phase 9B). Read by the
bundle endpoint (Phase 9C overlay) and forwarded to WS clients
(Phase 9D delta channel). Mirrors a subset of `get_lives_summary`
fields — `_CACHE_OVERLAY_FIELDS` in `tiktok_service.py` enumerates
which fields are owned by the cache vs which stay SQL-driven.

### 5.4 RBAC token cache

`AuthPersistenceAdapter` caches `AuthContext` objects keyed by
`SHA256(token | ip | ua)`, 30s TTL. Saves 3-4 DB roundtrips per
authenticated request after the first hit. Added in Phase 9.6.

### 5.5 Cache hierarchy summary

```
                ┌───────────────────────────────┐
                │   Request from FastAPI route  │
                └────────────────┬──────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │   RBAC token cache (Phase 9.6)      │ 30s TTL
              │   key: SHA256(token|ip|ua)          │
              └──────────────────┬──────────────────┘
                                 │ pass
              ┌──────────────────▼──────────────────┐
              │   Service-layer TTL caches          │ 60s TTL
              │   - lives_summary by handle-set     │
              │   - lives_totals (single slot)      │
              └──────────────────┬──────────────────┘
                                 │ miss
              ┌──────────────────▼──────────────────┐
              │   State cache (Phase 9, Redis/inproc)│ event-driven
              │   - per-host JSON blob              │
              │   - per-host monotonic version      │
              │   - Overlay on top of SQL output    │
              └──────────────────┬──────────────────┘
                                 │ miss/SQL
              ┌──────────────────▼──────────────────┐
              │   Pre-aggregation tables (event-     │ write-time
              │   driven UPSERT per event)          │
              │   - tiktok_event_hour_counts        │
              │   - tiktok_user_host_summary        │
              └──────────────────┬──────────────────┘
                                 │ miss / scan
              ┌──────────────────▼──────────────────┐
              │   Postgres (write engine + replica) │
              └─────────────────────────────────────┘
```

---

## 6. Read patterns + indexing strategy

### 6.1 Hot read: the lives-list bundle

`GET /admin/tiktok/lives/bundle` is polled every 30s by the admin
Lives page. Phase 7 collapsed three endpoints into this one.

Call graph:

```
get_lives_bundle()
├── list_subscriptions()           — single SELECT, no joins, ~80 rows
├── asyncio.gather(
│     get_lives_summary(handles)   — service cache (60s TTL)
│     get_lives_totals()           — service cache (60s TTL)
│   )
│
└── overlay state cache on the SQL result, attach per-host `version`
```

When both service caches hit warm, the wall-clock is ~17 ms p50.
Cold mount (cache empty) is ~800 ms.

### 6.2 The SQL fan-out (cold path)

`get_lives_summary` runs ~16 persistence helpers in two phases via a
`ThreadPoolExecutor(max_workers=8)` against the connection pool.
Phase 0 helpers race; Phase 1 helpers wait on the anchor (the active-
rooms list) then race.

Helpers + their cost (~700 ms total cold):

| Helper | Phase | Cost | What it computes |
|---|---|---|---|
| `_lives_summary_active_rooms` | 0 (anchor) | small | currently-active rooms per host |
| `_daily_buckets_cached` | 0 | <1 ms | 24h event counts (reads pre-agg) |
| `_week_calendar_cached` | 0 | ~250 ms | 7-day per-day rollup (60s TTL) |
| `_lives_summary_hourly` | 0 | ~100 ms | last 60min diamonds per minute |
| `_lives_summary_last_broadcasts` | 0 | ~80 ms | last 3 rooms per host |
| `_lives_summary_30d_averages` | 0 | ~150 ms | 30-day avg duration/diamonds |
| `_lives_summary_reconnects` | 0 | ~10 ms | reconnects last hour per host |
| `_lives_summary_top_gifters` | 1 | ~50 ms | top 3 gifters in active room |
| `_lives_summary_unique_and_session_stats` | 1 | ~80 ms | unique gifters + scoreboard counters |
| `_lives_summary_viewer_counts` | 1 | ~30 ms | viewer count + history |
| `_lives_summary_active_match` | 1 | ~5 ms | current PK if any |
| `_lives_summary_median_diamonds` | 1 | ~100 ms | 30-day median for vs-typical chip |

### 6.3 Index coverage

After Phase 9.3 the call graph is well-covered. The remaining heavy
queries are `_week_calendar_cached` and `_lives_summary_30d_averages`
— both scan gift events over a 7-30 day window. The pre-agg path
(extending `tiktok_event_hour_counts` to also serve weekly/monthly)
is the next-frontier optimization.

---

## 7. Write paths

### 7.1 Event persistence

The hot write path is `persist_event_full(room_id, host_unique_id, viewer, type, payload)`
(`tiktok_persistence.py:2067`). Single transaction:

1. Upsert `tiktok_rooms` row (room metadata, `last_seen_at` bump).
2. Upsert `tiktok_viewers` row (viewer identity + last-seen).
3. Insert `tiktok_events` row (or skip via ON CONFLICT if
   `(room_id, message_id)` already present).
4. Upsert `tiktok_user_host_summary` (diamond accumulation +
   first/last-seen update).
5. Bump `tiktok_event_hour_counts` (count + diamonds for the current
   hour).
6. (Phase 9B) Apply state-cache delta — publishes a delta to admin +
   public WS channels.

All five DB writes commit atomically. If any fails, the event is
rolled back; the WS broadcast doesn't fire (the listener catches the
exception, logs it, continues to the next event).

Cost: ~5-10 ms per event on warm DB, ~30-50 ms cold. At 100 events/sec
peak (popular creator), the persist pool stays at ~50% utilization.

### 7.2 Why `INSERT ... ON CONFLICT` over MERGE?

Pros:
- Postgres-native, fast, atomic per row.
- The partial unique index on `(room_id, message_id) WHERE message_id IS NOT NULL`
  is the dedup key. Events lacking `message_id` (synthetic events:
  `connect`, `disconnect`, `live_end`) skip the dedup and always insert
  — they're guaranteed unique by lifecycle.

Cons:
- No portable equivalent on SQLite. We branch (`if self._is_postgres():`
  for the upsert path, fallback to query-then-insert on SQLite).
- ON CONFLICT requires that the inferred index match the partial-
  index predicate exactly; mismatch → silent failure to use the
  unique index. Phase 7 caught one such case in `_bump_event_hour_count`
  before it shipped.

### 7.3 Listener worker writes

The listener worker process (`cli system tiktok run-listener`) writes
to:
- `tiktok_workers` — heartbeat row every 5s, `desired_status` /
  `command` polling for admin control signals.
- `tiktok_subscriptions.assigned_worker_id` + `assignment_lease_until`
  — lease-based assignment (renewed every 60s; stolen if expired).
- `tiktok_subscriptions.is_live` / `live_checked_at` — central live-
  status probe writes here so supervisors don't each hammer TikTok.
- `tiktok_worker_log` — append-only audit trail.

See `WORKER.md` for the full coordination model.

---

## 8. Failure modes + recovery

### 8.1 Postgres unavailability

The framework uses `utils/database/resilience.py:retry_db_operation`
to retry on `OperationalError` with exponential backoff. Persistence
adapters wrap critical paths in this decorator.

If the DB stays down past the retry window:
- Service layer raises `OperationalError`.
- Route handlers catch and return 503.
- Listener worker's event-persist path logs + drops the event (the
  WS broadcast still proceeds — Redis-backed listeners get the event
  even if DB write failed).
- State cache (Phase 9, in-process variant) keeps working; Redis
  variant degrades if Redis is also down.

### 8.2 Connection pool exhaustion

Symptoms: requests time out at `QueuePool limit of size X overflow Y reached`.
Mitigations:
- The TikTokService has THREE executor pools to prevent starvation:
  `_control_executor` (1 thread, heartbeat/control DB calls),
  `_event_executor` (4 threads, event persistence),
  default loop executor (everything else).
- The 8-thread ThreadPoolExecutor in `get_lives_summary` is sized
  to match (default pool 20, replica 20 — leaves headroom for
  concurrent requests).
- The 4 indexes added in Phase 9.3 reduce per-query lock time,
  cycling connections faster.

### 8.3 Replica lag

Currently unenforced. If `DB_USE_REPLICA_ENGINE=true` and the replica
lags > 5s, a "create subscription → list it" flow would briefly show
the new sub missing. Production deployments using replicas should
either:
- Use synchronous replication for the writer DSN, OR
- Route post-write reads through the write engine (the current
  routing-session helper already does this for some paths but not
  uniformly).

---

## 9. Future plans

### 9.1 Already planned (Phase 9 ongoing)

- **Phase 9.E** — Frontend WS-pushed state replaces polling. Cache
  becomes the steady-state source; SQL fan-out is the cold-start
  path only.
- **Phase 9.F** — Remove the service-layer TTL caches once Phase E
  is stable. Their only role today is absorbing the 30s poll cadence;
  with WS push that cadence is gone.

### 9.2 Backlogged items

| Item | Why | Where |
|---|---|---|
| Per-room pre-agg table | The 30-day averages still scan gift events. A `tiktok_room_summary` row per room (gifts, comments, diamonds, peak_viewers) would drop those scans to ≤79×30 = ~2,400 rows. | Memory: in `.claude/memory/MEMORY.md` Remaining Work. |
| Token cache reverse-index | RBAC cache invalidation on logout is currently TTL-only. A `session_id → set[cache_key]` reverse index would make logout instant. | Tracked in Phase 9.6 commit. |
| Architectural cleanup | The 6 lazy `adapters.*` imports in `tiktok_service.py` should become proper port abstractions. | `.claude/tracking/OPEN_ISSUES.md` ARC-2. |
| `routes/admin/security.py:13` direct DB import | Single use of `UserModel`; should be reached through `auth_service`. | OPEN_ISSUES.md ARC-1. |
| Replica lag enforcement | A `read_after_write_sync` helper that briefly routes reads through the writer after a write commits. | Not yet a real issue at our scale; flag if it bites in prod. |

### 9.3 Speculative — would consider but not committed

- **TimescaleDB hypertables for `tiktok_events`**. The events table
  is fundamentally time-series. Hypertables would auto-partition by
  time, improve range-query plans, and make retention policies
  trivial. Cost: dialect-specific, harder ops, breaks the "Postgres
  is Postgres" assumption.
- **Per-host event stream sharding**. At 10× current scale, a single
  `tiktok_events` table becomes a bottleneck. Postgres declarative
  partitioning by `host_unique_id` is the natural next step.
- **Move event ingestion to Kafka**. Decouple WS event capture from
  DB write. Lets us replay, do parallel consumers (Postgres writer +
  analytics writer + state-cache writer), and survive DB outages.
  Substantial complexity; only justified at significantly higher
  event volume than today's.

---

## 10. References

- `backend/adapters/persistence/_base.py` — `BasePersistenceAdapter`.
- `backend/adapters/persistence/tiktok_persistence.py` — TikTok module
  adapter; ~6000 lines; the lions share of the DB code.
- `backend/database/tiktok/models.py` — SQLAlchemy models.
- `backend/database/migrations/` — 45+ idempotent scripts.
- `backend/utils/database/database_session.py` — engine factories +
  session makers.
- `backend/utils/database/resilience.py` — retry decorator.
- `.claude/tracking/perf/REPORT.md` — Phase 1–8 perf history (warm
  poll 23 → 14 ms, cold mount 1135 → 818 ms, payload 264 → 199 KB).
- `.claude/tracking/perf/PHASE9_PLAN.md` — Phase 9 detailed plan.
- `.claude/tracking/OPEN_ISSUES.md` — known architectural / security
  issues.

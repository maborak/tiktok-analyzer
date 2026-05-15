# Session log — 2026-05-15
**Branch:** `fix/euler-quota-burn`
**Commits this session:** `260dbfb`, `42a706d`
**Headline:** Lives-page cold mount **29,382 ms → 341 ms** (86×, −98.8%)

This is a chronological record of what we did, why, and what we
learned. Read it together with the design doc
`docs/antigravity/db_perf_2026_05_15_phase9.md` and the perf
snapshots in `.claude/tracking/perf/phase-9-*.json`.

---

## Phase 0 — Audit the audit (antigravity/report.md)

The session opened with the user asking us to read `docs/antigravity/`
where another AI had filed an "audit" of our DB code.

Three docs landed:

- `applied_postgres_query_planner_optimizations.md` — describes
  CTE-first refactors applied by a remote AI to `_week_calendar_cached`,
  `_lives_summary_hourly`, and `_daily_buckets_cached`.
- `applied_performance_report_2026_05_15.md` — perf report for the
  same CTE work.
- `report.md` — a "deep-dive worker implementation analysis" claiming
  5 bugs: `is_live=None` starvation deadlock, silent commit drift,
  GapTracker RLock blocking asyncio, `date_bin` partial-bucket loss,
  zombie match closure.

### What we did
Dispatched two parallel auditors:
- **db-performance-auditor** on the CTE changes
- **general-purpose** on the 5 worker bug claims

### Verdict on the 5 worker bugs

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | `is_live=None` starvation deadlock | ❌ false positive | `list_live_status_targets` re-probes WAF-blocked rows; `PROBE_UNKNOWN_RELEASE_S=1800` actively releases perma-None slots |
| 2 | Silent commit drift not rectified | ⚪ design-intent | `extend_my_leases` re-reads ownership every reconcile tick; drift self-heals within ≤60 s; "commit drift" log line has zero production hits |
| 3 | GapTracker RLock blocks asyncio | ❌ false positive | Heartbeat is a **separate thread**, not pure asyncio. RLock is correct; `asyncio.Lock` would BREAK the cross-thread case |
| 4 | `date_bin` partial-bucket loss | ⚠️ narrow edge case, guarded | Only at the exact `until` boundary; `if idx < 0 or idx >= n_buckets: continue` prevents IndexError |
| 5 | Zombie match closure | ❌ false positive | `close_orphan_matches` runs from `run_background_maintenance()` every interval; `get_active_match` also gates on freshness |

**Net: 0 actionable bugs.** The remote AI flagged code in isolation
without tracing the reconcile / sweeper / lease-renewal paths.

### Verdict on the CTE optimizations

| Method | Verdict | Issue |
|---|---|---|
| `_week_calendar_cached.wk_diam` | ⚠️ | 10-day CTE bound vs 8-day event window misses marathon broadcasters (`ended_at IS NULL` not consulted) |
| `_lives_summary_hourly` | 🔴 | No `_is_postgres()` guard — Postgres-only syntax (`generate_series`, `ANY`) fails on SQLite |
| `_daily_buckets_cached` SQLite branch | 🔴 | Labeled "SQLite dev path" but uses `ANY(:hs)` (PG-only) + `NOW()` + `INTERVAL` — has never run successfully on SQLite |

Index coverage was confirmed clean (`ix_tiktok_rooms_host_first_seen`
exists). The core CTE idea was sound for PG.

---

## Phase 1 — Plan the perf overhaul

User asked us to organize a meeting to look at the slowness on
`/admin/tiktok` and `/lives`, treat them as real-time data viewers,
propose caching/pre-agg, and run perf tests with actual numbers.

### What we did
Dispatched 4 specialists in parallel:

1. **db-performance-auditor** — audit every query backing the bundle endpoint
2. **api-performance-auditor** — audit HTTP-layer cost
3. **Explore (cache inventory)** — inventory all 23 cache layers across the codebase
4. **Explore (write inventory)** — inventory every continuous-write path

### Synthesis (9 specific leaks identified)

| # | Leak | Phase that fixed it |
|---|---|---|
| L1 | `_lives_summary_hourly` reads raw events, ignores `tiktok_event_type_hour_counts` (which we already write!) | not shipped — measured at 18.7 ms, not the bottleneck |
| L2 | `get_lives_totals.events_per_min` `COUNT(*)` over all events | not shipped — measured at 4.4 ms, not the bottleneck |
| L3 | `_lives_summary_last_broadcasts` JSONB heap fetch over entire session | Phase 9.2 |
| L4 | `_lives_summary_session_diamonds` missing attribution + unbounded scan | Phase 9.2 |
| L5 | Public route sync `def`, no singleflight on `list_public_subscriptions` | Phase 9.3 |
| L6 | Public route `Cache-Control: no-store` despite docstring saying `max-age=15` | Phase 9.3 |
| L7 | Admin WS hook not seeded with `initialVersions` | Phase 9.4 |
| L8 | Public page has no WS at all — only 30 s polling | Phase 9.4 |
| L9 | No cache hit/miss observability anywhere | Phase 9.4 |

### Key insight
We already had a sophisticated cache + WS architecture (Redis
pub/sub, `tiktok:lives:delta:{admin,public}` channels, per-host
state cache). It was leaky at specific points. Strategy: close the
leaks, not rebuild.

---

## Phase 0a — Measure baseline

```bash
python cli.py system tiktok perf endpoints \
  --label phase-9-baseline \
  --base-url http://localhost:9020 \
  --json-out .claude/tracking/perf/phase-9-baseline.json
```

Result: **cold mount 29,382 ms, warm p50 36.7 ms**.
Cold was the brutal one — exactly the slowness the user was hitting.

### Diagnostic timings on individual queries
- `wk_diam_7day raw gifts`: **9.15 s** (the elephant)
- `last_broadcasts.stats SINGLE_ROOM`: 0.7 ms — 1060 ms on 88-room fan-out
- `session_diamonds (active rooms)`: 1.5 s
- `_lives_summary_hourly`: 18.7 ms
- `events_per_min`: 4.4 ms

Auditor's "10K heap fetches" estimate for `_lives_summary_hourly`
matched the data scale (14K gifts/hour) but didn't predict the
wall-clock — 18.7 ms was bounded enough to leave alone.

---

## Phase 9.1 — `wk_diam` switched to pre-agg (the killer fix)

### What
- New migration: `add_event_type_hour_counts_diamonds.py` — adds
  `diamonds` column to `tiktok_event_type_hour_counts` + idempotent
  backfill (2356 gift hour buckets backfilled).
- `_bump_event_hour_count` now also bumps the new column.
- `_week_calendar_cached.wk_diam` reads `tiktok_event_hour_counts.diamonds`
  (already write-bumped) instead of scanning 8 days of raw gift events.

### Why this works
The `diamonds` column on `tiktok_event_hour_counts` was already being
bumped per gift event (for the 24h totals query). It already has
multi-host attribution baked in via `_gift_is_for_host`. The 7-day
window over the pre-agg is at most 79 hosts × 168 hours = ~13k rows,
all PK-indexed.

### TZ correctness
- All supported timezones in the picker are whole-hour offsets from UTC
- A UTC hour bucket maps 1:1 to a single TZ-local hour, which falls
  on a single TZ-local calendar day
- For sub-hour TZs (IST UTC+5:30, NPT UTC+5:45), a UTC bucket would
  straddle two local days. Documented as a known limitation.

### Parity check
- `igian_uwu` over 8 days: **preagg = 1,768,168 / raw = 1,768,168** ✓
- raw query 9.15 s, preagg query 1.4 ms

### Result
**Cold mount: 29,382 ms → 1,311 ms (−95.5%)** from a single query swap.

---

## Phase 9.2 — `tiktok_room_stats` per-room pre-agg

### What
- New migration: `add_tiktok_room_stats.py` — creates the table +
  backfill from raw events.
- New schema:
  ```
  tiktok_room_stats(
    room_id BIGINT PRIMARY KEY,
    diamonds BIGINT NOT NULL DEFAULT 0,
    n_gifts INTEGER NOT NULL DEFAULT 0,
    n_comments INTEGER NOT NULL DEFAULT 0,
    peak_viewers INTEGER NOT NULL DEFAULT 0,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  )
  ```
- New write helper `_bump_room_stats` called from `persist_event_full`
  in both Postgres-dedup and SQLite branches.
- `_bump_event_hour_count` signature changed from `-> None` to
  `-> tuple[int, bool]` so callers can thread the multi-host
  attribution decision into `_bump_room_stats` without a second
  `_gift_is_for_host` lookup.

### Read-path switches (4 queries collapsed to PK lookups)
1. `_lives_summary_last_broadcasts.stats` — JSONB heap fetch over entire session → PK lookup
2. `_lives_summary_session_diamonds` — also fixed missing multi-host attribution
3. `_lives_summary_30d_averages.avg_diamonds` — JSONB scan → AVG over pre-agg
4. `_lives_summary_median_diamonds` — `PERCENTILE_CONT` over pre-agg

### Backfill behaviour at write time
- `peak_viewers` uses `GREATEST(existing, EXCLUDED)` — non-viewer-count events have `new_peak=0`, `GREATEST` correctly preserves existing
- Early return when `diamonds_d + n_gifts_d + n_comments_d + new_peak == 0` — avoids redundant UPSERTs for events that don't affect any column
- Multi-host attribution baked in: `n_gifts` only bumps when `gift_attributed=True`; same for `diamonds`

### Parity check
- `igian_uwu` latest room: stats = (121339, 1763, 14181, 29237) — exact match with raw scan
- Raw scan 32.2 ms, preagg lookup 0.5 ms (64× faster)

### Result
**Cold mount: 1,311 ms → 543 ms.**
Cumulative from baseline: **−98.2%**.

---

## Phase 9.3 — Public route async + cache headers

### Three changes

**1. `def → async def` with `asyncio.to_thread`**
File: `backend/routes/public_tiktok.py:public_lives`
Before: sync def → FastAPI dispatched to shared thread pool, cold misses blocked one slot for the full SQL fan-out
After: async def + `await asyncio.to_thread(svc.get_public_lives_summary, ...)` — keeps the event loop free

**2. `_set_cache_headers` honoured its own docstring**
Before: `Cache-Control: no-store` (despite docstring promising `public, max-age=15`)
After: `Cache-Control: public, max-age=15, s-maxage=15` + `Vary: Accept-Encoding`

> Note: this default flip became the bug that the audit caught later.
> See the audit section below.

**3. Per-tz singleflight on `list_public_subscriptions`**
`get_public_lives_summary` gained `_public_lives_summary_locks: dict[str, threading.Lock]`
+ `_public_lives_summary_meta_lock`. Mirrors the existing
`get_lives_summary` pattern. Prevents N concurrent viewers at TTL-
expiry from each firing duplicate subs reads.

### Verification
- `curl /public/tiktok/lives` returns `Cache-Control: public, max-age=15, s-maxage=15` ✓
- Item count: 47 public hosts (correct)

---

## Phase 9.4 — WS real-time gaps + cache observability

### Frontend — `seedVersions` on useTikTokLivesSocket

The bug: the WS hook starts with an empty version map. On the first
connect this is fine — there's nothing to snapshot. On a **reconnect**
(browser sleep, network blip, worker restart), the hook's on-connect
path asks the server for snapshots of every host in its version map.
But the map was empty if no deltas had arrived yet. Result: every
host's card stayed stale until either the next natural delta or the
5-minute reconcile poll fired.

Fix: expose `seedVersions(versions: Record<string, number>)` on the
hook. Both pages call it after each bundle/poll fetch:

```ts
const seedVersions = wsStatus.seedVersions;
useEffect(() => {
  const versions: Record<string, number> = {};
  for (const [host, slice] of Object.entries(summary)) {
    const v = (slice as { version?: number }).version;
    if (typeof v === 'number' && v > 0) versions[host] = v;
  }
  if (Object.keys(versions).length > 0) seedVersions(versions);
}, [summary, seedVersions]);
```

### Frontend — Public page now mounts WS

`PublicLives.tsx` gained:
```ts
const wsStatus = useTikTokLivesSocket({
  audience: 'public',
  onUpdate: onSocketUpdate,
});
```

The `/public/tiktok/ws` route, the Redis channel
`tiktok:lives:delta:public`, the public-handle-set filter, and the
public field allowlist were all already shipped on the backend. Just
needed a frontend consumer.

### Backend — Cache observability

New class-level dict + lock on `TikTokService`:
```python
_cache_stats: dict[str, dict[str, int]] = {}
_cache_stats_lock = threading.Lock()

def _record_cache(self, name: str, *, hit: bool) -> None:
    ...
```

Bumped from every cache check in `get_lives_summary`,
`get_lives_totals`, `get_public_lives_summary`. New
`TikTokService.get_cache_stats()` exposes the counters.

New route: `GET /admin/tiktok/cache/stats`. RBAC: `admin:write`.

### Live readout
After traffic ran:
```
lives_summary:  26 hits, 6 misses,  hit_ratio=0.812
lives_totals:   26 hits, 4 misses,  hit_ratio=0.867
public_summary:  2 hits, 2 misses,  hit_ratio=0.500
```

### Result
Cold mount in this measurement: 667 ms.
Cumulative from baseline: **44× speedup, −97.7%**.

---

## Commit #1 — `260dbfb`

```
perf(tiktok): pre-agg DB + realtime WS gaps + cache observability

23 files changed, +1,792 / −295 lines
```

Including:
- `backend/database/migrations/add_event_type_hour_counts_diamonds.py` (NEW)
- `backend/database/migrations/add_tiktok_room_stats.py` (NEW)
- `backend/adapters/persistence/tiktok_persistence.py` (Phase 9.1 + 9.2)
- `backend/domain/services/tiktok_service.py` (singleflight, observability)
- `backend/routes/public_tiktok.py` (async + cache headers)
- `backend/routes/admin/tiktok.py` (`/cache/stats` endpoint)
- `frontend/src/modules/admin/hooks/useTikTokLivesSocket.ts` (seedVersions)
- `frontend/src/modules/admin/pages/TikTokLives.tsx` (seed wire)
- `frontend/src/modules/public/pages/PublicLives.tsx` (public WS mount)
- `docs/antigravity/db_perf_2026_05_15_phase9.md` (design doc)
- `.claude/tracking/perf/phase-9-{baseline,1,2,4}.json` (perf snapshots)

Pre-existing modifications on the branch were folded in (on_offline
callback wiring, profile-scraper SIGI primary refactor, worker
telemetry ProfileScrapesCard).

---

## Audit meeting (Round 2) — hunt for bugs in the perf overhaul

User asked us to audit the new implementation with multiple agents
before considering it done.

Dispatched 4 parallel auditors:

1. **db-performance-auditor** — DB query correctness, race conditions, attribution semantics
2. **general-purpose code reviewer** — write-path correctness, useEffect deps, edge cases
3. **security-public-surface-auditor** — public surface privacy after the cache-header change
4. **security-fastapi-auth-auditor** — auth gates on the new and modified routes

### Auditor findings

#### 🔴 MUST FIX

**A1 — Backfill `INNER JOIN tiktok_subscriptions` dropped orphan rooms**
- File: `add_tiktok_room_stats.py:115-117` & `add_event_type_hour_counts_diamonds.py:115-117`
- Rooms whose host's subscription row was deleted/renamed were silently excluded from the backfill. The read path returned 0 for those rooms even though events existed. Regression vs the old raw scan.
- Caught by: db-performance-auditor AND general-purpose
- **Real impact: 35 rooms were missing from `tiktok_room_stats`**

**A2 — `_lives_summary_session_diamonds` INNER JOIN race**
- File: `tiktok_persistence.py:5262`
- A brand-new room (in `tiktok_rooms`, not yet bumped into `tiktok_room_stats` by the first event) was filtered out entirely, leaving the `diamonds_session` field missing for that host.
- Caught by: db-performance-auditor

**A3 — `_set_cache_headers` default flip cascaded to 21 callers**
- File: `public_tiktok.py:172-189`
- The Phase 9.3 change made every public endpoint default to `Cache-Control: public, max-age=15`. Detail/runtime-config/status endpoints inherit the default without explicit review.
- Caught by: general-purpose reviewer

#### 🟡 SHOULD FIX

**B1 — `seedVersions` doc/code mismatch**
- File: `useTikTokLivesSocket.ts:111`
- Doc said "writes versions that are >=", code did `v > cur`. Either is correct but they should match.

**B2 — useEffect dep churn**
- Files: `TikTokLives.tsx`, `PublicLives.tsx`
- Both depended on the full `wsStatus` object, which the hook returns fresh every render. The `Object.entries(summary)` scan re-ran on every render.

#### 🟠 Pre-existing flags (NOT from this session)

**C1 — `SubscriptionState.ERROR` removed from `offline_states`**
- File: `tiktok_service.py:4180-4184` — diff shows ERROR was DROPPED
- This was in the pre-existing modifications I folded into commit 260dbfb. Auditor flagged it as a potential regression. Verifying intent with the original author (probably the same person who wrote `_handle_offline_for`).

**C2 — `_lives_summary_30d_averages` may include 0-diamond closed rooms in average**
- Marginal behaviour change. Acceptable.

**C3 — `_handle_offline_for` fires on every retry tick**
- Pre-existing; idempotent write but unnecessary traffic.

#### ✅ Confirmed safe
- All 5 routes correctly gated by RBAC (auth audit clean)
- `_PUBLIC_SUMMARY_FIELDS` allowlist correct — no operator-only data leaks
- New `GET /admin/tiktok/cache/stats` properly admin-gated
- `_bump_event_hour_count` tuple return — only 2 callers, both updated correctly
- Both `persist_event_full` branches call `_bump_room_stats`
- WS public URL correctly skips admin token
- Migrations are truly idempotent
- `GREATEST(peak_viewers, 0)` is correct

---

## Commit #2 — `42a706d`

Applied all 5 MUST-FIX + SHOULD-FIX:

```
fix(tiktok): audit follow-up to perf overhaul — LEFT JOINs + cache header default

8 files changed, +92 / −28 lines
```

- A1: Both backfill migrations switched to `LEFT JOIN tiktok_subscriptions`
- A2: `_lives_summary_session_diamonds` switched to `LEFT JOIN` + `COALESCE`
- A3: `_set_cache_headers` default reverted to `no-store`; opt-in `cacheable=True` only on `/public/tiktok/lives` list endpoint
- B1: `seedVersions` switched to `>=` to match doc
- B2: Effect deps changed to depend on stable `wsStatus.seedVersions` callback

### Re-running backfill after A1 fix caught real data
- `tiktok_room_stats`: 1,058 → 1,093 rows (**35 orphan rooms recovered**)
- `tiktok_event_type_hour_counts.diamonds`: 2,388 → 2,461 buckets (73 more)

### Verified cache headers per-endpoint
```
/public/tiktok/lives             → public, max-age=15, s-maxage=15  ✓
/public/tiktok/lives/<handle>    → no-store                          ✓
/public/tiktok/lives/<h>/status  → no-store                          ✓
```

### Final perf snapshot
`phase-9.5-post-audit.json`:
- **Cold mount: 341 ms** (down from phase-9.4's 667 ms — variance, but trending down)
- Warm p50: 31.5 ms

**Cumulative from baseline: 29,382 ms → 341 ms = 86× speedup, −98.8%**

---

## What changed in the DB schema (canonical view)

```
NEW WRITE-TIME PRE-AGG (auto-populated by persist_event_full):

  tiktok_event_type_hour_counts          [diamonds COLUMN ADDED 2026-05-15]
    (host_unique_id, hour_bucket, type) PK
     n            INTEGER  — count per (host, hour, type)
     diamonds     BIGINT   — gift diamonds per (host, hour) [type='gift' only]

  tiktok_room_stats                       [NEW TABLE 2026-05-15]
    room_id  BIGINT PRIMARY KEY
    diamonds         BIGINT   — gift diamonds (multi-host attribution baked in)
    n_gifts          INTEGER  — attributed gift count
    n_comments       INTEGER  — comment event count
    peak_viewers     INTEGER  — MAX(payload.total) seen on viewer_count
    last_updated_at  TIMESTAMPTZ
```

Read-path queries that switched to these tables:
- `_week_calendar_cached.wk_diam` → `tiktok_event_hour_counts.diamonds`
- `_lives_summary_last_broadcasts.stats` → `tiktok_room_stats`
- `_lives_summary_session_diamonds` → `tiktok_room_stats` (LEFT JOIN)
- `_lives_summary_30d_averages.avg_diamonds` → `tiktok_room_stats`
- `_lives_summary_median_diamonds` → `tiktok_room_stats`

---

## Operational notes

### Worker restart required
The `run-listener` worker process is separate from uvicorn and does
NOT auto-reload on code change. To activate Phase 9.2's
`_bump_room_stats` write call on new events, restart the worker
manually. Then re-run the idempotent backfill once more:

```bash
python database/migrations/add_tiktok_room_stats.py
```

### Migrations are all idempotent
Safe to re-run any time. They check `_table_exists` / `_column_exists`
before ALTER, and use `INSERT … ON CONFLICT DO UPDATE` for the
backfill. After the worker restart, re-running picks up any rooms
the inline bump missed during the gap.

### Cache observability
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:9020/admin/tiktok/cache/stats
```
Returns hit/miss counters. Reset on process restart. Healthy
steady-state: `lives_summary` ratio > 0.8 (it's at 0.81 currently).

---

## Lessons (verbatim from the design doc)

1. **Measure before optimizing.** The auditor's "10K heap fetches" estimate for `_lives_summary_hourly` matched the data scale but the actual wall-clock (18.7 ms) was bounded enough to leave alone. The real cold-mount killer was `wk_diam` (9.15 s) — an 8-day window.

2. **Worker-process vs uvicorn-reload divergence.** The dev backend uses `--reload`, which catches code changes. The worker (`cli.py system tiktok run-listener`) is a separate process and does NOT reload. After any write-path change, the worker must be manually restarted before new events populate new write paths. Backfills bridge that gap.

3. **"Fix it for admin" / "fix it for public" gap.** Several issues had the infrastructure already shipped for admin but not consumed on the public page (WS, audience flag, public-set filter). The fix was 30 lines of frontend wiring — not architectural work. Always audit "what's already shipped for the other audience" before scoping new work.

4. **Pre-aggregation is the right answer when:**
   - The read pattern is bounded (per-host, per-room, per-time-window)
   - The write pattern is high-volume but each write touches a few rollup rows (O(1) per event)
   - The aggregate is associative (sum, max, count)
   - Attribution / filtering can be decided at write time

5. **The audit caught real bugs.** Three of the 5 audit findings (A1, A2, A3) were genuine regressions that would have shipped silently. A1 alone had recovered 35 rooms of data the read path was missing. Always audit the AI's work with another AI.

6. **Default flips cascade.** Changing the default of `_set_cache_headers` to `cacheable=True` would have affected 21 existing callers. The safer pattern: keep the safe default (`no-store`), opt in per-route after verifying the payload.

7. **INNER JOIN vs LEFT JOIN matters for backfills.** An INNER JOIN that "should always have a match" silently drops rows when the data has gaps you didn't expect (deleted subscriptions, orphan rooms). LEFT JOIN with COALESCE is the safer default for pre-aggregation that needs to be a complete shadow of the raw table.

---

## Perf snapshots (all in `.claude/tracking/perf/`)

| Snapshot | Phase | Cold | Warm p50 |
|---|---|---:|---:|
| phase-9-baseline.json       | baseline                | 29,382 ms | 36.7 ms |
| phase-9.1-wk_diam-preagg.json | wk_diam → pre-agg      |  1,311 ms | 40.1 ms |
| phase-9.2-room_stats.json   | room_stats table        |    543 ms | 36.8 ms |
| phase-9.4-final.json        | WS + observability      |    667 ms | 32.1 ms |
| phase-9.5-post-audit.json   | audit fixes applied     |    341 ms | 31.5 ms |

Diff with:
```bash
python cli.py system tiktok perf compare \
  .claude/tracking/perf/phase-9-baseline.json \
  .claude/tracking/perf/phase-9.5-post-audit.json
```

---

## Carried forward (not addressed this session)

- **CTE long-running-room blind spot** — all three CTEs bound by `first_seen_at > NOW() - INTERVAL '…'` miss marathon broadcasters. Add `OR ended_at IS NULL` to the CTE bound.
- **SQLite dialect guards** — `_lives_summary_hourly` + `_daily_buckets_cached` else-branch use Postgres-only syntax without `_is_postgres()` guard.
- **`events_per_min`** — measured at 4.4 ms; not a bottleneck today, but eventually replace with `SUM(n)` from current partial hour of `tiktok_event_hour_counts`.
- **Pre-existing C1 — `SubscriptionState.ERROR` removed from `offline_states`** — verify intent with the `_handle_offline_for` author.
- **Pre-existing C3 — `_handle_offline_for` fires on every retry tick** — should gate on `if not last_offline`.
- **2v2 / 3v3 rival rendering** — duplicated team scores in `<BattlerCard>` (carried from earlier sessions).
- **UI features pending from earlier sessions**: viewer-count sparkline, live captions panel, polls widget, Q&A inbox, stream-uptime panel.

---

## Files for the next reader

- **This log** — `docs/antigravity/session_log_2026_05_15.md` (you're reading it)
- **Design doc** — `docs/antigravity/db_perf_2026_05_15_phase9.md` (DBA-verifiable writeup)
- **CHANGELOG** — `.claude/tracking/CHANGELOG.md` (top entry)
- **MEMORY** — `.claude/memory/MEMORY.md` (Last Session + Remaining Work)
- **Audit responses** — `docs/antigravity/report.md`, `applied_postgres_query_planner_optimizations.md`, `applied_performance_report_2026_05_15.md`
- **Perf snapshots** — `.claude/tracking/perf/phase-9-*.json` (5 files)
- **Migrations** — `backend/database/migrations/add_event_type_hour_counts_diamonds.py`, `add_tiktok_room_stats.py`

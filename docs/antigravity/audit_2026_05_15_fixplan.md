# Fix plan — retroactive `/audit HEAD~5..HEAD` findings
**Created:** 2026-05-15
**Audit doc**: this fix plan is the actionable companion to the
retroactive audit run after the `/audit` slash command shipped.
17 findings across 4 specialist agents: **1 CRITICAL, 6 HIGH, 6 MEDIUM, 5 LOW**.

> Hold for execution. The user has another task first. This document
> captures every finding with the specific fix shape, file:line
> evidence, expected effort, and dependencies — so the work can be
> picked up cold without re-reading the audit transcript.

---

## Phase 1 — Block-deploy (do first)

These three should ship as a single follow-up commit before this
branch can safely merge to `main`.

### F1 [CRITICAL] · Dead pre-agg write amplification

- **File**: `backend/adapters/persistence/tiktok_persistence.py:5295-5344` (read), `:2436-2444` (write)
- **Bug**: Migration `add_event_type_hour_counts_diamonds.py` added a `diamonds` column on `tiktok_event_type_hour_counts` AND wired the write-time bump. But `_lives_summary_hourly` STILL reads raw `tiktok_events` — verified by grep, nothing in the codebase reads `tiktok_event_type_hour_counts.diamonds`. Net: every event now pays an extra UPSERT cost on a hot column for zero read-side benefit.
- **Pick one fix**:
  - **A — drop the write + migration** (recommended given the read path was deliberately left raw because 18.7 ms wasn't a bottleneck): revert the diamond bump in `_bump_event_hour_count` and ship a follow-up migration to `ALTER TABLE … DROP COLUMN diamonds` on `tiktok_event_type_hour_counts`. Update the design doc.
  - **B — wire the read** (gives up minute-resolution sparkline): rewrite `_lives_summary_hourly` to read from the pre-agg. Changes the UI: 24 hour buckets instead of 60 minute buckets. Requires a frontend audit on `Sparkline` to confirm the new resolution works.
- **Effort**: A is ~50 lines (revert + drop-column migration). B is ~30 lines backend + frontend audit.
- **Dependency**: none

### F2 [HIGH] · `cross_live_gifters_for_host` leaks private host names + diamonds

- **File**: `backend/adapters/persistence/tiktok_persistence.py:3817-3852`, `backend/domain/services/tiktok_service.py:4074`, `backend/routes/public_tiktok.py:779-786`
- **Bug**: Anonymous public viewer hitting `/public/tiktok/lives/{handle}/cross-live-gifters` gets `other_hosts[]` containing EVERY tracked `host_unique_id` the gifter has sent diamonds to — including `is_public=False` hosts — with per-host diamond and gift totals. Public-surface enumeration of private hosts + partial revenue reconstruction.
- **Fix**: Thread `public_only: bool = False` through the call chain:
  ```python
  # public_tiktok.py
  return svc.get_cross_live_gifters_for_host(handle, public_only=True)
  # tiktok_service.py
  def get_cross_live_gifters_for_host(self, handle, *, public_only=False):
      return self._persistence.cross_live_gifters_for_host(handle, public_only=public_only)
  # tiktok_persistence.py — second query (breakdowns):
  sql = """
      SELECT user_id, host_unique_id AS host, diamonds, gifts
      FROM tiktok_user_host_summary uhs
  """
  if public_only:
      sql += """
          JOIN tiktok_subscriptions ts ON ts.unique_id = uhs.host_unique_id
              AND ts.is_public = true
      """
  sql += " WHERE user_id = ANY(:uids) ORDER BY user_id, diamonds DESC"
  ```
  Also recompute `host_count`, `diamonds_elsewhere`, `gifts_elsewhere` from the filtered subset (same pattern as `common_gifter_detail.public_only`).
- **Effort**: ~40 lines spread across 3 files
- **Dependency**: none — security-critical
- **Test**: hit the public endpoint with a known gifter who has tipped both public and private hosts; verify only public hosts appear in the response

### F3 [HIGH] · Migrations unregistered for fresh deploys

- **File**: `backend/database/migrations/add_event_type_hour_counts_diamonds.py`, `backend/database/migrations/add_tiktok_room_stats.py`
- **Bug**: Neither migration is referenced from any startup hook or migration runner. Fresh production deploy → tables/columns don't exist → pre-agg reads return 0 silently for `last_broadcasts`, `session_diamonds`, `avg_diamonds`, `median_diamonds`.
- **Fix shape**: Find the migration runner (it's not in `api_main.py:initialize_services` per the existing pattern; check `backend/api_main.py` startup hooks + `backend/database/core/`). If migrations truly run manually-only, then:
  1. Document the manual-run requirement in `backend/docs/DB_ARCHITECTURE.md`
  2. Add both new migrations to whatever deploy script the user uses
  3. Consider adding a startup-time check that fails fast if the migration hasn't been applied (`if not _column_exists(...): raise RuntimeError(...)`)
- **Effort**: ~30 min investigation + ~20 lines if a runner exists; just docs if not
- **Dependency**: none

---

## Phase 2 — Functional regressions (fix before merge to main)

These don't block deploy of THIS branch (assuming the worker is restarted and Phase 1 ships), but they're real correctness regressions in pre-existing modifications that snuck into commit 260dbfb.

### F4 [HIGH] · `_handle_offline_for` wipes profile_error + freezes scraper for 4h

- **File**: `backend/domain/services/tiktok_service.py:4214-4231`, `backend/adapters/persistence/tiktok_persistence.py:394-396`
- **Bug**: On every `UserOfflineError`, the eager offline path calls `update_subscription_profile(unique_id, profile={"is_live": False})`. The persistence implementation unconditionally:
  - sets `profile_refreshed_at = now` → `list_subscriptions_with_stale_profiles` skips this row for 4h
  - sets `profile_error = None` → wipes any recent WAF detection diagnostic
  Net: a host going offline (legitimately or via WAF) drops out of the re-probe loop for 4h. Recovery latency from offline→live grows from 60s to 4h.
- **Fix shape**: Either:
  - Add a narrower setter `update_subscription_live_status(unique_id, is_live: bool)` that only writes `is_live` and `live_checked_at`, leaving `profile_refreshed_at` and `profile_error` alone
  - OR change `_handle_offline_for` to call that narrower setter
- **Effort**: ~25 lines (one new persistence method + replace the call site)
- **Dependency**: none, but interacts with F5 (SIGI primary) — fix together if possible

### F5 [HIGH] · SIGI-as-primary-liveness misses just-went-live creators

- **File**: `backend/adapters/tiktok_profile_scraper.py:486-491`, fallback gate at `:154`
- **Bug**: SIGI scrape unconditionally sets `is_live = False` when `user.roomId` is missing/zero. Step 2 Euler fallback only runs when `is_live is None`. TikTok's static profile page has CDN lag (documented in `tiktok_live_client.py:947` in the reverse direction). A host that just went live can be shown offline for minutes; Euler is never consulted to second-guess.
- **Fix shape**: When SIGI scrape succeeds but reports offline AND no other strong signal exists, set `is_live = None` (UNKNOWN) instead of `False`. The Euler fallback will then run. Specifically: in `_fetch_profile_page`, the `roomId == 0` branch should set the field to `None` if we don't have other corroborating evidence (e.g., the user just came off a CONNECTED state).
- **Effort**: ~15 lines + verification on a known-live host
- **Dependency**: pairs with F4

### F6 [HIGH] · `SubscriptionState.ERROR` docstring vs code mismatch

- **File**: `backend/domain/services/tiktok_service.py:4170-4184`
- **Bug**: Docstring at line 4170 says transitions into "DISCONNECTED / LIVE_ENDED / ERROR / DISABLED" trigger `_local_offline_since` stamping. Code at 4180-4184 excludes `ERROR`. A future maintainer will "fix" this by adding ERROR back to the set, reintroducing the AgeRestrictedError-stuck-slot bug that WORKER.md §3.4 documents was deliberately removed.
- **Fix**: Update the docstring to match code + cite WORKER.md §3.4 inline:
  ```python
  """
  Transitions into an offline-equivalent state — DISCONNECTED,
  LIVE_ENDED, DISABLED — stamp `_local_offline_since` for the
  stuck-slot defense.
  
  ERROR is deliberately NOT in this set. AgeRestrictedError keeps
  hosts in ERROR for the duration of the exponential backoff
  (30 min → 4 h); stamping `_local_offline_since` on ERROR would
  cause the stuck-slot release to kill the slot at every backoff
  tick, defeating the backoff. See WORKER.md §3.4.
  """
  ```
- **Effort**: ~5 lines
- **Dependency**: none

### F7 [HIGH] · Public WS keeps streaming a just-flipped-private host for 30s

- **File**: `backend/routes/public_tiktok.py:518-547` (delta pump)
- **Bug**: `get_public_handle_set()` has 30s TTL. After operator flips `is_public=False`, that host's deltas keep being forwarded to already-connected public WS clients for up to 30s. This is a separate channel from the REST `no-store` path (which is instant after the audit fix).
- **Fix shape**: Two options:
  - **A — instant invalidation**: when `update_subscription_profile` writes `is_public=False`, invalidate the public-handle-set cache via a service-level callback. Add `_public_handle_set_cache = None` reset to the write path.
  - **B — shorter TTL**: drop the public-handle-set TTL when used inside the WS pump (still check cache for performance, but force re-validate every 2-3s).
  - **C — per-event re-check (slow but simplest)**: drop the cache entirely inside the delta-forward path. Cost: extra DB read per delta.
- **Effort**: A is cleanest, ~20 lines. C is simplest, ~5 lines (probably acceptable given the public WS volume).
- **Dependency**: none

---

## Phase 3 — Correctness + write amplification

### F8 [MEDIUM] · `_apply_state_delta` fires BEFORE commit

- **File**: `backend/adapters/persistence/tiktok_persistence.py:2330-2333` (PG path) and `:2367-2370` (synthetic/SQLite path)
- **Bug**: `_apply_state_delta` publishes the WS delta inside the open transaction, before `s.commit()`. If commit fails (FK violation, deadlock, connection drop), WS clients have already seen an event that was rolled back. Self-heals on the 60s TTL refresh but produces incorrect intermediate UI state.
- **Fix**: Move the `_apply_state_delta` call to AFTER `s.commit()`. The PG dedup path will need to capture the values it needs before the commit:
  ```python
  if row_id:
      diamonds_delta, gift_attributed = self._bump_event_hour_count(...)
      self._bump_room_stats(...)
      s.commit()
      # Now safe — DB state matches what we're about to publish
      self._apply_state_delta(s, host_unique_id, event_type=type, payload=payload, viewer=viewer)
  ```
  Watch out: `_apply_state_delta` currently takes `s` and might query it. If so, either keep passing it (now post-commit) or refactor to take only the values it needs.
- **Effort**: ~30 lines + test that delta publish still works
- **Dependency**: none

### F9 [MEDIUM] · `_bump_room_stats` write amplification on every comment

- **File**: `backend/adapters/persistence/tiktok_persistence.py:2484-2503`
- **Bug**: Every comment event fires a full UPSERT on `tiktok_room_stats` with `peak_viewers=0` in VALUES. `GREATEST(stored, 0)` handles correctness, but on a hot stream (5+ comments/sec) it's 5+ UPSERTs/sec on the same PK row with an always-false peak update.
- **Fix**: Either:
  - **A — skip peak from VALUES**: build the UPSERT clause conditionally — only include `peak_viewers` in VALUES when `event_type == 'viewer_count'`. Same trick for `diamonds`/`n_gifts` etc.
  - **B — accept the cost**: PK UPSERT on a tiny row is cheap. Drop this finding. But on a 200-comment/sec hot stream it does add up.
- **Effort**: A is ~30 lines (conditional SQL building); B is zero.
- **Dependency**: none

### F10 [MEDIUM] · `_public_lives_summary_cache` unbounded by raw tz

- **File**: `backend/domain/services/tiktok_service.py:3699-3766`, `backend/routes/public_tiktok.py public_lives` handler
- **Bug**: Cache keyed on raw `tz` from query param without validation/canonicalization. Persistence layer maps unknown zones to UTC, so 1000 unique invalid tz strings → 1000 cache entries holding identical UTC payloads. No eviction.
- **Fix**: Validate `tz` at the route layer:
  ```python
  tz: str = Query("UTC", pattern=r"^[A-Za-z_]+(/[A-Za-z_]+){0,2}$", max_length=64)
  ```
  AND canonicalize before keying:
  ```python
  canon_tz = self._canonicalize_tz(tz)  # already exists for the SQL path
  cached_for_tz = self._public_lives_summary_cache.get(canon_tz)
  ```
- **Effort**: ~15 lines
- **Dependency**: none

### F11 [MEDIUM] · `public_room_gifters` multi-room missing same-host check

- **File**: `backend/routes/public_tiktok.py:870-880`
- **Bug**: Docstring promises "every id must belong to the SAME public host." `_resolve_public_room_set` only verifies `is_public=True`, not same-host. Two public hosts' rooms can be aggregated → cross-host gifter leaderboard on the public surface (not catastrophic but breaks the contract).
- **Fix**: After `_resolve_public_room_set`, verify all rooms share `host_unique_id`:
  ```python
  rooms = _resolve_public_room_set(parsed)
  hosts = {svc._persistence.get_room_host_handle(r) for r in rooms}
  if len(hosts) > 1:
      raise HTTPException(400, detail="all room ids must belong to the same host")
  ```
- **Effort**: ~10 lines
- **Dependency**: none

### F12 [MEDIUM] · Cache stats double-count misses during singleflight

- **File**: `backend/domain/services/tiktok_service.py:3692-3725` (public summary), `:3789-3798` (totals)
- **Bug**: `_record_cache("…", hit=False)` is called BEFORE acquiring the singleflight lock. N concurrent callers all record N misses when only one paid the SQL cost. Operator hit-ratio dashboards under-report effectiveness during traffic bursts.
- **Fix**: Move the miss-record to inside the lock, after the inner double-check:
  ```python
  with lock:
      cached_for_tz = self._public_lives_summary_cache.get(tz)
      if cached_for_tz and (now - cached_for_tz[0]) < TTL:
          self._record_cache("public_summary", hit=True)  # collapsed hit
          return cached_for_tz[1]
      self._record_cache("public_summary", hit=False)  # real miss
      # ... do the work
  ```
- **Effort**: ~10 lines
- **Dependency**: none

### F13 [MEDIUM] · `on_offline` fires every retry tick

- **File**: `backend/adapters/tiktok_live_client.py:870-879`
- **Bug**: `on_offline` callback is inside `except UserOfflineError:` without gating on `last_offline`. The supervisor loop re-enters the offline branch on every retry — once per ~5-30s depending on backoff. Each fires the callback, each schedules a DB write through the event executor. Idempotent, but wasteful.
- **Fix**: Gate on transition:
  ```python
  except UserOfflineError:
      if not last_offline:
          logger.info("@%s is offline; will retry on a slow cadence.", self._unique_id)
          if self._on_offline:
              try:
                  await self._on_offline()
              except Exception:
                  pass
      last_offline = True
      ...
  ```
- **Effort**: ~5 lines
- **Dependency**: none

---

## Phase 4 — Cleanup (LOW)

### F14 [LOW] · `_handle_offline_for` docstring lies about bypassing scraper
- **File**: `backend/domain/services/tiktok_service.py:4214-4217`
- **Fix**: Replace "bypasses the profile scraper" with "pre-empts the scraper for the host's `is_live` flag — the scraper itself continues to poll on its own cadence." 2 lines.

### F15 [LOW] · `WORKER.md` section numbering jumps 3.2 → 3.4
- **File**: `backend/docs/WORKER.md:193, 218`
- **Fix**: Renumber subsequent sections OR backfill the 3.3 placeholder. 5 min.

### F16 [LOW] · Error-string sentinel sniffing brittle
- **File**: `backend/domain/services/tiktok_service.py:2478-2482`
- **Fix**: Add a structured `error_kind` field to the scraper output. The classifier switches on `error_kind == "waf"` instead of `"WAF" in err_str`. ~20 lines (scraper output + classifier).

### F17 [LOW] · Worker telemetry charts re-render every poll
- **File**: `frontend/src/modules/admin/components/TikTokWorkerTelemetry.tsx:432, 442-449`
- **Bug**: `data.profile_scrapes` is a fresh object reference each poll, busting `useMemo([data.profile_scrapes, …])`. ECharts re-runs with `notMerge` on every poll. Earlier bar-chart variant only recomputed when `data.waf.totals` changed shape.
- **Fix**: Derive a stable memo key from the data (e.g., serialize the array shapes/lengths or sum the first row). ~15 lines.

### F18 [LOW] · Worktree hygiene
- **Files**: `backend/test_bundle.py`, `backend/test_bundle_perf.py`, `backend/test_profile.py`, `check_payload_size.py`, `test_perf.py`, `.playwright-mcp/`, `backend/data/`
- **Fix**: Either move ad-hoc scripts to `backend/tests/` with `test_*` names and proper pytest setup, OR add to `.gitignore`. Same for `.playwright-mcp/` and `backend/data/`. ~5 min.

---

## Execution suggestion

When you're ready to apply, the cleanest grouping is:

| Commit | Contents | Why grouped |
|---|---|---|
| `fix(security): public surface — cross-live-gifters + WS handle-set` | F2 + F7 | Both public-surface security fixes |
| `fix(tiktok): liveness + offline state machine` | F4 + F5 + F6 + F13 | All related to the SIGI/Euler/state-transition cluster |
| `fix(tiktok): drop dead pre-agg write amplification` | F1 (option A) | Drops the dead write and the migration |
| `fix(tiktok): event commit ordering + write amplification` | F8 + F9 | Both about the event-persist transaction |
| `fix(tiktok): cache observability + tz validation` | F10 + F11 + F12 | Smaller correctness/cleanup |
| `chore: docs + worktree cleanup` | F14 + F15 + F18 | Doc-only |
| `refactor(tiktok): structured scraper error_kind` | F16 | Standalone refactor |
| `perf(frontend): worker telemetry useMemo stability` | F17 | Standalone frontend |

Total: 8 commits, all small and reviewable.

## Validation steps per phase

- **F1 (option A)**: re-run perf snapshot → confirm warm p50 unchanged; verify no new "diamonds column does not exist" errors after migration drop
- **F2**: hit `/public/tiktok/lives/{handle}/cross-live-gifters` with a known gifter; verify `other_hosts[]` excludes private hosts
- **F3**: simulate fresh deploy (`DROP TABLE tiktok_room_stats; DROP COLUMN diamonds`) and check the startup path either runs migrations or fails fast
- **F4 + F5**: take a known WAF-blocked host; flip the worker on; verify scraper continues re-probing every 60s (not 4h); verify a just-went-live host is detected within 60s
- **F7**: open a public WS client; flip a host private; verify deltas stop within ~2s (not 30s)
- **F8**: induce a deliberate commit failure (FK violation on a synthetic event); verify WS client does NOT see the event
- **F10**: hit `/public/tiktok/lives?tz=` with 1000 random strings; verify cache doesn't grow past N canonical entries

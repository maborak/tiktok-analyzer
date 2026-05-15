# Listener Worker

The listener pool is the process that subscribes to TikTokLive
WebCast feeds, persists every event, and fans out to the API workers
via Redis. This document covers how it's deployed, how it
coordinates across processes, how slots are allocated, and the known
gotchas. For the event pipeline downstream of the worker see
`EVENTS_LOGGER.md`. For the schema it writes to see `DB_ARCHITECTURE.md`.

Last revised 2026-05-14.

---

## 1. Deployment modes

The framework supports two deployment shapes, gated by the env var
`PHOVEU_BACKEND_TIKTOK_LISTENER_MODE`:

| Mode | What it means |
|---|---|
| `in_process` (default) | Listener pool runs INSIDE the uvicorn API process. Same lifecycle as HTTP. Simplest setup, no Redis required for ingestion. |
| `worker` | Listener pool runs in a SEPARATE process (`python cli.py system tiktok run-listener`). API is started in passive mode (subscription CRUD only, no session lifecycle). Event fan-out goes through Redis pub/sub on channel `tiktok:events`. |

### 1.1 Why two modes?

In-process mode is the easy path:
- One process, one .env, one log stream.
- No Redis dependency for ingestion (only for distributed cache /
  notification queue if those are enabled).
- Local dev: edit code, uvicorn `--reload` picks it up, listener
  restarts with the rest.

Worker mode is the production-shaped path:
- API hot-reload (`--reload`) no longer drops every WebSocket. Devs
  iterating on routes don't break ingestion.
- Listener survives API redeploys / crashes; admin tabs reconnect
  but the underlying event capture continues.
- The API can scale horizontally (multiple uvicorn workers behind a
  load balancer) without each one trying to claim ingestion.
- Trade-off: two processes to operate; Redis becomes a hard
  dependency.

### 1.2 Supervisor pattern (`--reload`)

`run-listener --reload` wraps the actual worker in a supervisor
process (`_supervisor_main` in `backend/cli/commands/system/tiktok.py:197`).

```
   supervisor (--reload)
        │
        │ spawns + watches
        ▼
   worker (no --reload)
   ├── claims subscriptions
   ├── runs TikTokLive listeners
   ├── persists events
   ├── publishes to Redis
   └── heartbeats every 5s
```

Supervisor responsibilities:
- Spawn the child via `subprocess.Popen(child_argv)`.
- Watch tracked source files (`*.py` under `backend/`). On change,
  SIGTERM the child + respawn.
- Forward signals (SIGINT → SIGTERM child → wait → exit).
- On unexpected child exit, respawn after a short backoff.

The supervisor stays light (no DB / Redis connections of its own).

Gotcha: if you SIGTERM the supervisor's child manually but the
supervisor wasn't started with `--reload`, the supervisor doesn't
respawn (in non-reload mode it's not really a supervisor, just a
direct `asyncio.run(_main(...))` invocation). Use `kill <child_pid>`
only if you've confirmed `--reload` is on.

---

## 2. Capacity + claim model

### 2.1 Per-worker capacity

```python
self._worker_capacity: int = int(
    os.getenv("PHOVEU_BACKEND_TIKTOK_WORKER_CAPACITY") or "30"
)
```

The default `30` is a polite-scraper heuristic. ~30 simultaneous
TikTokLive WebSocket connections per IP stays below TikTok's per-IP
anti-bot threshold (`DEVICE_BLOCKED` cascade above that level). It's
not formally calibrated; the number was tuned empirically.

Override via env when:
- You're running multiple workers on distinct IPs (each can carry 30).
- You have rotating residential proxies (the per-worker number maps
  to a single egress identity).
- You're seeing `DEVICE_BLOCKED` errors → drop it.
- You have plenty of headroom and small handle counts → drop it to
  match handle count (no slot-leak risk).

### 2.2 Claim model — DB-only

Coordination across workers uses the database, never the filesystem.
The user explicitly rejected `flock`-based or file-based mutex (per
`~/.claude/projects/.../memory/feedback_db_only_coordination.md`).

Two tables drive coordination:

- `tiktok_workers` — one row per worker process. UNIQUE on
  `worker_key`. Heartbeat timestamp, capacity, `status`,
  `desired_status`, `command` (admin-driven pause/resume/kill
  signals).
- `tiktok_subscriptions.assigned_worker_id` + `assignment_lease_until`
  — soft assignment with TTL. When `lease_until` expires, another
  worker may steal.

### 2.3 Claim transaction

```sql
SELECT s.unique_id
FROM tiktok_subscriptions s
WHERE s.enabled = TRUE
  AND (
    s.assigned_worker_id IS NULL
    OR s.assignment_lease_until < NOW()
  )
ORDER BY s.unique_id
LIMIT :max_to_claim
FOR UPDATE SKIP LOCKED;     -- key bit
```

Then UPDATE the rows to set `assigned_worker_id = :me` and
`assignment_lease_until = NOW() + :lease_seconds`.

`SKIP LOCKED` is the critical primitive. Two workers running this
query simultaneously see disjoint result sets — the row-level lock
held during the SELECT acts as the mutex. Without `SKIP LOCKED` they'd
contend on a shared lock + serialize → effective single-threaded.

### 2.4 Lease + heartbeat

- `LEASE_SECONDS = 60` — claim grants exclusive ownership for 60 s.
- `_db_heartbeat_loop` runs every 5 s — UPDATE on `tiktok_workers`
  to bump `last_heartbeat_at`. ALSO calls
  `extend_my_leases(worker_id, LEASE_SECONDS)` to keep the
  per-subscription lease fresh.
- If a worker crashes / wedges, its heartbeat goes stale within ~30 s
  and its leases expire within 60 s. Another worker's next
  `claim_subscriptions` picks up the abandoned handles.

`reap_stale_workers(stale_after_seconds=30)` runs at startup to
DELETE worker rows whose heartbeat hasn't updated in 30 s. Prevents
"phantom worker" entries from blocking the unique key.

### 2.5 Reconcile loop

The worker calls `reconcile_assignments()` every `reconcile_seconds`
(default 10 s). The reconcile is the central control loop. It does:

1. **Probe-cache-driven release** — for each currently-owned handle,
   check the cached `is_live` from the central probe. If
   `is_live=False` AND probe is fresh (<3 min old) AND offline-window
   ≥5 min, RELEASE the slot. See §3 for the trap.
2. **Resume sessions** we own but don't have running locally (handles
   the worker-restart case where leases were extended across restart
   but `_sessions` is empty).
3. **Claim more** if we have capacity (`capacity - len(_sessions)`).
4. **Drop disabled handles** — anything `enabled=False` in the DB
   gets `_stop_session` + assignment cleared.
5. **Battle of contention** — if another worker's lease appears on a
   handle we still have running, voluntarily release.

The reconcile cadence (10 s) plus `LEASE_SECONDS` (60 s) gives a
1-in-6 hit rate per worker per lease cycle — leases are renewed long
before they'd expire.

---

## 3. Slot recycling — the trap

### 3.1 The current logic

`reconcile_assignments` releases a slot when ALL of:

1. The CENTRAL probe last said `is_live=False`
2. AND that observation is < `LIVE_STATUS_FRESHNESS_S = 180.0` s old
3. AND local state is NOT `CONNECTED` (we'd contradict the probe)
4. AND we've been observing offline ≥ `OFFLINE_RELEASE_HYSTERESIS_S = 300.0` s

The intent: be conservative. Don't release a creator who's actually
live just because the probe blipped.

### 3.2 The trap

The probe returns a TRI-STATE (`tiktok_service.py:1795-1799`):

```python
raw_is_live = profile.get("is_live") if profile else None
if raw_is_live is None:
    is_live = None        # probe couldn't determine (WAF, 403, …)
else:
    is_live = bool(raw_is_live)
```

The recycle path treats `None` as "don't touch" (the alternative
caused cascading evictions when TikTok had a 1-second 403 blip).

**Failure mode**: a host whose live ended (local state →
`DISCONNECTED`) AND whose profile probe consistently returns `None`
(WAF on their profile URL, deleted account, age-restricted) →
**slot leaks forever**. The session sits in `_sessions` counting
against capacity; the recycle says "probe is None, leave it alone";
new subscriptions can't be claimed.

This is the user-reported "30/30 with disconnected sessions for 3+
hours" bug. Real production issue.

### 3.4 Proposed fix (shipped)

Two-stage defense:

**Stage 1 — local signal as authoritative free trigger**:
In `_handle_state_change_for`, when state transitions to
`DISCONNECTED` / `LIVE_ENDED` / `DISABLED`, mark
`self._local_offline_at[handle] = time.time()`. Reset on state
back to `CONNECTED`. In reconcile, add a new condition: if
`local_offline_at` is older than `LOCAL_OFFLINE_RELEASE_S` (600 s = 10 min),
force-release REGARDLESS of probe state.
**Note**: `ERROR` state is intentionally EXCLUDED from this list. Terminal
errors like `AgeRestrictedError` have long exponential backoffs (up to 4h).
If we included `ERROR`, the stuck-slot defense would kill the session
mid-backoff and release the slot, causing an endless reconnect loop that
burns the Euler quota.

**Stage 2 — cap probe-`None` patience**:
If `is_live=None` has persisted continuously for >
`PROBE_UNKNOWN_RELEASE_S` (1800 s = 30 min), treat as False
for recycle purposes. The "1 sec of 403s → cascade" the existing
code guards against doesn't fit a 30-min window — by then the probe
has either recovered or the host is genuinely unreachable.

**Eager Offline Sync**:
To prevent WAF-blocked probes from keeping `is_live=True` forever
and causing endless WS reconnect attempts, `UserOfflineError` now
triggers an eager `update_subscription_profile` to set `is_live=False`
immediately.

---

## 4. Process internals

### 4.1 Three executors

`tiktok_service.py:212` — three thread pools:

| Executor | Size | Purpose |
|---|---|---|
| `_control_executor` | 1 thread | Heartbeat + DB control calls (pause/resume/kill polling). Single-threaded by design — control plane is serial. |
| `_event_executor` | 4 threads | Event persistence (`_persist_event_threadsafe`). |
| Default loop executor | sys default | Everything else (profile fetches, scrape probes, periodic maintenance). |

Why three? Starvation prevention. Under heavy event load, the default
executor was saturating and the heartbeat couldn't get scheduled —
causing leases to expire and other workers to steal handles even
though we were healthy. Dedicating a thread to control fixes the
"heartbeat-starved" failure mode.

### 4.2 `gap_tracker` reentrant lock

The gap-tracker (`adapters/tiktok_offset_tracker.py`) uses
`threading.RLock`, NOT `threading.Lock`. The `all_snapshots()` method
holds the lock and calls `snapshot()` per session which re-acquires.
With a non-reentrant Lock this deadlocks the heartbeat thread on
the first tick.

This was discovered the hard way. Don't change it back.

### 4.3 Centralized live-status scraping

A SINGLE `_live_scraper_loop` task per worker hits TikTok's profile
endpoint with ~5 s pacing. Writes `is_live` + `live_checked_at` to
`tiktok_subscriptions`. This is shared state: every supervisor reads
this cache via `peek_live_status(unique_id)` rather than each
supervisor hammering TikTok independently.

Without this we got `DEVICE_BLOCKED` cascades — 18 concurrent
supervisors checking liveness at once.

### 4.4 `_wait_until_live` hysteresis

When a supervisor wants to connect to a creator's live, it first
checks `is_live` from the cache. The check is:
- sleep-first (5 s minimum), then poll
- requires TWO consecutive positive reads before attempting connect

Why both? TikTok's profile page LIES `is_live=true` for ~5 min after
a stream ends, while the WebSocket rejects immediately. Without the
two-consecutive-positive rule, we get tight reconnect loops.

---

## 5. Worker control plane

### 5.1 Admin signals via DB

The API doesn't send signals directly to the worker process. Instead,
the API writes to `tiktok_workers.desired_status` or `command`. The
worker polls these every reconcile cycle (10 s) and acts on its own
process:

| Admin action | Mechanism | Worker reaction |
|---|---|---|
| Pause all listeners | `UPDATE tiktok_workers SET desired_status='paused'` | Worker calls `pause_all()` on next reconcile. Active sessions enter PAUSED state but stay connected; new events still flow. |
| Resume | `UPDATE tiktok_workers SET desired_status='running'` | Worker calls `resume_all()`. |
| Kill | `UPDATE tiktok_workers SET command='kill'` | Worker calls `service.stop_requested = True` → main loop exits → process dies → supervisor respawns (in `--reload` mode) |
| Reconnect single sub | `UPDATE tiktok_subscriptions SET … WHERE unique_id=…` (TBD signal) | Worker sees the change, restarts that session. |
| Release sub | `POST /admin/tiktok/lives/{handle}/release` | API directly clears `assigned_worker_id`; worker's next reconcile drops it. |

Pros of DB-as-control-plane:
- No RPC infrastructure (gRPC, message queue, custom socket).
- Works across machines (the worker doesn't need to be reachable from
  the API).
- Persistent: admin clicks "pause," the desired-status survives a
  worker restart.

Cons:
- Up to one reconcile cycle of latency (10 s default).
- Requires read access to the DB from both sides.

### 5.2 SIGUSR1/SIGUSR2

POSIX signal handlers in `_main` (`cli/commands/system/tiktok.py:392`):
- `SIGUSR1` → `pause_all` (fire-and-forget task)
- `SIGUSR2` → `resume_all`

Useful for manual debugging without DB access. Not part of the
admin-UI control plane.

---

## 6. Phase 9 state cache integration

When `PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH={shadow,on}`, the worker
also writes to a per-host state cache:

```python
state_cache = TikTokStateCacheRedis(
    sync_client=redis.from_url(...),
    async_client_getter=get_redis,
    public_sanitizer=service.sanitize_public_patch,
)
persistence = TikTokPersistenceAdapter(state_cache=state_cache)
```

Every `persist_event_full` call (which is every event) routes
through `_apply_state_delta` which mutates the cache + publishes a
delta on Redis pub/sub. API workers subscribe and forward to
connected WS clients.

A `state-cache tick task` also runs in the worker process (started in
`_main` after the state cache is wired). Every 5 s, for each active
host, it recomputes age-derived fields (`last_*_age_s`,
`active_poll.fresh_age_s`) and publishes patches. See
`tiktok_state_ticker.py` and `PHASE9_PLAN.md`.

---

## 7. Health + observability

### 7.1 `/admin/tiktok/listener/status`

Returns a structured snapshot of every worker + their assigned
handles. Per-handle: state, events_total, last_event_age_s,
last_error (if any), recycle_release_in_s.

Reads from in-memory worker state — no DB hit. Cached implicitly via
the route handler (no TTL; freshly snapshotted on every request).

### 7.2 Worker log audit trail

Every significant lifecycle event writes a row to
`tiktok_worker_log`:

- `startup` — worker registered.
- `session_start` / `session_terminal` / `session_reconnect` — per-
  handle.
- `profile_probe_failed` / `profile_probe_partial` — WAF / 403
  probe outcomes with raw evidence (url, status, body_len, snippet).
- `ctrl_pause` / `ctrl_resume` / `ctrl_kill` — admin-driven actions.

The audit log is append-only with `event` + `ts` + `detail` JSONB.
Read by the admin UI for the per-host listener-status modal and for
the WAF-probe debug panel.

### 7.3 Heartbeat as proof-of-life

The 5 s heartbeat to `tiktok_workers.last_heartbeat_at` is the
primary liveness signal for ops. A worker whose heartbeat is > 30 s
old is considered dead; the next worker's reap pass deletes its row
and steals its handles.

---

## 8. Known issues + limitations

### 8.1 The stuck-slot bug (§3) — UNFIXED

Critical production impact. Workaround until shipped: manually
release stuck handles via `POST /admin/tiktok/lives/{handle}/release`,
or restart the worker process to clear all sessions and re-claim.

### 8.2 Probe blind spots

The probe scrapes `tiktok.com/@{handle}/live`. Three failure modes:
- WAF — TikTok's edge returns a generic challenge page. Probe
  returns `None`.
- Account banned / deleted — profile 404s. Probe returns `None`.
- Age-restricted — TikTok serves a different page. Probe returns
  `None`.

All three are indistinguishable from "transient network issue." The
worker conservatively treats `None` as "unknown" everywhere. See §3.

### 8.3 No auto-scaling

Capacity is a hard env-var number. The worker doesn't try to detect
"I have headroom, let me grab more" beyond the `claim_subscriptions`
loop. There's no autoscaler that adds more worker processes when
the queue of unclaimed handles grows.

Operator's workaround: run more workers on more IPs. The DB
coordination already supports it; nothing else needs to change.

### 8.4 Single-IP rate limit

The 30-per-worker capacity is bottlenecked by ONE TCP egress
identity. Even at multi-process scale on one host, you're hitting
TikTok from a single IP. Real multi-IP scaling requires real
residential proxies (`fetch_public_profile_throttled` could be
extended to rotate; not implemented today).

### 8.5 `_active_match` in-memory

Active PK battle state is held in `self._active_match: dict[room_id, info]`
inside the service. In `in_process` mode, a uvicorn `--reload`
drops this state mid-battle — the score timeline picks up cleanly
because every score update is persisted via `tiktok_matches`, but
the "in-flight battle" overlay on the lives page resets briefly.

In `worker` mode, the worker doesn't reload, so this is fine — but
documented as a known in-process gotcha.

---

## 9. Future plans

### 9.1 Short-term (committed)

- **Stuck-slot fix** (§3.4) — two-stage defense via local signal +
  probe-None patience cap. Highest priority; user-facing impact.
- **Phase 9.E** — Frontend uses WS-pushed state, polling becomes
  safety net only. Worker writes to state cache on every event;
  frontend hook applies deltas.

### 9.2 Medium-term

- **Calibrated capacity**. Replace the hardcoded `30` with a
  per-IP measurement: probe TikTok's rate-limit signals (`Retry-After`
  headers, `DEVICE_BLOCKED` frequency) and self-adjust.
- **Profile scraper port extraction**. Three lazy `adapters.*` imports
  in `tiktok_service.py` should become a `TikTokProfileScraperPort`
  + adapter. Documented in `OPEN_ISSUES.md` as ARC-2.
- **Multi-IP egress**. A `ProfileEgressPool` abstraction with
  per-handle stickiness (so a creator doesn't see IP changes mid-
  session). Lets us scale past TikTok's per-IP threshold.

### 9.3 Speculative

- **Move ingestion to a separate read replica DSN**. The listener's
  writes don't compete with API reads today (different connection
  pools) but going through the writer keeps us simple. Splitting
  could open optimizations on the writer side.
- **Per-handle worker affinity hints**. Today `claim_subscriptions`
  picks ANY unclaimed handle. Could prefer handles whose previous
  worker had `worker_key=$X` (sticky reassignment after a restart)
  to keep the live-event WebSocket cursor history aligned.
- **`tikfinity-analysis.md` follow-up**. The reverse-engineered
  TikTok protocol notes (`docs/tikfinity-analysis.md`) include
  header-rewrite tricks we could use to extend the probe's
  evasion. Currently we use only the basic scraper; if WAF
  frequency rises, the next escalation is encoded there.

---

## 10. Operator runbook (snippets)

### 10.1 Worker shows 30/30, can't add new handles

1. Run the listener-status query: which handles are claimed but
   `state != CONNECTED`?
   ```sql
   SELECT s.unique_id, s.is_live, s.live_checked_at,
          EXTRACT(EPOCH FROM (NOW() - s.live_checked_at))::int AS check_age_s
   FROM tiktok_subscriptions s
   WHERE s.assigned_worker_id IS NOT NULL
     AND s.enabled = TRUE
   ORDER BY s.live_checked_at NULLS FIRST;
   ```
2. Look for rows with `check_age_s > 180` AND `is_live IS NULL` —
   these are probe-stuck.
3. Either:
   - `POST /admin/tiktok/lives/{handle}/release` for each stuck
     handle, OR
   - `kill <listener_pid>` to force respawn (in `--reload` mode).
4. Permanent fix: §3.4.

### 10.2 Worker crash-looping

Symptoms: `tiktok_worker_log` shows rapid `startup` / `session_terminal`
entries; supervisor (in `--reload`) keeps respawning.

Likely cause: configuration mismatch (`WorkerKeyConflictError` — two
workers claiming the same `worker_key`). Check `tiktok_workers` for
duplicate rows; the unique constraint should prevent it but if a
network partition left a phantom row, manual DELETE clears it.

### 10.3 Probe hammering TikTok

Symptoms: 403 / DEVICE_BLOCKED in worker logs; `tiktok_subscriptions.live_checked_at`
stops updating.

Likely cause: the throttle in `fetch_public_profile_throttled`
isn't tight enough for our current IP pool.

Mitigations:
- Reduce `LIVE_SCRAPE_PAUSE_SECONDS` is the WRONG direction (more
  pause not less).
- Increase `LIVE_STATUS_TTL_SECONDS` so the worker doesn't re-probe
  hosts as aggressively.
- If neither helps, the issue is upstream of us — we're either
  rate-limited or banned at the IP level. Switch egress.

---

## 11. References

- `backend/cli/commands/system/tiktok.py` — CLI entry + supervisor
  + main loop.
- `backend/domain/services/tiktok_service.py` — TikTokService;
  ~3400 lines; the bulk of the worker logic.
- `backend/adapters/tiktok_live_client.py` — TikTokLive WebCast
  client wrapper.
- `backend/adapters/persistence/tiktok_persistence.py` — DB layer;
  `claim_subscriptions`, `release_my_assignment`,
  `extend_my_leases`, etc.
- `backend/database/tiktok/models.py` — `WorkerModel`,
  `WorkerLogModel`, `SubscriptionModel` etc.
- `~/.claude/projects/.../memory/feedback_db_only_coordination.md` —
  the rule "never flock/files for worker mutex."
- `~/.claude/projects/.../memory/project_tiktok_module.md` — non-
  obvious architectural decisions.
- `CLAUDE.md` section "Listener-pool deployment modes" — quick
  reference for `in_process` vs `worker`.

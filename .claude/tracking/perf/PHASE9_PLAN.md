# Phase 9 — WebSocket-pushed live state

**Goal**: replace the 30 s `livesBundle()` poll on `/admin/tiktok` and
`/lives` (public) with WS-pushed state deltas. Initial state still
comes from `/lives/bundle`. After connect, the server pushes a
versioned delta per host on every state change.

## Locked decisions

| Decision | Choice | Implication |
|---|---|---|
| Deployment shape | **Both** — dev in_process, prod worker | State cache is an adapter behind a port. Two impls: in-process `dict + Lock`, Redis `HSET / PUBLISH`. Boot picks based on `PHOVEU_BACKEND_TIKTOK_LISTENER_MODE`. |
| Surfaces covered | **Both** — admin + public | Two pub channels: `tiktok:lives:delta:admin`, `tiktok:lives:delta:public`. Public deltas filtered through `_pick(row, _PUBLIC_SUMMARY_FIELDS)` + `last_broadcasts[:1]` before publish. |
| Timeline | **Day-by-day**, A before B | Each phase ships independently behind a feature flag (`PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH={off,shadow,on}`). Off = today. Shadow = compute + publish but client ignores. On = client uses WS state. Phases A–D ship under `shadow`; phase E flips to `on`. |
| Consistency | **Strong, per-host monotonic version** | Server increments a version per host on every delta. Client tracks `versionByHost`. On gap, requests a per-host snapshot. |

---

## Architecture

```
┌────────────────────────────┐                          ┌────────────────────────┐
│  TikTokLive listener       │                          │  React lives page      │
│  (worker OR in_process)    │                          │  ─ summary state Map   │
│                            │                          │  ─ versionByHost Map   │
│  every event →             │                          │  ─ useTikTokLivesSocket│
│   1. INSERT tiktok_events  │                          └─────┬───────┬──────────┘
│   2. apply_state_delta()   │                                │ WS    │ HTTP
│       a. mutate state cache│                                │       │ (initial bundle
│       b. INCR version      │                                │       │  +periodic reconcile)
│       c. PUBLISH δ         │                                │       │
└──────────┬─────────────────┘                                │       │
           │                                                  │       │
           ▼                                                  │       │
┌────────────────────────────┐        SUBSCRIBE     ┌─────────▼───────▼──────────┐
│  State store               │ ◀──────────────────  │  FastAPI worker(s)         │
│  ┌──────────────────────┐  │                      │                            │
│  │  Redis (worker mode) │  │  PUBLISH/SUBSCRIBE   │  ─ /lives/bundle reads     │
│  │  HASH per host       │  │ ──────────────────▶  │    state cache (+version)  │
│  │  INCR version key    │  │                      │  ─ /admin/tiktok/ws        │
│  └──────────────────────┘  │                      │    forwards δ to clients   │
│  ┌──────────────────────┐  │                      │  ─ /public/tiktok/ws       │
│  │  In-process (dev)    │  │  in-process events   │    forwards sanitized δ    │
│  │  dict[host, state]   │  │ ──────────────────▶  │  ─ /lives/{handle}/snapshot│
│  │  dict[host, version] │  │                      │    on-demand resync        │
│  └──────────────────────┘  │                      └────────────────────────────┘
└────────────────────────────┘
```

### Strong consistency: per-host version

- **Server**: each time a state delta is applied for host `h`,
  atomically `version[h] += 1`. In Redis: `INCR tiktok:lives:version:<h>`.
  In-process: `versions[h] += 1` under a `threading.Lock` shared with the
  state mutation.
- **Publish**: every delta carries `{host, version, patch}`.
- **Bundle response**: each per-host slice is wrapped as
  `{version, data: <existing summary fields>}` so client primes its
  `versionByHost` from the bundle.
- **Client receive**:
  - If `delta.version == versionByHost[h] + 1` → apply patch.
  - If `delta.version <= versionByHost[h]` → discard (already seen).
  - If `delta.version > versionByHost[h] + 1` → **gap detected** →
    request snapshot for `h` over WS (`{type:"request-snapshot",handles:[h]}`).
- **Snapshot reply**: `{type:"snapshot", host, version, data}` →
  client overwrites that host's slice + version.
- **Reconnect**: WS open → client sends `{type:"request-snapshot",handles:[<all>]}`
  for every host it cares about. Server returns a snapshot for each.

Version is monotonic per host, never resets except on a deliberate
server-side reset (host removed + re-added). Across server restarts:
Redis is the truth. In-process resets to 0; clients holding higher
versions detect a gap and resync.

### Two channels for two surfaces

- `tiktok:lives:delta:admin` — full delta payload, every host
- `tiktok:lives:delta:public` — same delta, but **filtered** through
  `_PUBLIC_SUMMARY_FIELDS` + `last_broadcasts[:1]` before publish.
  Sanitization happens at PUBLISH time, not at SUBSCRIBE time, so any
  worker subscribing to the public channel gets pre-sanitized data —
  no risk of an admin-shaped field accidentally landing on a public
  client.

The pre-publish sanitizer is the same `_pick` already used by
`get_public_lives_summary`; we extract it into a reusable helper.

### Cold-start / fallback

- Bundle endpoint with empty cache: falls back to the existing SQL
  fan-out, populates cache, returns with version=1.
- Redis unavailable in worker mode: log+degrade, return cached snapshot
  if any, otherwise SQL. WS sends `{type:"unavailable"}` and clients
  fall back to 30 s polling until reconnect.
- In-process mode: never fails (memory always available).

---

## Phase A — State-cache port + two adapters

**Files**

- `backend/ports/tiktok_state_cache.py` (new) — `TikTokStateCachePort` ABC.
- `backend/adapters/tiktok_state_cache_inproc.py` (new) — in-process impl.
- `backend/adapters/tiktok_state_cache_redis.py` (new) — Redis impl.
- `backend/api_main.py` — DI wiring: pick adapter based on `PHOVEU_BACKEND_TIKTOK_LISTENER_MODE` (in_process → inproc, worker → redis).

**Port API**

```python
class TikTokStateCachePort(ABC):
    def get(self, handle: str) -> tuple[int, dict] | None:
        """Returns (version, summary_dict) or None if uncached."""

    def set(self, handle: str, version: int, data: dict) -> None:
        """Replace the full slice (used by snapshot + cold backfill)."""

    def apply_patch(
        self, handle: str, patch: dict, *,
        publish_admin: bool = True,
        publish_public: bool = True,
    ) -> int:
        """Atomically:
          1. Merge `patch` into the cached slice (deep merge).
          2. Increment per-host version.
          3. Publish `{host, version, patch}` to admin + (sanitized) public channels.
        Returns the new version."""

    def list_versions(self) -> dict[str, int]:
        """For diagnostics / health checks."""

    def subscribe(self, channel: Literal["admin","public"]) -> AsyncIterator[dict]:
        """Pubsub for the API WS workers. Async."""
```

**Acceptance**

- `pytest backend/tests/adapters/test_tiktok_state_cache.py` covers
  both adapters with the same fixture: apply 100 patches → final state
  matches the merged result, version == 100, subscriber sees 100 messages.
- No callers wire it in yet; just primitive + DI.

**Day 1 (~half day).**

---

## Phase B — Event-driven state writes

**Files**

- `backend/adapters/persistence/tiktok_persistence.py` —
  - new `_apply_state_delta(event_type, payload, host_unique_id, ts)` helper.
  - called inline from `record_event()` after the existing `_bump_event_hour_count`.
  - dispatches by `event_type` to one of the field-update mappings (see table below).
- `backend/api_main.py` — pass the state cache adapter into `TikTokPersistenceAdapter`'s constructor.

**Event → field-update mapping**

| Event type | Patch |
|---|---|
| `gift` | `diamonds_session += dc*rc`; binary-merge `top_gifters`; `n_unique_gifters` += (first gift this session?); `n_first_time_gifters` += (no prior `tiktok_user_host_summary`?); `session_stats.n_gifts++`; `session_stats.largest_gift_diamonds = max`; `last_gift_age_s = 0`; `hourly_buckets[(now-start_of_hour).min]+=value` |
| `comment` | `session_stats.n_comments++`; if new user_id this session → `session_stats.n_unique_commenters++`; `last_comment_age_s = 0`; per-host ring buffer of recent comments → `comments_per_min_recent` *(NOT shipped to admin bundle, but used by detail page)* |
| `like` / `join` / `follow` / `share` | `session_stats.n_<type>++` |
| `live_pause` | `n_pauses++`; `last_pause_age_s = 0` |
| `envelope` | `n_envelopes_session++`; `envelope_diamonds_session += payload.diamonds` |
| `poll` (mt=2) | replace `active_poll = {title, poll_id, fresh_age_s:0}` |
| `battle_begin` | replace `active_match = {…}` |
| `battle_progress` | update `active_match.opponents[i].score` |
| `battle_end` | clear `active_match` |
| `live_started` (synthesized on connect+room_id seen) | reset session-scoped fields; set `active_room_id`, `live_started_at` |
| `live_ended` (synthesized on disconnect/timeout) | move current session into `last_broadcasts[0]`; clear session fields; clear `active_room_id` |
| `viewer_count_update` (~1/min, synthesized from periodic scrape) | set `viewer_count`; append to `viewer_history` (cap 30) |
| `member` / other ignored types | no-op (don't publish) |

**Tick task** — `tiktok_state_ticker.py` (new asyncio task started from
`api_main.py`). Every 5 s, for each host with `active_room_id != null`:

- recompute `last_*_age_s` from stored event timestamps
- decay `comments_per_min_recent` if no comments in last 60 s
- expire `active_poll` if `fresh_age_s > 60`

Publishes one consolidated patch per host. Cheap.

**Acceptance**

- `pytest backend/tests/persistence/test_record_event_state_writes.py`:
  for each event type, fire one event → assert cache state matches
  what `get_lives_summary` would return for the same dataset (i.e.
  the SQL output is the source-of-truth oracle).
- Run with `PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH=shadow` in a dev env
  for 1 hour with real listener traffic; the live state cache should
  field-for-field match `get_lives_summary(handles)` at the end.

**Day 1 PM → Day 2 AM (~half day plus buffer).**

---

## Phase C — Bundle endpoint reads from cache

**Files**

- `backend/domain/services/tiktok_service.py:get_lives_summary` —
  read from cache first; on miss, compute via SQL and `state_cache.set()`.
- `backend/domain/services/tiktok_service.py:get_lives_bundle` —
  attaches `version` to each per-host slice in the response payload.
- `backend/routes/admin/tiktok.py:lives_bundle` and the public
  equivalent — no signature change; payload shape grows a per-host
  `version` field.
- `frontend/src/modules/admin/services/tiktok.ts` — type update:
  `TikTokLiveSummary` gains an optional `version?: number` field.

**Acceptance**

- Snapshot test: `pytest test_bundle_shape_unchanged.py` compares the
  full bundle response on `main` vs branch for a fixed seeded DB.
  The only diff allowed is the per-host `version` field. Every other
  byte matches.
- With Phase 9 flag = `shadow`: bundle reads from cache, frontend
  ignores `version`. No user-visible change.
- With flag = `on`: same response, frontend primes its versionByHost.

**Day 2 (~half day).**

---

## Phase D — WS delta fan-out

**Files**

- `backend/routes/admin/tiktok.py:websocket_admin_tiktok` —
  also subscribes to `tiktok:lives:delta:admin` via the state cache
  adapter. Each message becomes a WS frame:
  ```json
  {"type":"summary-delta","host":"...","version":N,"patch":{...}}
  ```
- `backend/routes/public_tiktok.py:websocket_public_lives` —
  same pattern, subscribes to `:public` channel (already sanitized).
- New WS message types handled inbound:
  ```json
  {"type":"request-snapshot","handles":["h1","h2",...]}
  ```
  Server replies one frame per handle:
  ```json
  {"type":"snapshot","host":"h1","version":N,"data":{...}}
  ```
- Frontend hook `useTikTokLivesSocket` (new file, replacing the poll
  effect on lives page). Wraps `openTikTokWebSocket` with the
  request-snapshot / apply-delta / gap-detect logic. Returns
  `{summary: Map, version: Map, status: "live"|"reconnecting"|"polling-fallback"}`.

**Backpressure** — server WS send queue is bounded; if a client falls
behind by >100 messages, server drops the client and signals
reconnect. Reconnect triggers full resync, so no data is lost from the
client's perspective.

**Acceptance**

- `pytest backend/tests/routes/test_lives_ws_delta.py`:
  - apply patch via state cache → see WS frame on the admin channel
    within 50 ms.
  - same patch on public channel: shipping shape matches
    `_pick(patch, _PUBLIC_SUMMARY_FIELDS)`.
  - request-snapshot returns the right shape for both surfaces.
- Manual: open the admin lives page, inject a synthetic gift via a
  test endpoint, see the diamond counter update inside 1 s.

**Day 3 (full day, includes browser smoke testing).**

---

## Phase E — Client uses WS state, polling is the safety net

**Files**

- `frontend/src/modules/admin/pages/TikTokLives.tsx` — replace the
  poll-loop useEffect with `useTikTokLivesSocket()`. Keep a 5-min
  reconciliation `livesBundle()` fetch. On WS error/close, fall back
  to 30 s polling until reconnect succeeds.
- `frontend/src/modules/public/pages/PublicLives.tsx` — same pattern.

**Feature flag** — `PHOVEU_FRONTEND_TIKTOK_WS_STATE_PUSH` (env at
build time) gates the new code path. `false` keeps the polling
behavior, `true` switches to WS. Default `false` during shadow
period.

**Acceptance**

- Open both pages with flag on; verify steady-state behavior matches
  Phase 8 visually but with sub-second update latency.
- Kill the WS connection mid-session; page falls back to 30 s polling
  and reconnects when the WS comes back; reconciliation occurs.
- Multi-tab: 5 tabs of the admin page see the same delta within 1 s.

**Day 4 (~half day).**

---

## Phase F — Cleanup

- Remove `_LIVES_SUMMARY_TTL_S` and `_lives_totals_cache` (the state
  cache is fresh per-event; the SQL fan-out is only the cold-start
  path now).
- Remove the `_warm_tiktok_caches` startup task (cache populates on
  first event after listener boots; the cold-start SQL fan-out
  on first bundle request is fast enough as a backstop).
- Remove the 30 s `setInterval` polling code from the frontend (kept
  in Phase E behind the feature flag for fallback only).

**Day 4 PM.**

---

## Risk register

| Risk | Mitigation |
|---|---|
| `_apply_state_delta` diverges from `get_lives_summary` SQL — same field computed two ways | Phase B acceptance test compares cache vs SQL output. Shadow period before cutover. Snapshot test on bundle shape in Phase C. |
| Per-host write rate spikes (1k gifts/sec on a big live) overload Redis | Each event is one `HSET` + `INCR` + `PUBLISH`. Redis can do tens of thousands per second. Profile in shadow. Adapter falls back to in-process buffering if Redis falls behind. |
| WS fan-out × many tabs: each tab gets every host's delta even for hosts off-screen | The lives list page subscribes to ALL hosts; that's the design. ~80 hosts × ~1 event/sec/host × 5 tabs = ~400 msgs/sec — fine for a browser. The detail page only subscribes to its host (different WS endpoint). |
| Reconnection storm during a deploy | Stagger reconnect with exponential backoff (already in `openTikTokWebSocket`). Snapshot endpoint is cheap (one HGET per host). |
| `top_gifters` rebuild on each gift is O(N) when N = session unique gifters per host | Cap top_gifters tracking to a bounded heap (size 3) in cache. New gift only touches the heap. |
| `comments_per_min_recent` ring buffer eats memory | Bounded ring per host (60 entries = 60 ints). Negligible. |
| Worker mode without Redis | Boot fails fast with a clear error: "worker mode requires PHOVEU_REDIS_URL". |

---

## Open questions for during implementation (not blocking the plan)

- Should we use Redis Streams instead of pub/sub for delta delivery,
  to allow late-joining workers to replay missed messages? (Pub/sub
  drops unread messages.) — **default: pub/sub** since the version
  gap-detect already handles missed messages via snapshot request.
- Tick task runs in API process or listener process? — **default:
  listener**, since it has direct access to per-host state and event
  timestamps. API processes only forward.
- Should `version` reset on `live_ended`? — **default: no**, version
  is monotonic across sessions per host. Cleaner semantics for the
  client.

---

## Definition of done

1. Both `/admin/tiktok` and `/lives` (public) update card state via
   WS push within 1 s of a server-observed event, with no polling
   beyond the 5-min safety net.
2. Cold mount latency is at most as bad as Phase 8 (~800 ms p50);
   warm-state cache hit on bundle is <50 ms p50.
3. With the WS killed, both pages fall back to 30 s polling and
   reconnect cleanly.
4. With Redis killed (worker mode), the bundle endpoint falls back
   to SQL, and clients fall back to polling.
5. Snapshot-test on bundle shape passes (no unexpected fields, only
   `version` added).
6. Field-for-field parity test between state cache and
   `get_lives_summary` SQL passes after 1 h of listener traffic.

---

## Estimated effort

- Phase A: 0.5 d
- Phase B: 1 d (event mapping is detail-heavy)
- Phase C: 0.5 d
- Phase D: 1 d (WS + sanitizer + snapshot path)
- Phase E: 0.5 d
- Phase F: 0.25 d

**Total: ~3.75 days** of focused work, plus a shadow-mode soak period
between B and C of at least a day in production data.

---

## Suggested kickoff

Say "start Phase A" to begin. I'll create the port + two adapters +
tests, no callers wired. That's a complete, mergeable unit on its own
that just adds a primitive without touching any existing behavior.

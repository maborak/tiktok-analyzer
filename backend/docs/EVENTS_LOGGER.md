# TikTok Events Logger

This document describes the event capture pipeline — from TikTokLive
WebSocket subscription through DB persistence to client fan-out.
Companion to `WORKER.md` (process model) and `DB_ARCHITECTURE.md`
(table layout).

Last revised 2026-05-14.

---

## 1. What gets captured

Every event TikTok's WebCast service emits during a live broadcast,
plus a handful of synthesized lifecycle events. Per-event handlers
live in `backend/adapters/tiktok_live_client.py` (search `@client.on`).

| TikTokLive event | Internal `type` | Notes |
|---|---|---|
| `ConnectEvent` | `connect` (synthetic) | First frame after WS handshake — synthesized into a row with `message_id=None`. |
| `DisconnectEvent` | `disconnect` (synthetic) | WS dropped. Triggers state change → `DISCONNECTED`. |
| `LiveEndEvent` | `live_end` (synthetic) | TikTok signaled "stream ended." Distinct from disconnect — clean shutdown. |
| `CommentEvent` | `comment` | Chat message. Payload carries `text`. |
| `GiftEvent` | `gift` | A gift was sent. Payload: `gift_id`, `diamond_count`, `repeat_count`, recipient. Combo-merging logic applies (see §2.1). |
| `LikeEvent` | `like` | Heart taps. High-frequency — TikTok batches into `count` per envelope. |
| `FollowEvent` | `follow` | Viewer started following the creator. |
| `ShareEvent` | `share` | Viewer shared the live. |
| `JoinEvent` | `join` | Viewer entered the room. High frequency on popular lives. |
| `SubscribeEvent` | `subscribe` | Viewer subscribed (TikTok Live Subs, distinct from follow). |
| `RoomUserSeqEvent` | `viewer_count_update` (synthetic) | Per-minute viewer-count refresh. Also carries top viewers / room user list. |
| `EnvelopeEvent` | `envelope` | Red-envelope (lucky money) drop. Has `diamond_count` like gifts. |
| `EmoteChatEvent` | `emote_chat` | Emoji-only chat. |
| `PollEvent` | `poll` | Live poll posted. Has `title`, `poll_id`. |
| `QuestionNewEvent` | `question_new` | Q&A submission. |
| `LinkMicArmiesEvent` | `armies` (often promotes to `match_*`) | PK battle in progress. Side-scores arrive as army events; we promote them to match rows. |
| `LiveIntroEvent` | `live_intro` | Stream description / promotional banner change. |
| `LivePauseEvent` | `live_pause` | Creator paused stream (camera off, going AFK). |
| `(synthesized)` | `live_started` | NOT yet emitted (gap — see §6). |
| `(synthesized)` | `live_ended` | NOT yet emitted (gap — see §6). |

Roughly 18 raw event types from TikTokLive + 4-5 synthesized.
`tiktok_live_client.py` declares ~25 `@client.on(...)` handlers; the
rest are either unmapped (we drop them) or low-signal (debug logs
only).

---

## 2. The persistence pipeline

### 2.1 Single-transaction persist

Every event flows through `persist_event_full`
(`backend/adapters/persistence/tiktok_persistence.py:2067`):

```python
def persist_event_full(self, *, room_id, host_unique_id, viewer, type, payload, …) -> int:
    # 1. Dedup key from payload.message_id
    # 2. Open one DB session
    with self._get_session() as s:
        self._upsert_room_in_session(s, …)             # room metadata
        if is_postgres():
            stmt = pg_insert(TikTokEventModel)…on_conflict_do_nothing(…)
            row_id = s.execute(stmt).scalar()
            if row_id:
                self._upsert_user_host_summary(s, …)   # cross-session ledger
                self._bump_event_hour_count(s, …)      # pre-agg
                self._apply_state_delta(s, …)          # Phase 9 cache
        else:
            row = TikTokEventModel(…)
            s.add(row); s.flush()
            self._upsert_user_host_summary(s, …)
            self._bump_event_hour_count(s, …)
            self._apply_state_delta(s, …)
        s.commit()
        s.refresh(row)
        return row.id
```

Five writes, one transaction:

1. **Room upsert** — `tiktok_rooms` (room_id, host_unique_id,
   first_seen_at, last_seen_at).
2. **Event insert** — `tiktok_events`. Uses `INSERT … ON CONFLICT
   DO NOTHING` against the partial unique index
   `(room_id, message_id) WHERE message_id IS NOT NULL`. Dedup is
   free — TikTok re-sends the same message_id during WS reconnects.
3. **User-host summary upsert** — `tiktok_user_host_summary`
   (`user_id, host_unique_id, first_seen_at, last_seen_at,
   diamonds, gifts`). Used by leaderboards + first-timer detection.
4. **Event hour count bump** — `tiktok_event_hour_counts`
   (`host_unique_id, hour_bucket, n, diamonds`). Pre-agg for the
   24h diamond total + the rhythm strip.
5. **State cache delta** — Phase 9, only when state cache is wired.
   Mutates the per-host slice + publishes a delta to admin/public
   WS channels.

Atomicity: all five writes commit together. If anything raises, the
event row is rolled back AND the state-cache write is skipped
(`_apply_state_delta` is best-effort + try-wrapped to never break
the rollback).

### 2.2 Why dedup at the unique index, not at the application

TikTok's WS reconnect cursor resends events on every reconnect.
Without dedup we'd double-count gifts every time the WebSocket flapped.

Two options:
- Application-side: read `tiktok_events` to check if message_id
  exists, then INSERT. Race-prone — two threads could pass the check
  simultaneously.
- DB-side: partial unique index + `ON CONFLICT DO NOTHING`. Atomic,
  postgres handles concurrent inserts correctly.

We chose option 2. The partial index (`WHERE message_id IS NOT NULL`)
exists because synthetic events (`connect`, `disconnect`, `live_end`)
have no message_id and should always insert.

### 2.3 The `_active_match` battle-state map

In-memory dict on `TikTokService` keyed by `room_id` → `{match_id,
battle_id}`. Each event in a battle gets tagged with the current
`match_id` via this map so leaderboards can scope gifts to a specific
PK battle.

The map is populated on `armies` event (which carries a battle_id);
cleared on `match_end` event or on listener disconnect (cleanup in
`_stop_session`).

Gotcha: in-memory means `--reload` drops the state. The `match_id`
on events persisted across the reload would be NULL for events
landing right after the reload, until the next `armies` event
re-populates the map. The orphan-match closer (see §4) cleans up
matches that never got an `ended_at` due to this.

---

## 3. Event-level decisions

### 3.1 Gift combo merging

TikTok gifts can be sent in combos — one user "spamming" the same
gift produces a sequence of `GiftEvent`s with the same `message_id`
but incrementing `repeat_count`. The persist path stores ONLY the
final event (highest repeat_count) via the dedup mechanism.

Actually that's wrong — the dedup is by `(room_id, message_id)`
strictly. The first event wins. We DON'T currently capture combo
progression. Each gift envelope's `repeat_count` is the count at the
moment the event fired; we store the value but don't track combo
duration or final-vs-intermediate.

The TikTokLive lib emits one `GiftEvent` per combo COMPLETE (not per
intermediate tap). So in practice this isn't a problem — the
"final" event for a 50-gift combo arrives as a single event with
`repeat_count=50`. We persist that.

### 3.2 Per-anchor PK score capture

When two creators are in a PK battle and both happen to be tracked
by us, we record gifts from both sides via separate `tiktok_events`
rows (each room has its own listener). The `tiktok_matches` table
records the battle metadata with `opponents` JSONB carrying both
sides' user_ids.

`_opponents_from_armies_event` reads BOTH `event.armies` (1v1 battles)
AND `team_armies[].team_users[]` (multi-guest team-battle path) so
we capture multi-team battles correctly. The original implementation
read only `event.armies` and missed multi-team data on 3v3 / 4v4.

### 3.3 Monotonicity score guard

`update_match` rejects 50%+ score drops. Without this, a stray
`armies` event from a NEW battle could overwrite the previous
match's final score (TikTok sometimes re-emits old battle ids during
transition).

Implemented as a simple max-decrease percentage check at the
persist layer.

### 3.4 Comment text persistence

Comments store text in `payload->>'text'` (JSONB). Not separately
indexed; queries that filter by comment substring fall back to a
table scan on `tiktok_events WHERE type='comment'`. Acceptable
because:
- Comment text search is admin-only, infrequent.
- The result set is small (one host's session).
- The `(room_id, type)` index narrows to comments first.

If full-text comment search becomes a hot feature, add a tsvector
expression index on `payload->>'text'`.

---

## 4. Maintenance background tasks

### 4.1 Orphan-match closer

Matches that never received `match_end` (worker crashed mid-battle,
TikTok dropped the event, etc.) stay open with `ended_at IS NULL`.
The `close_orphan_matches` job sweeps every N minutes and closes
matches whose `last_seen_at` is older than 5 minutes — the
`get_active_match` filter then ignores them.

Without this, the lives-list page would show stale "in match" pills
on creators whose battle ended 30 minutes ago.

### 4.2 Pre-agg consistency

The pre-aggregate tables (`tiktok_event_hour_counts`,
`tiktok_user_host_summary`) are bumped INLINE in the persist
transaction. They're never repaired or recomputed at runtime.

If they get out of sync (e.g., a botched migration left
`tiktok_event_hour_counts.diamonds` partially backfilled), the fix
is to re-run the backfill migration. Postgres ON CONFLICT DO UPDATE
makes the backfill idempotent.

### 4.3 Worker log retention

`tiktok_worker_log` is append-only and grows ~hundreds of rows per
day per worker. No retention job today. Operationally it's harmless
(small text rows, fast index lookups) — but at multi-year scale
it'd need a TTL or partitioning.

### 4.4 Stale TikTokLive cursor

The TikTokLive lib tracks an event cursor per WS session for
reconnect replay. We don't persist this — every WS reconnect starts
fresh. Result: a few seconds of events MAY be lost if the listener
reconnects mid-flap. Dedup at the message_id level mitigates the
duplicate side; the missing-event side is harder to address without
intrusive lib patches.

---

## 5. Fan-out to clients

### 5.1 Two channels: legacy event stream + Phase 9 state deltas

Both fan-outs live alongside each other on the WS endpoint.

**Legacy event stream** (since day 1):
- Channel: `tiktok:events` (Redis pub/sub, worker → API workers).
- Payload: one envelope per raw event:
  ```json
  {"type":"gift","unique_id":"alice","room_id":"...","user_id":"...","payload":{…}}
  ```
- Consumed by the WS endpoint via `_ws_pump_from_redis` (worker
  mode) or directly via in-process listener (in-process mode).
- Forwarded to clients as-is. Client-side handlers filter by `type`
  and update the UI (e.g., the rhythm strip increments on every
  `gift`).

**Phase 9 state deltas** (Phase 9D):
- Channel: `tiktok:lives:delta:admin` + `tiktok:lives:delta:public`.
- Payload: per-host state-cache delta:
  ```json
  {"type":"summary-delta","host":"alice","version":42,"patch":{"diamonds_session":12345}}
  ```
- Pre-sanitized on the public channel (operator-only fields stripped
  at PUBLISH time).
- Consumed by the same WS endpoint via `state_delta_pump`, sent as
  `summary-delta` frames.
- Plus a `request-snapshot` / `snapshot` reply protocol for resync
  on gap detect.

### 5.2 Why two channels?

Raw events are fine-grained — one frame per atomic action. Drives
real-time UI like the rhythm strip, the in-match score animation,
the per-event toast notification.

State deltas are coarse-grained — one frame per state mutation,
already aggregated. Drives the lives-list card scoreboard, the
"top 3 gifters" chips, the running diamond total.

A client that needs BOTH (real-time event-stream feel for one host
+ rolled-up scoreboards for the list) gets both on the same WS.
Filter is type-based on the client side.

### 5.3 WS endpoint structure

`/admin/tiktok/ws` and `/public/tiktok/ws` mount three parallel
tasks per connection:

1. **`control_reader`** — inbound JSON control messages
   (`subscribe`, `request-snapshot`).
2. **Legacy event pump** — `_ws_pump_from_service` (in_process) or
   `_ws_pump_from_redis` (worker mode). Forwards
   `tiktok:events` envelopes.
3. **State delta pump** — `state_delta_pump`. Subscribes to the
   `tiktok:lives:delta:*` channel + forwards `summary-delta` frames.

All three are independent. Cancellation is per-task — closing the
WS cancels them all in the `finally` block.

### 5.4 Backpressure

The legacy event pump uses a 1000-deep async queue per connection.
On overflow, events are silently dropped (logged at WARNING). The
client's WS doesn't reconnect — it just misses events.

The state-delta pump uses the cache adapter's 100-deep per-
subscriber queue. On overflow, the subscriber is DROPPED entirely,
the iterator raises, the pump exits, the WS closes. Client
reconnects + re-requests snapshots → state catches up.

Different policies because:
- Legacy events are individual data points — losing one is annoying
  but not corrupting (the per-host aggregates are computed
  elsewhere).
- State deltas are CHANGES to a versioned state — losing one
  creates a version gap that mis-orders subsequent deltas. The
  protocol's snapshot resync is the only correct recovery.

### 5.5 Public-channel filtering

The public WS adds two filtering layers:
- The cache adapter pre-sanitizes deltas before publishing on
  `:public` (drops fields not in `_PUBLIC_SUMMARY_FIELDS`).
- The WS endpoint's `passes_filter` and the snapshot-reply handler
  enforce the public-handle-set (only `is_public=True` subscriptions
  emit anything to public viewers).

Both layers are required. Pre-publish sanitization protects deltas
from leaking via the channel; the public-handle-set check protects
private hosts from being enumerable.

---

## 6. Synthesized events (the gap)

The Phase 9 plan calls for two synthesized events that AREN'T yet
flowing through `persist_event_full`:

- **`live_started`** — fired when the listener first observes a
  `room_id` for this host. Resets all session-scoped fields in the
  state cache.
- **`live_ended`** — fired on `DisconnectEvent` or `LiveEndEvent`.
  Archives the just-finished session into `last_broadcasts[0]`,
  clears session fields.

Currently the listener-wrapper handles `ConnectEvent` /
`DisconnectEvent` / `LiveEndEvent` by:
- Logging to `tiktok_worker_log` (audit trail) ✓
- Updating `tiktok_subscriptions.is_live` + room state ✓
- NOT inserting a `tiktok_events` row with `type='live_started'` /
  `type='live_ended'` ✗

Consequence: the state cache never sees these events, so it never
resets `_gifter_totals` / `_commenter_ids` / session counters on
session boundaries. The shadow soak shows: cache fields like
`active_room_id` and `live_started_at` aren't being populated.

The bundle endpoint's overlay rule ("only overlay fields the cache
has") protects the SQL output — these fields stay SQL-driven, no
data is corrupted. But Phase E's WS-only flow can't ship until
these events are wired.

Fix shape (deferred): in `tiktok_live_client.py`'s
`ConnectEvent` / `LiveEndEvent` / `DisconnectEvent` handlers, after
the current bookkeeping, fire one synthetic event through
`record_event` with the right payload. Persist path picks it up,
state cache reacts.

---

## 7. Pros

### 7.1 Comprehensive event coverage

We capture ~18 raw TikTokLive event types. Most TikTok analytics
SaaS tools capture maybe 6-8. The detailed event-by-event log is
the primary value-add of this project vs. the alternatives.

### 7.2 Dedup is built in

`(room_id, message_id)` unique index means WS reconnect replay never
corrupts counts. Operationally invisible.

### 7.3 Read-path performance comes from pre-aggregation

`tiktok_event_hour_counts` (Phase 7) + `tiktok_user_host_summary`
(initial design) handle the dominant read queries cheaply. Without
them, the 24h diamond sum scans millions of events. With them, ~2K
rows.

### 7.4 Two-channel fan-out is the right shape

Raw events for real-time signals + state deltas for aggregations.
The two don't fight each other; clients can subscribe selectively.

### 7.5 In-transaction state mirror

The Phase 9 state cache writes are part of the persist transaction.
Either the event lands AND the cache reflects it, or neither — no
half-states where the DB row exists but the cache doesn't (or vice
versa). The state cache is genuinely a mirror, not a separate
source of truth.

---

## 8. Cons

### 8.1 Write amplification

Each event → 3-5 DB writes (event, user-host summary, hour counts,
optional state cache, optional match update). At 100 events/sec
peak, that's 300-500 writes/sec from a single host. Postgres handles
it; the cost is in transaction commit latency, which directly bounds
how many events/sec a worker can ingest.

Today's ceiling: ~250 events/sec per worker process before commits
queue. Real-world load on the busiest live we've tracked: ~80 events/sec.
Headroom is ~3x, comfortable but not infinite.

### 8.2 JSONB queries are heap-bound

The events' `payload` is JSONB. Any query that filters on
`payload->>'…'` (e.g., the 24h diamond sum used to do this) requires
a heap fetch per row. Pre-aggs fix the hot ones; ad-hoc payload
filters (admin debugging) stay expensive.

### 8.3 The synthesized events gap (§6)

`live_started` / `live_ended` aren't emitted through `record_event`,
so the state cache has incomplete session boundaries. Workaround:
the bundle endpoint's overlay rule prevents the gap from corrupting
output. But it blocks Phase 9.E (full WS push) until fixed.

### 8.4 Single ingestion process per worker

The worker is single-process. Inside it, the event executor has 4
threads (good parallelism for persistence). But at the WS layer,
each subscription's events are handled serially by one event-loop
coroutine. A burst of 500 events/sec for ONE host serializes
through one persistence pipeline.

Realistic mitigation: shard listeners across workers (each one gets
~30 hosts). That's already how `capacity` works. We can't
parallelize a single host's events without breaking the dedup +
state-cache ordering guarantees.

### 8.5 No event-level replay

Once persisted, events are immutable. There's no "replay this event
through the pipeline" command for backfilling new pre-aggs or new
state-cache fields. New aggs are seeded by one-time SQL backfill
migrations (e.g., `add_event_hour_counts_diamonds.py`); new state-
cache fields seed via `_apply_state_delta` going forward only.

If Phase 9 adds a new tracked field tomorrow, hosts that haven't
gifted today have a cache entry without that field. Frontend reads
default to "0" via nullish coalescing — acceptable; not perfect.

---

## 9. Failure modes

### 9.1 TikTokLive WS disconnect mid-event

The TikTokLive lib retries reconnect automatically. During the retry
window:
- Events are buffered by TikTok's cursor on their side.
- On reconnect, the lib re-emits buffered events.
- Our dedup eats the duplicates.

Worst case: a long disconnect (>cursor window, ~few minutes) loses
the in-window events. Rare.

### 9.2 DB write failure

`persist_event_full` raises → the event isn't persisted, the
listener's `_on_event` callback catches + logs:

```python
logger.exception(
    "Persist failed for @%s type=%s room=%r (%s: %s) — event broadcast still proceeds",
    unique_id, type, room_id, e.__class__.__name__, e,
)
```

Note "event broadcast still proceeds" — the Redis fan-out fires
even on DB failure. This is a deliberate choice: real-time UI keeps
working during a DB hiccup, at the cost of that event not appearing
in history.

### 9.3 Redis fan-out failure

If Redis is down:
- `EventPublisher` no-ops gracefully (warning log).
- Subscribers see an empty stream.
- DB persistence continues unaffected.

Recovery: when Redis comes back, fan-out resumes. Events that
happened during the outage are gone from the real-time stream
(`tiktok:events` is volatile pub/sub), but DB has them. Clients
that reconnect after the outage will see history via the bundle
endpoint.

### 9.4 State cache failure (Phase 9)

The state cache's writes are wrapped in `_apply_state_delta` with
a try/except that logs + swallows. A cache failure NEVER breaks the
DB transaction. The cache misses an event; the bundle endpoint's
overlay logic falls back to SQL for that host's fields.

### 9.5 Backpressure on the listener

If the persistence pool saturates (DB slow, network issue), the
event executor's queue grows. The TikTokLive coroutine awaits
`run_in_executor` — it'll yield to the loop but stay open. WS
continues receiving events; they pile up in the executor queue.

Limit: the 4-thread executor has no explicit queue cap. In practice
the event loop's task scheduling is the bottleneck. A persistent
DB outage would eventually OOM the worker; transient outages absorb
fine.

---

## 10. Future plans

### 10.1 Already planned

- **Wire synthetic `live_started` / `live_ended`** (§6). Unblocks
  Phase 9.E.
- **Phase 9.E** — Frontend uses WS-pushed state. Polling becomes
  safety net only.

### 10.2 Medium-term

- **Per-broadcast pre-agg table**. `tiktok_room_summary` with
  `room_id, n_gifts, n_comments, diamonds, peak_viewers`. Currently
  the `last_broadcasts` enrichment scans events per room (~200ms);
  a PK-lookup would be sub-ms. Documented in
  `~/.claude/projects/.../memory/project_pending_work.md` as STALE
  (carried two sessions).
- **Capture `GiftCollectionUpdateEvent`**. Suggested by earlier
  audit; not yet implemented. Would let us track gift catalog
  changes without a periodic full reseed.
- **Comment full-text index**. Add a tsvector expression index on
  `payload->>'text'` if comment search becomes a real workflow.

### 10.3 Speculative

- **Per-host event partitioning**. Postgres declarative
  partitioning by `host_unique_id` on `tiktok_events` would scale
  past current limits (~1M rows/day). Operational complexity goes
  up; only justified at ~10x current scale.
- **Kafka for event ingestion**. Decouple WS capture from DB
  write. Lets us run a Postgres writer + analytics writer + state-
  cache writer in parallel; survives DB outages without dropping
  the real-time stream. Substantial complexity; only at significantly
  higher scale than today's.
- **TimescaleDB hypertables** for `tiktok_events`. Auto-partitions
  by time, improves range queries, makes retention trivial. Cost:
  dialect-specific, harder ops.

---

## 11. References

- `backend/adapters/tiktok_live_client.py` — TikTokLive client
  wrapper, ~1300 lines, every `@client.on` event handler.
- `backend/adapters/persistence/tiktok_persistence.py:2067`
  `persist_event_full` — the single-transaction persist path.
- `backend/adapters/persistence/tiktok_persistence.py:_apply_state_delta`
  — Phase 9 state cache mutation (the per-event dispatcher).
- `backend/adapters/tiktok_event_bus.py` — Redis pub/sub
  publisher + subscriber.
- `backend/routes/admin/tiktok.py:ws_events` — admin WS endpoint
  with both legacy event stream and Phase 9D state delta stream.
- `backend/routes/public_tiktok.py:public_ws_events` — public WS
  endpoint, same structure with public-handle-set filtering.
- `.claude/tracking/perf/PHASE9_PLAN.md` — full Phase 9 plan
  including the per-event field-update mapping table.
- `~/.claude/projects/.../memory/project_event_emission_gaps.md` —
  events the TikTokLive lib supports but we don't emit yet for our
  hosts (Q&A, donations, subscribes).
- `docs/tikfinity-analysis.md` — static-analysis research on
  TikTok's WS protocol; useful when posting/probing breaks.

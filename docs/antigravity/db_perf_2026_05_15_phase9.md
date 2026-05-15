# Lives-page DB performance — Phase 9 deep dive
**Date:** 2026-05-15
**Branch:** `fix/euler-quota-burn`
**Scope:** `/admin/tiktok` (admin Lives list) and public `/lives`
**Result:** Cold mount **29,382 ms → 667 ms** (44× faster, −97.7%)

---

## 1. What we shipped

Four ordered phases, each measured against the same backend
(`localhost:9020`, 89 enabled subs, 1,077 rooms, 15.9 M events):

| Phase | Change | Cold mount | Warm p50 | Notes |
|------:|--------|-----------:|---------:|-------|
| 9.0   | Baseline (pre-change) | **29,382 ms** | 36.7 ms | Cache cold; `wk_diam` raw scan is the dominant cost |
| 9.1   | `wk_diam` → `tiktok_event_hour_counts.diamonds` | **1,311 ms** (−95.5%) | 40.1 ms | Single highest-leverage change |
| 9.2   | `tiktok_room_stats` table for per-room aggregates | **543 ms** (−98.2%) | 36.8 ms | 4 RED queries collapse to PK lookups |
| 9.3   | Public route `async def` + `Cache-Control: public, max-age=15` | n/a | n/a | HTTP-layer fix; absorbs concurrent viewers via CDN/browser cache |
| 9.4   | WS `seedVersions` on admin + public; cache hit/miss observability | **667 ms** | 32.1 ms | Real-time fidelity; final cache hit ratio 81%/87% |

End state: anonymous public viewers and admin operators both see
sub-second cold loads and sub-second-fresh updates via WS deltas.
The 30 s safety-net poll still runs in case the WS dies.

## 2. What the DB schema now looks like

### Pre-aggregation tables (write-time materialized aggregates)

```
tiktok_event_hour_counts
  (host_unique_id, hour_bucket)  PRIMARY KEY
   n            INTEGER  — all-type event count per host per hour
   diamonds     BIGINT   — gift diamonds (attribution-aware) per host per hour
```

```
tiktok_event_type_hour_counts                 [NEW IN PHASE 9.1 — diamonds col]
  (host_unique_id, hour_bucket, type)  PRIMARY KEY
   n            INTEGER  — count per event type per host per hour
   diamonds     BIGINT   — gift diamonds (attribution-aware) per host per hour,
                          per type. Identical to event_hour_counts.diamonds
                          when type='gift'; 0 for other types.
```

```
tiktok_room_stats                              [NEW IN PHASE 9.2]
  room_id      BIGINT       PRIMARY KEY
  diamonds     BIGINT       — total gift diamonds in this room (attribution-aware)
  n_gifts      INTEGER      — gift event count in this room (attribution-aware)
  n_comments   INTEGER      — comment event count in this room
  peak_viewers INTEGER      — MAX(payload.total) seen on viewer_count events
  last_updated_at TIMESTAMPTZ — for backfill diff + freshness checks
```

### Indexes (existing, used by the new queries)

- `ix_tiktok_event_hour_counts (host_unique_id, hour_bucket)` — PK
- `ix_tiktok_event_type_hour_counts (host_unique_id, hour_bucket, type)` — PK
- `ix_tiktok_room_stats (room_id)` — PK
- `ix_tiktok_rooms_host_first_seen (host_unique_id, first_seen_at DESC NULLS LAST)`
- `ix_tiktok_rooms_host_active (host_unique_id, last_seen_at DESC) WHERE ended_at IS NULL`
- `ix_tiktok_events_room_type_ts (room_id, type, ts DESC)` — still used for sparkline raw scan

### Write path

```
persist_event_full(room_id, host, viewer, type, payload, ...)
  ├─ _upsert_room_in_session       (debounced last_seen_at, 30s push interval)
  ├─ _upsert_viewer_in_session     (debounced, 30s)
  ├─ INSERT INTO tiktok_events     (dedup'd via partial unique index)
  ├─ _upsert_user_host_summary
  ├─ _bump_event_hour_count        — returns (diamonds_delta, gift_attributed)
  │     ├─ UPSERT tiktok_event_hour_counts        (n, diamonds)
  │     └─ UPSERT tiktok_event_type_hour_counts   (n, diamonds)
  ├─ _bump_room_stats              — uses returned attribution decision
  │     └─ UPSERT tiktok_room_stats               (diamonds/n_gifts/n_comments/peak_viewers)
  └─ _apply_state_delta            (Redis pub/sub fan-out, Phase 9B)
```

The attribution decision (`_gift_is_for_host` → `to_user.user_id ∈ {0, host's
profile_user_id}`) is computed once per event and threaded into both
bump functions, so no double cache lookup.

## 3. Why we made the choices we made

### Why pre-agg at write time, not read time

Read-path queries on `tiktok_events` over a 7-day or 30-day window
require a JSONB heap fetch per matching gift row (the index has
`room_id, type, ts` but not the payload). At 15.9 M total events and
~14 K gifts/hour, the `_week_calendar_cached.wk_diam` query was
**9.15 s** of pure heap fetching every cold cache miss. Caching the
result for 60 s helps steady-state poll cadence but every backend
restart, every TZ change, and every 60+ s idle window pays the full
cost.

By doing the multiplication-and-attribution UPSERT inline at event-
persist time, the cost moves to the write side (one extra UPSERT per
event = ~0.1 ms) and the read side becomes a tiny indexed range scan
or PK lookup. Same SQL the existing `tiktok_event_hour_counts.diamonds`
column already proved out for the 24h totals.

### Why `tiktok_room_stats` keyed on `room_id` only

The four read paths replaced (`session_diamonds`, `last_broadcasts.stats`,
`30d_averages.avg_diamonds`, `median_diamonds`) all already start from
a room-id list derived from `tiktok_rooms` (filtered by host + window).
Joining `tiktok_room_stats` on `room_id` is a PK lookup — the host
filtering happens at the rooms-table level, where the
`ix_tiktok_rooms_host_first_seen` index does the heavy lifting.

Putting `host_unique_id` in `tiktok_room_stats` would let us skip the
rooms join in some queries but adds redundant data. The current shape
matches the existing access patterns and stays normalized.

### Why `peak_viewers` uses `GREATEST` and `n_gifts`/`n_comments` use sum

- `peak_viewers` is the all-time max in this room. The TikTok viewer
  count goes up and down; the snapshot we keep is the highest seen,
  not the most recent. UPSERT-side `GREATEST(existing, new)` gives us
  that with no second query.
- `n_gifts` and `n_comments` are monotonic counts; same shape as
  `tiktok_event_hour_counts.n`.

### Why we kept `_lives_summary_hourly` on raw events

The 60-minute sparkline needs per-minute granularity. The pre-agg
table is per-hour. We measured: raw events scan for 60 min on this
data scale is **18.7 ms** — bounded enough to stay on raw events. The
auditor's 10K-rows-equals-slow estimate didn't survive the
measurement.

If sparkline granularity could drop to per-hour, a `(host, hour_bucket,
diamonds)` lookup over `tiktok_event_hour_counts.diamonds` would
deliver the same shape at 0.5 ms. Trade-off: visualization fidelity.
Not shipped.

### Why public route went `Cache-Control: public, max-age=15`

The docstring already promised this. The previous `no-store` was
overly defensive: every public summary field is in the
`_PUBLIC_SUMMARY_FIELDS` allowlist (no operator-only data ever ships),
and a 15-second leakage window after an operator flips `is_public=False`
is harmless. The win: anonymous viewers sharing a stream URL no
longer pay one RTT per tab per 30s; browsers + CDNs absorb 15s of
poll traffic each.

### Why WS `seedVersions` mattered

The `useTikTokLivesSocket` hook starts with an empty version map. On
the first connect this is fine — there's nothing to snapshot. On a
reconnect (browser sleep, network blip, worker restart) the hook's
on-connect path asks the server for snapshots of every host in its
version map — but it was empty if no deltas had arrived yet. Result:
every host's card stayed stale until either the next natural delta
arrived or the 5-minute reconcile poll fired.

Seeding the version map from the bundle response after every fetch
fixes this: the hook always knows the version of every host the page
is showing, so reconnect → snapshot-everything → fresh cards within
1 RTT.

### Why public page gets the same WS treatment

The infrastructure (`/public/tiktok/ws`, `tiktok:lives:delta:public`
Redis channel, public-handle-set filter, public field allowlist) was
already built and tested for admin. The cost of mounting the existing
hook on the public page with `audience: 'public'` is one `useEffect`
+ one merge function. Public viewers now see sub-second deltas for
diamonds, viewer count, top gifters — same fidelity as admin.

## 4. What this means for the operator

### Real-time vs polling

```
Cold start (page mount)
  → GET /lives/bundle             admin  (in-memory cache, pre-agg DB)
  → GET /public/tiktok/lives      public (Cache-Control absorbs concurrent viewers)

Steady-state real-time updates
  → WS push via Redis pub/sub     both audiences

Safety-net reconcile
  → 5 min poll                    admin, when WS is live
  → 30 s poll                     both audiences, when WS is degraded
```

### What's cached where

| Layer | What | TTL | Invalidation |
|---|---|---|---|
| Service in-memory | `_lives_summary_cache` per (tz, handle-set) | 60 s | TTL only; singleflight on miss |
| Service in-memory | `_lives_totals_cache` | 60 s | TTL only; singleflight on miss |
| Service in-memory | `_public_lives_summary_cache` per tz | 30 s | TTL only; singleflight on miss |
| Browser/CDN | `Cache-Control: public, max-age=15` | 15 s | TTL only |
| Browser/CDN | `Cache-Control: private, max-age=30` (admin bundle) | 30 s | TTL only |
| DB write-time pre-agg | `tiktok_event_hour_counts.diamonds` | live | every event UPSERTs |
| DB write-time pre-agg | `tiktok_event_type_hour_counts.diamonds` | live | every event UPSERTs |
| DB write-time pre-agg | `tiktok_room_stats` | live | every event UPSERTs |
| Redis | `tiktok:lives:state:<handle>` | indefinite | every event applies patch |
| Redis pub/sub | `tiktok:lives:delta:{admin,public}` | n/a | event stream |

### Observability

`GET /admin/tiktok/cache/stats` — operator-visible hit/miss counters:

```json
{
  "caches": [
    {"name": "lives_summary",  "hits": 26, "misses": 6, "hit_ratio": 0.812, "size": 2},
    {"name": "lives_totals",   "hits": 26, "misses": 4, "hit_ratio": 0.867, "size": 1},
    {"name": "public_summary", "hits":  2, "misses": 2, "hit_ratio": 0.5,   "size": 1}
  ]
}
```

Counters reset on process restart. Healthy steady-state ratios for a
single admin tab polling every 30 s with 60 s TTL: expected ~80%+. A
ratio below 30% means cache invalidation is racing the poll cycle
(e.g. distinct handle subsets per call) — investigate.

## 5. What any DBA can verify

### Verify the pre-agg writes are wired

```sql
-- Should show recent timestamps if the worker is up:
SELECT MAX(last_updated_at), MAX(hour_bucket) FROM (
  SELECT last_updated_at, NULL::timestamptz AS hour_bucket FROM tiktok_room_stats
  UNION ALL
  SELECT NULL::timestamptz, hour_bucket FROM tiktok_event_hour_counts
) t;
```

### Verify read-path parity (sample handle)

```sql
-- Compare pre-agg total against raw scan. Should match.
WITH preagg AS (
  SELECT SUM(diamonds) AS d FROM tiktok_event_hour_counts
  WHERE host_unique_id = 'igian_uwu' AND hour_bucket > NOW() - INTERVAL '8 days'
),
raw_scan AS (
  SELECT COALESCE(SUM(
    COALESCE((e.payload->>'diamond_count')::int, 0)
    * COALESCE((e.payload->>'repeat_count')::int, 1)
  ), 0) AS d
  FROM tiktok_events e
  JOIN tiktok_rooms r ON r.room_id = e.room_id
  JOIN tiktok_subscriptions sub ON sub.unique_id = 'igian_uwu'
  WHERE r.host_unique_id = 'igian_uwu'
    AND e.ts > NOW() - INTERVAL '8 days'
    AND e.type = 'gift'
    AND (
      sub.profile_user_id IS NULL
      OR COALESCE(e.payload->'to_user'->>'user_id', '0')
         IN ('0', sub.profile_user_id::text)
    )
)
SELECT preagg.d AS preagg_diamonds, raw_scan.d AS raw_diamonds,
       (preagg.d = raw_scan.d) AS exact_match
FROM preagg, raw_scan;
```

Same shape for `tiktok_room_stats`:

```sql
SELECT rs.diamonds, rs.n_gifts, rs.n_comments, rs.peak_viewers,
  (
    SELECT COUNT(*) FILTER (WHERE e.type='gift'
      AND (sub.profile_user_id IS NULL
           OR COALESCE(e.payload->'to_user'->>'user_id','0')
              IN ('0', sub.profile_user_id::text)))
    FROM tiktok_events e
    JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
    WHERE e.room_id = rs.room_id
  ) AS raw_n_gifts
FROM tiktok_room_stats rs
JOIN tiktok_rooms r ON r.room_id = rs.room_id
WHERE r.host_unique_id = 'igian_uwu'
ORDER BY r.first_seen_at DESC LIMIT 5;
```

### Verify the indexes are picked

```sql
EXPLAIN ANALYZE
SELECT host_unique_id,
       ((NOW() AT TIME ZONE 'America/Lima')::date
        - (hour_bucket AT TIME ZONE 'America/Lima')::date) AS day_offset,
       COALESCE(SUM(diamonds), 0) AS d
FROM tiktok_event_hour_counts
WHERE host_unique_id = ANY(ARRAY['igian_uwu', 'eulertam'])
  AND hour_bucket > NOW() - INTERVAL '8 days'
GROUP BY 1, 2;
```

Expected: `Index Scan using <PK or composite>` — total time <5 ms.

### Re-run backfill any time

The migrations are idempotent. Re-running them is safe and catches
the gap between the migration timestamp and the worker restart:

```bash
python database/migrations/add_event_type_hour_counts_diamonds.py
python database/migrations/add_tiktok_room_stats.py
```

The second one upserts `(diamonds, n_gifts, n_comments, peak_viewers,
last_updated_at)` from a grouped scan over `tiktok_events`. Inline
bumps from `_bump_room_stats` keep it warm; backfill covers anything
the inline path missed (e.g. events ingested before the worker
picked up the new write code).

## 6. Lessons we learned

### The auditor's estimate of "10K heap fetches" matched the data scale...

...but the actual wall-clock for the 60-min sparkline scan (18.7 ms)
turned out to be far less painful than the auditor's pessimistic
prediction. The real cold-mount killer was `wk_diam` (9.15 s) — an
8-day window. **Measure before optimizing.**

### Worker-process vs uvicorn-reload divergence

The dev backend runs uvicorn with `--reload`, which catches code
changes automatically. But the worker (`cli.py system tiktok run-listener`)
is a separate process that does NOT reload. After shipping any write-
path change, the worker must be manually restarted before new events
populate the new write paths. Backfills are idempotent and bridge
that gap.

### The "fix it for admin" / "fix it for public" gap

Several issues had the *infrastructure* already shipped for admin
but not consumed on the public page (WS, audience flag, public-set
filter). The fix was 30 lines of frontend wiring — not architectural
work. Always audit "what's already shipped for the other audience"
before scoping new work.

### Pre-aggregation is the right answer when:

- The read pattern is bounded (per-host, per-room, per-time-window)
- The write pattern is high-volume but each write touches at most a
  few rollup rows (cost is O(1) per event, not O(N))
- The aggregate is associative (sum, max, count)
- Attribution / filtering can be decided at write time from row state
  + a small adjacent lookup

It is NOT the right answer for:

- Ad-hoc analytical queries with unknown predicates
- Per-minute granularity over long windows (cardinality explodes)
- Aggregates that depend on cross-row state at read time (medians
  over arbitrary windows can be tricky; we pre-aggregate per-room
  totals and let `PERCENTILE_CONT` work over the tiny per-room result)

## 7. What's next (not shipped)

The four-phase plan is complete. Open follow-ups that would extend
the wins further:

- **CTE blind spot for long-running rooms** — every CTE that bounds
  rooms by `first_seen_at > NOW() - INTERVAL '...'` excludes rooms
  that started before the window but are still emitting events. Add
  `OR ended_at IS NULL` to the CTE predicate in all three places
  (`_week_calendar_cached`, `_lives_summary_hourly`,
  `_daily_buckets_cached`). Low impact today (no marathon broadcasters
  in the current install) but worth fixing before scale.

- **SQLite-path dialect guards** — `_lives_summary_hourly` and
  `_daily_buckets_cached.else` branch use Postgres-only syntax
  (`ANY(:hs)`, `NOW()`, `INTERVAL`). They error if anyone ever
  runs this on a SQLite dev database with multiple handles. Either
  add a `_is_postgres()` early-return or rewrite with `IN (...)`
  + `datetime('now')`.

- **`get_lives_totals.events_per_min`** — `COUNT(*)` over the last
  5 minutes is currently 4.4 ms (cheaper than predicted). If it
  ever shows up in a flame graph, replace with `SUM(n)` from the
  current partial hour of `tiktok_event_hour_counts`.

- **Backfill cadence** — for tables that accumulate slowly
  (`tiktok_room_stats`), schedule a periodic backfill (cron / Phoveus
  event) to catch any inline bumps that got dropped on a worker
  crash. Daily is fine.

## Appendix: perf snapshot files

All snapshots live in `.claude/tracking/perf/`. Use the perf CLI to
diff:

```bash
python cli.py system tiktok perf compare \
  .claude/tracking/perf/phase-9-baseline.json \
  .claude/tracking/perf/phase-9.4-final.json
```

| Snapshot | Captured | Cold | Warm p50 |
|---|---|---:|---:|
| phase-9-baseline.json       | 20:42 | 29,382 ms | 36.7 ms |
| phase-9.1-wk_diam-preagg.json | 20:57 | 1,311 ms  | 40.1 ms |
| phase-9.2-room_stats.json   | 21:18 | 543 ms    | 36.8 ms |
| phase-9.4-final.json        | 21:35 | 667 ms    | 32.1 ms |

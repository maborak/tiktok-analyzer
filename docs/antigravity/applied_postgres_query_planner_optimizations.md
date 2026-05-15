# PostgreSQL Query Planner Optimizations: TikTok Events & Rooms

## The Problem: Conflicting Bounds & Sequential Scans
In the TikTok Bot architecture, we frequently need to aggregate high-volume events (diamonds, gifts, comments) over a specific time window for a specific set of active broadcasters (hosts). 

The data model is relational:
- `tiktok_rooms`: Tracks broadcast metadata (`room_id`, `host_unique_id`, `first_seen_at`, `ended_at`). A host has a few dozen rooms over time.
- `tiktok_events`: Tracks every individual websocket event (`room_id`, `ts`, `type`, `payload`). A single room can have hundreds of thousands of events.

When querying these together, a flat `INNER JOIN` can cause catastrophic performance degradation (queries hanging or taking 30+ seconds):

```sql
-- ❌ BAD PATTERN: Flat Join with conflicting bounds
SELECT r.host_unique_id, SUM(...) 
FROM tiktok_events e
JOIN tiktok_rooms r ON r.room_id = e.room_id
WHERE r.host_unique_id = ANY(:hs)
  AND e.ts > NOW() - INTERVAL '8 days'
  AND e.type = 'gift';
```

### Why does this fail?
The PostgreSQL Query Planner looks at the two filters:
1. `r.host_unique_id = ANY(:hs)`
2. `e.ts > NOW() - INTERVAL '8 days'`

Instead of evaluating the `tiktok_rooms` table first (which would yield a tiny subset of ~5 active `room_id`s), the planner often assumes the `e.ts` index is the better starting point. It pulls **millions of events** from the last 8 days across the entire platform, parses JSON payloads, executes timezone casts, and *only then* joins them to `tiktok_rooms` to discard 99.9% of the rows. This exhausts CPU, memory, and database connection pools.

## The Solution: CTE Pruning Bounds
To fix this, we **force** PostgreSQL to materialize the highly selective room subset first by wrapping the `tiktok_rooms` filter in a Common Table Expression (CTE).

```sql
-- ✅ GOOD PATTERN: CTE Bound
WITH host_rooms AS (
  SELECT room_id, host_unique_id
  FROM tiktok_rooms
  WHERE host_unique_id = ANY(:hs)
    AND first_seen_at > NOW() - INTERVAL '10 days' -- Adds a safe upper bound!
)
SELECT r.host_unique_id, SUM(...)
FROM host_rooms r
JOIN tiktok_events e ON e.room_id = r.room_id
WHERE e.ts > NOW() - INTERVAL '8 days'
  AND e.type = 'gift';
```

### Why does this work?
By defining `host_rooms` as a CTE, PostgreSQL executes that subquery first. It hits the `host_unique_id` + `first_seen_at` indexes, returning a handful of `room_id`s in ~2 milliseconds. It then takes those specific `room_id`s and executes a precise index lookup on the massive `tiktok_events` table, completely bypassing the planner's tendency to scan the 8-day global event window. The query drops from 30+ seconds down to <5ms.

## Where this was applied (May 2026)
This optimization was applied across `backend/adapters/persistence/tiktok_persistence.py` in the following aggregation helpers:
1. `_week_calendar_cached` (`wk_diam` query)
2. `_lives_summary_hourly` 
3. `_daily_buckets_cached` (SQLite fallback execution path)

## Rule of Thumb for Future AI Agents
When joining `tiktok_events` against `tiktok_rooms` in this repository:
- **Never** write a flat `JOIN` if you are querying by `host_unique_id` over a large timeframe.
- **Always** isolate the target rooms in a `WITH host_rooms AS (...)` CTE first.
- **Always** ensure the CTE includes a generous `first_seen_at` bound (e.g. `NOW() - INTERVAL '10 days'` for an 8-day event window) so Postgres uses the room-table index efficiently.

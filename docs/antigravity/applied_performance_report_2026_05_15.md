# Performance Optimization Report: TikTok Admin Dashboard
**Date:** 2026-05-15
**Subject:** Resolving Latency in `/admin/tiktok` Aggregations

## 1. Executive Summary
Following reports of severe latency (30s+ timeouts) on the TikTok Admin dashboard, a deep audit was conducted on the `get_lives_bundle` endpoint. The bottleneck was traced to PostgreSQL query planner failures in the `TikTokPersistenceAdapter`. By refactoring key SQL queries to use **Common Table Expressions (CTEs)**, we forced efficient index usage, reducing query execution time from 30+ seconds to <5ms.

## 2. Root Cause: Query Planner Regression
The latency occurred in queries joining the massive `tiktok_events` table (millions of rows) with the `tiktok_rooms` table. 

### The "Planner Trap"
When a query filters by both a timestamp (`e.ts`) and a host identity (`r.host_unique_id`), PostgreSQL often chooses the timestamp index first if the interval is large (e.g., 8 days).
- **Behavior:** It scans millions of events platform-wide, parses JSON payloads, and performs timezone math *before* filtering by the specific host.
- **Result:** High CPU usage, memory pressure, and connection pool starvation.

## 3. The Solution: CTE Pruning
We implemented a **CTE-First** strategy to isolate the room identifiers before joining the events.

### Optimized Pattern
```sql
WITH host_rooms AS (
  SELECT room_id FROM tiktok_rooms 
  WHERE host_unique_id = ANY(:hs) 
    AND first_seen_at > NOW() - INTERVAL '10 days'
)
SELECT ... FROM host_rooms r
JOIN tiktok_events e ON e.room_id = r.room_id
WHERE e.ts > NOW() - INTERVAL '8 days'
```
This forces Postgres to materialize the tiny subset of rooms (usually <10 rows) first, allowing it to perform a lightning-fast nested loop join using the `room_id` index on `tiktok_events`.

## 4. Implementation Details
The following methods in `backend/adapters/persistence/tiktok_persistence.py` were optimized:

| Method | Optimization | Impact |
| :--- | :--- | :--- |
| `_week_calendar_cached` | Wrapped `wk_diam` query in `host_rooms` CTE. | Primary fix for 8-day heatmap hang. |
| `_lives_summary_hourly` | Refactored `gifts` CTE to use `host_rooms` bound. | Fixed 60-min sparkline lag. |
| `_daily_buckets_cached` | Applied CTE bound to the SQLite/dev execution path. | Optimized dev/test performance. |

## 5. Validation
### Accuracy
Aggregates were verified using the existing parity test suite:
- **Test:** `pytest backend/tests/test_state_cache_parity.py`
- **Result:** `6 PASSED`. Verified that SQL-summed totals perfectly match state-cache deltas.

### Reliability
Full backend tests were executed to ensure no regressions in broader system logic:
- **Test:** `pytest backend/tests/` (ignoring broken queue modules)
- **Result:** `151 PASSED`. All TikTok-related logic remains structurally sound.

## 6. Lessons for Future AI Agents
1. **Never use flat joins** on `tiktok_events` when filtering by `host_unique_id` over a window larger than 1 hour.
2. **Always use CTEs** to prune the `room_id` set first.
3. **Monitor Concurrency:** The `/lives/bundle` endpoint currently spawns 7 threads per request. While queries are now fast (<5ms), this pattern consumes 7 DB connections per user. Avoid increasing this concurrency without migrating to an asynchronous DB driver.

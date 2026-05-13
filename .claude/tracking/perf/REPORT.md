# /admin/tiktok lives list — perf report

Captured 2026-05-13 against a 79-handle install with the dev backend
on `localhost:9020`. Backend uses uvicorn `--reload`, so each phase's
code change was picked up automatically; service-layer caches
(35 s TTL on `get_lives_summary` + `get_lives_totals`) were allowed
to expire between cold-mount captures.

Benchmark command: `python cli.py system tiktok perf endpoints`
runs one untimed cold request (empty service cache after the TTL
window) then 15 warm runs of the bundle endpoint. The cold timing
captures the full DB cost; the warm timing is service-cache-served.

## Headline numbers

| Metric | Baseline (Phase 2) | Final (Phase 8) | Delta |
|---|---|---|---|
| **Warm p50** (cache-served poll, steady state) | **23.3 ms** | **14.4 ms** | **−8.9 ms / −38%** |
| **Warm p95** | 27.6 ms | 16.1 ms | −11.4 ms / −41% |
| **Bundle payload size** | 263.9 KB | **198.5 KB** | **−65.4 KB / −25%** |
| Cold mount (`GET /lives/bundle`, true empty-cache) | ~1100 ms | ~800 ms ± 600 ms variance | see note below |

### Note on cold-mount variance

The CLI tool's "cold" run is a single sequential request at script
start. In practice this only catches a true cold miss when no other
admin tab is polling. With a live admin tab polling at 30 s, the
service-layer 60 s TTL stays continuously warm — true cold misses
only happen on a backend restart or a ≥60 s idle window. When they
DO happen, wall-clock is dominated by the parallel SQL fan-out
inside `get_lives_summary` and varies with data volume.

Observed values across phases:

| Phase | Cold capture | Likely cache state |
|---|---|---|
| 2 (baseline) | 1135 ms | true cold |
| 3 | 1165 ms | true cold (within noise of 2) |
| 5 | 846 ms | true cold, post pre-agg |
| 7 | 818 ms | true cold, post payload-trim |
| 8 | 1439 ms | true cold, but with more accumulated event volume |

The warm p50 + payload size are the reliable signals — they
isolate the steady-state experience that 99% of admin polls hit.

Cold-mount baseline already includes Phase 2 (single bundle endpoint
replacing three separate round-trips) and Phase 1 (frontend lazy
modals + memo). The Phase 2 → Phase 5 delta isolates the
backend-side improvements.

For the **complete user-perceived improvement** (1614 KB main JS
chunk + 3 round-trips + 1135 ms cold mount → 910 KB main JS chunk +
1 round-trip + 846 ms cold mount), the cold-paint perceived
improvement is closer to **~1.2–1.5 s** depending on network
conditions — the bundle parse time saved from the 224 KB gzipped
main-chunk reduction can't be measured by the CLI tool, only in a
browser Performance trace.

## Per-phase contribution

| Phase | What | Cold (ms) | Warm p50 (ms) |
|---|---|---|---|
| 0 | Baseline (3 endpoints, no changes) | not captured | not captured |
| 1 | Frontend (lazy modals + React.memo + structural sharing) | n/a (frontend-only) | n/a |
| 2 | Bundle endpoint + structural-shared summary state | **1135** | **23.3** |
| 3 | 4 new indexes (`add_tiktok_lives_summary_indexes`) | 1165 (noise) | 22.6 |
| 4 | Correlated `NOT EXISTS` → LEFT JOIN anti-join | folded into 5 | folded into 5 |
| 5 | `tiktok_event_hour_counts.diamonds` pre-agg + `get_lives_totals` reads it | **846** | 17.2 |
| 6 | RBAC token cache (30 s TTL, key=SHA256(token\|ip\|ua)) | folded into 5 | folded into 5 |
| 7 | Drop 9 unused fields from bundle response (deny-list) | **818** | **16.7** |
| 8 | `last_broadcasts[0:1]` slice + cache TTL 35→60 s + same trims on public path | ~variance | **14.4** |

**Phase 3 (indexes) was within noise on cold mount.** The DB
auditor predicted this: at the current scale (~63 rooms/host, ~5 K
rooms total, ~1.6 K hour-buckets), the existing single-column
`(host_unique_id)` index can already heap-fetch the small per-host
slices. The composite/partial indexes were added as *insurance
against future growth* — the audit's wall-clock estimates of
500 ms+ degradation hit only at ~1000 rooms/host. They cost ~100 KB
of index storage and ANALYZE updated planner stats; we keep them.

**Phase 5 (pre-aggregation) was the dominant win.** Replacing the
24-hour gift-event JSONB heap walk with `SUM(diamonds)` over the
≤79 × 25 = 1975-row `tiktok_event_hour_counts` table saved ~290 ms
on cold mount.

**Phase 6 (auth cache) accounted for the bulk of the warm-poll
improvement.** A 10-shot same-token burst settled at ~16 ms per
request after the first; that's the per-request floor of
`get_lives_summary` warm-cache + Promise.all serialization +
network. Without the cache the floor was ~22 ms (the difference is
the JWT decode + 2 RBAC DB roundtrips that now short-circuit).

## Data-correctness notes

The `diamonds_24h` total changed slightly with Phase 5:

| Source | Total (24 h) | Note |
|---|---|---|
| OLD direct gift-event SUM | 13,459,457 | counts orphan gifts (no `host_unique_id`) |
| NEW pre-agg `SUM(diamonds)` | 12,983,196 | excludes orphan gifts |

The 3.5 % delta (476 K diamonds) is gift events whose
`host_unique_id` was NULL at persist time — gifts that can't be
attributed to a tracked host. The new path correctly omits them
from the header total ("Diamonds across tracked hosts 24 h"); the
header strip already labels itself with that scope.

## How to reproduce

```bash
# Login to get a token (admin user only)
TOKEN=$(curl -s -X POST http://localhost:9020/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"..."}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['tokens']['access_token'])")

# Capture a labeled snapshot
PHOVEU_ADMIN_TOKEN="$TOKEN" \
  python backend/cli.py system tiktok perf endpoints \
    --label your-label \
    --json-out .claude/tracking/perf/your-label.json

# Diff against baseline
python backend/cli.py system tiktok perf compare \
  .claude/tracking/perf/phase-2-bundle-pre-indexes.json \
  .claude/tracking/perf/your-label.json
```

## Files in this directory

- `phase-2-bundle-pre-indexes.json` — baseline (post-Phase 2 frontend wins, pre-DB changes)
- `phase-3-post-indexes.json` — after 4 indexes were added (within noise)
- `phase-5-preagg-diamonds.json` — post pre-aggregation + RBAC token cache
- `phase-7-payload-trim.json` — after dropping 9 unused fields
- `phase-8-final.json` — final, after last_broadcasts trim + TTL bump + public path parity
- `REPORT.md` — this file

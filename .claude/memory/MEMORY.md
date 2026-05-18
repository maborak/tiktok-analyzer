# Project Memory

Repo-level persistent context for the TikTok-bot project. The `Last
Session` block below is rewritten on every `/session-commit` run.

---

## Last Session
Date: 2026-05-18
Branch: fix/euler-quota-burn
Summary: Tier 1–3 service-layer caching across ~20 TikTok read methods + L2 DB-backed cache tables for `host_calendar` and `room_stats` + `warm-caches` CLI daemon + every fix from the multi-agent `/audit` (2 CRITICAL, 5 HIGH, 8 MEDIUM, 5 LOW). Headline: `host_calendar` 2,880 ms → 4 ms L2 hit (~700×); singleflight collapses 10-thread stampede on `list_enigma_viewers` from ~7,500 ms to ~288 ms wall-clock. Commit `1442f4a`.

### Remaining Work

- **Push the branch** — `fix/euler-quota-burn` has 10+ unpushed commits including the big `1442f4a` audit-fix commit. `git push origin fix/euler-quota-burn` when ready.
- **Restart uvicorn + run new migrations** — the API process needs a restart to pick up the cache code. Two new migrations (`add_tiktok_host_calendar_cache.py`, `add_tiktok_room_stats_cache.py`) need running before the cache tables exist. Both idempotent. Also re-run any worker-mode `run-listener` since persistence layer changed.
- **Optional: start `./build.sh cache-warmer` daemon** — proactively populates the `tiktok_host_calendar_cache` L2 table so the first page-load of any host is already warm. Without it, the API lazily fills the cache on first hit (still <1 s per host on cold L2).
- **CTE long-running-room blind spot** — `_week_calendar_cached`, `_lives_summary_hourly`, `_daily_buckets_cached` bound rooms by `first_seen_at > NOW() - INTERVAL '...'`. Add `OR ended_at IS NULL` for marathon broadcasters. Low impact today.
- **SQLite dialect guards** — `_lives_summary_hourly` + `_daily_buckets_cached` else-branch use PG-only syntax (`ANY(:hs)`, `NOW()`, `INTERVAL`) without `_is_postgres()` early-return. Errors on SQLite dev DB with multi-handle queries.
- **2v2 / 3v3 rival rendering** — multiple rival anchors sharing a team duplicate the team score across `<BattlerCard>`s. Group by `team_id`, render one card per rival team with members inside.
- **Popular-Vote / anonymous-recipient gift attribution** — multi-guest battles where `to_user.user_id=0` and `team_id` is absent can't be attributed per-anchor. Defer until operator need emerges. (STALE — fifth session.)
- **UI features pending from earlier sessions**: viewer-count sparkline (RoomUserSeqEvent), live captions panel, polls widget, Q&A inbox, stream-uptime panel (LivePauseEvent/LiveUnpauseEvent). Backend capture only — frontend rendering surface still missing.
- **WAF-probe modal verification** — probe-debug pipeline complete. Pending: trigger a refresh on a WAF-blocked handle and confirm the "Recent probe events from worker_log" panel populates.

---

## Key files

| Path | Why it matters |
|------|---------------|
| `backend/domain/services/tiktok_service.py` | Central TikTok service; service-level 10s cache for `get_lives_summary`. |
| `backend/adapters/persistence/tiktok_persistence.py` | All TikTok DB reads/writes; 60s caches for `daily_buckets` + `week_calendar`; orphan-match closer; monotonicity score guard. |
| `backend/adapters/tiktok_live_client.py` | TikTokLive WS handlers; `_opponents_from_armies_event` reads both 1v1 and multi-guest paths. |
| `backend/cli/commands/system/tiktok.py` | `run-listener` CLI entry for worker mode. |
| `frontend/src/modules/admin/pages/TikTokLives.tsx` | Lives index card grid + page-level gifter modal + listener-status card. |
| `frontend/src/modules/admin/pages/TikTokLiveDetail.tsx` | Per-host deep page; in-progress PK card with animated scores + top donors; scope chips. |
| `frontend/src/modules/admin/components/TikTokGifterModal.tsx` | Cross-context gifter modal. Responsive Gifts tab (table on `md+`, cards below). |
| `frontend/src/modules/admin/components/TikTokMatchEventsModal.tsx` | Past-match detail modal. |
| `client/electron/tiktok-bridge.ts` | Electron-side TikTok chat POST. |
| `dev.sh` | Local-dev supervisor; `--timeout-graceful-shutdown 5` for uvicorn reloads. |

## Slash commands

| Command | Purpose |
|---------|---------|
| `/session-commit` | Wrap up the session — commit uncommitted work, update this file + CHANGELOG. |
| `/sync-all` | Refresh tracking docs + agent factual sections against current code. |

## Agents

| Agent | Scope |
|-------|-------|
| `core/session-commit` | Session wrap-up (release-engineer role). |
| `project/ai-slop-detector` | Audit text for AI-fluff patterns. |
| `project/frontend-dark-mode-auditor` | Catch explicit `dark:*` traps that fight the framework's auto-inversion. |
| `project/frontend-responsive-auditor` | Catch responsive layout issues. |
| `project/ux-designer` | UX review on user-facing surfaces. |

---

# Project Memory

Repo-level persistent context for the TikTok-bot project. The `Last
Session` block below is rewritten on every `/session-commit` run.

---

## Last Session
Date: 2026-05-15
Branch: fix/euler-quota-burn
Summary: Lives-list cold-mount overhauled from 29.4 s to 667 ms (44×) via `tiktok_room_stats` write-time pre-agg, `wk_diam` switched to `tiktok_event_hour_counts.diamonds`, public route `async def` + `Cache-Control: public, max-age=15`, WS `seedVersions` on reconnect, and `GET /admin/tiktok/cache/stats` hit/miss observability. Doc at `docs/antigravity/db_perf_2026_05_15_phase9.md`.

### Remaining Work

- **Restart `run-listener` worker + re-run `add_tiktok_room_stats.py`** — the worker (PID 57440, started before this session) still runs the old persistence code, so `_bump_room_stats` doesn't fire on new events. Reads work (backfill in place); the idempotent backfill re-run bridges the gap after worker restart. Worker is user-controlled; I won't restart it.
- **Multi-agent audit of Phase 9 implementation** — user's NEXT request after commit. Review the new write path (`_bump_room_stats` + tuple return from `_bump_event_hour_count`), WS hook `seedVersions`, public route async + cache-header change, singleflight, and migration safety for missed bugs / regressions.
- **CTE long-running-room blind spot** — `_week_calendar_cached`, `_lives_summary_hourly`, `_daily_buckets_cached` all bound rooms by `first_seen_at > NOW() - INTERVAL '...'`. Add `OR ended_at IS NULL` to cover marathon broadcasters. Low impact today, important before scale.
- **SQLite dialect guards** — `_lives_summary_hourly` + `_daily_buckets_cached` else-branch use Postgres-only syntax (`ANY(:hs)`, `NOW()`, `INTERVAL`) without `_is_postgres()` early-return. Errors on a SQLite dev DB with multi-handle queries.
- **2v2 / 3v3 rival rendering** — multiple rival anchors sharing a team duplicate the team score across `<BattlerCard>`s. Group by `team_id`, render one card per rival team with members inside.
- **Popular-Vote / anonymous-recipient gift attribution** — multi-guest battles where `to_user.user_id=0` and `team_id` is absent can't be attributed per-anchor. Defer until operator need emerges. (STALE — fourth session.)
- **UI features pending from earlier sessions**: viewer-count sparkline (RoomUserSeqEvent), live captions panel, polls widget, Q&A inbox, stream-uptime panel (LivePauseEvent/LiveUnpauseEvent). Backend capture only — frontend rendering surface still missing.
- **WAF-probe modal verification** — probe-debug pipeline complete (worker_log persistence + modal UI). Pending: trigger a refresh on a WAF-blocked handle and confirm the "Recent probe events from worker_log" panel populates.

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

# Project Memory

Repo-level persistent context for the TikTok-bot project. The `Last
Session` block below is rewritten on every `/session-commit` run.

---

## Last Session
Date: 2026-05-13
Branch: main
Summary: Lives-list page perf overhaul (single `/lives/bundle` endpoint, pre-agg diamonds, RBAC token cache, 4 new indexes, NOT EXISTS rewrite, payload trim, public path parity) plus UI polish on heatmaps, calendar tz handling, landing page, and a written plan for Phase 9 (WebSocket-pushed live state).

### Remaining Work

- **Phase 9 — WebSocket-pushed live state**. Plan at `.claude/tracking/perf/PHASE9_PLAN.md`. Locked decisions: both deployment modes (in-process + worker), both surfaces (admin + public), day-by-day rollout with `PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH={off,shadow,on}` flag, strong consistency via per-host monotonic version + gap-detect snapshot resync. Six phases A→F (~3.75 d focused + 1 d shadow soak). User said "start Phase A" to begin. **Kickoff item next session.**
- **2v2 / 3v3 rival rendering** — when multiple rival anchors share a team, each `<BattlerCard>` currently shows the same team score (duplicated). Group by `team_id` and render one card per rival team with member list inside.
- **Popular-Vote / anonymous-recipient gift attribution** — multi-guest battles where `to_user.user_id=0` and `team_id` is absent (e.g. battle #3103) can't be attributed per-anchor. Possible workaround: diff team scores between consecutive `armies` events to identify which side received each gift. Defer until a real operator need emerges. (STALE — third session carrying this.)
- **Per-broadcast pre-aggregate table** — small `tiktok_room_summary` (`room_id, n_gifts, n_comments, diamonds, peak_viewers`) updated on event-insert would drop the `last_broadcasts` enrichment scan from ~200ms to a PK lookup. Phase 5 of this session shipped the *hourly* version (`tiktok_event_hour_counts.diamonds`) — the per-room rollup is still pending and is a smaller follow-on. (STALE — second session carrying this.)
- **UI features pending from earlier sessions** (per `~/.claude/projects/.../memory/project_pending_work.md`): viewer-count sparkline (RoomUserSeqEvent), live captions panel, polls widget, Q&A inbox, stream-uptime panel (LivePauseEvent/LiveUnpauseEvent). Backend capture only — frontend rendering surface still missing.
- **WAF-probe modal verification** — probe-debug pipeline implementation is complete (worker_log persistence + modal UI). Pending: trigger a refresh on a WAF-blocked handle (e.g. `xiomyespinoza20`) and confirm the modal "Recent probe events from worker_log" panel populates after restart. Smallest task in the pending pool.

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

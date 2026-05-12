# Project Memory

Repo-level persistent context for the TikTok-bot project. The `Last
Session` block below is rewritten on every `/session-commit` run.

---

## Last Session
Date: 2026-05-11
Branch: main
Summary: First full commit of the TikTok-bot module on top of the Phoveus framework — backend listener pipeline, frontend admin UI, Electron client, plus Tier 1+2 perf optimization, per-anchor PK score capture, monotonicity score guard, orphan-match closer, and tooling (.claude/, dev.sh, build.sh).

### Remaining Work

- **ETag/304 on `/admin/tiktok/lives/summary`** — Tier 3 perf item. Saves bandwidth + parse cost on every poll. Needs frontend 304 handling in `livesSummary()`. (Persistence + service caches already in place; this only adds the last edge.)
- **2v2 / 3v3 rival rendering** — when multiple rival anchors share a team, each `<BattlerCard>` currently shows the same team score (duplicated). Group by `team_id` and render one card per rival team with member list inside.
- **Popular-Vote / anonymous-recipient gift attribution** — multi-guest battles where `to_user.user_id=0` and `team_id` is absent (e.g. battle #3103) can't be attributed per-anchor. Possible workaround: diff team scores between consecutive `armies` events to identify which side received each gift. Defer until a real operator need emerges.
- **Per-broadcast pre-aggregate table** — Tier 2 follow-on. A small `tiktok_room_summary` table (`room_id, n_gifts, n_comments, diamonds, peak_viewers`) updated on event-insert would drop the `last_broadcasts` enrichment scan from ~200ms to a primary-key lookup. Worth doing only if the `tiktok_event_hour_counts` model proves sustainable in production.
- **Sync-all command not yet exercised** — `.claude/commands/core/sync-all.md` was adapted to this repo's structure but never run. First invocation should be against a relatively clean state so the diff is small.

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

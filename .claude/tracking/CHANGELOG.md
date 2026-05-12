# Changelog

All notable changes to this project will be documented here.
Format: https://keepachangelog.com/en/1.0.0/

---

## [Unreleased] — 2026-05-11

> Commit: `aa74d65` (`initial`) — 99 files / +51,618 / −19. Captures
> the full TikTok-bot module on top of the Phoveus framework scaffold.

### Added — Backend (TikTok module)

- **Listener pipeline**: hexagonal TikTok module — `adapters/tiktok_live_client.py`, `adapters/persistence/tiktok_persistence.py`, `ports/tiktok_live.py`, `ports/tiktok_persistence.py`, `domain/services/tiktok_service.py`, `routes/admin/tiktok.py`. Reads TikTokLive WebSocket events (gift, comment, like, join, follow, share, viewer_count, match_*, envelope, etc.) and persists them with full hexagonal isolation.
- **Worker mode**: separate listener-pool process via `cli/commands/system/tiktok.py run-listener`. API runs `passive=True`; events fan out through Redis `tiktok:events`. In-process mode preserved via `PHOVEU_BACKEND_TIKTOK_LISTENER_MODE` env var.
- **Match-update score guard**: monotonicity check in `update_match` rejects 50%+ score drops to prevent stray events from a new battle overwriting the prior match's final.
- **Multi-team battle data extraction**: `_opponents_from_armies_event` reads both `event.armies` (1v1 path) AND `team_armies[].team_users[]` (multi-guest team-battle path) for authoritative per-anchor scores.
- **Orphan-match closer**: background maintenance task back-fills `ended_at` on matches the listener didn't cleanly close.
- **Pre-aggregated hour counts**: `tiktok_event_hour_counts` table + write-side counter for cheap 24h rhythm-strip reads (saves ~700ms on warm).
- **14 migrations**: `add_tiktok_tables`, `add_tiktok_worker_registry`, `add_subscription_live_cache`, `add_event_message_id`, `add_event_hour_counts`, `add_favorite_gifters`, `add_favorite_gifters_notify`, `add_notifications`, `add_user_host_summary`, `add_worker_control_log`, `dedupe_existing_events`, `drop_caption_rank_events`, `optimize_tiktok_indexes`, `tz_aware_tiktok_timestamps`. All idempotent `CREATE/ALTER IF NOT EXISTS`.

### Added — Frontend (`/admin/tiktok`)

- **Lives index**: scoreboard cards with per-host enrichment — viewers + sparkline, diamonds, battles W-L, gifts, comments, joins, follows, envelope sub-line, 60-min sparkline, 7-day mini-heatmap, momentum tags, vs-typical chip, silence detector, active-poll chip.
- **Per-host detail** (`/admin/tiktok/$handle`): broadcast selector, calendar heatmap, daily aggregate mode, brushed range mode, chart, in-progress PK card (animated scores, top donors of THIS battle, rival monitor pills, teammate row in multi-team), past battles, top gifters / comments tabs with scope chip ("All time", "May 7 · 4 broadcasts", "Selected range", etc.).
- **Gifter detail modal**: scope toggle + banner; tabs for Gifts (responsive cards on mobile, table on desktop), Comments, Relationships, Matches; in-modal `+ Add to monitor` for the gifter.
- **Match events modal**: side-balance bar, side gifters split, top donors unified, animated score deltas, head-to-head tab, activity log, score timeline.
- **Common gifters** + **Favorite gifters** tables, **Global gifters** view, **Notifications center** with per-host channels.
- **Electron client detection**: `window.api?.sendComment` runtime check enables composer UI only in the Electron app.

### Added — Electron client (`client/`)

- Standalone npm project at repo root. Loads framework's web UI; exposes `window.api` via context-bridge preload.
- `electron/tiktok-bridge.ts` — calls TikTok `webcast/room/chat/` from a hidden BrowserWindow with the host's authenticated session.
- `electron/web-request-hooks.ts` — CSP strip + CORS rewrite + CSRF preflight forge + `bytedance://` protocol cancel on the partition's webRequest.
- `electron/sign-broker.ts` — sign-server bridge.

### Added — Tooling

- `dev.sh` — local-dev supervisor (backend / frontend / worker / client) with state in `.dev/`. `--timeout-graceful-shutdown 5` baked into the uvicorn launch line so a hung lifespan no longer blackholes `/health`.
- `build.sh` — multi-service build helper.
- `.claude/agents/` — `core/session-commit.md` + 4 project agents (ai-slop-detector, frontend-dark-mode-auditor, frontend-responsive-auditor, ux-designer).
- `.claude/commands/` — `core/session-commit.md`, `core/sync-all.md` (copied from amazon-watcher and adapted to this repo's structure).
- `client/.gitignore` — Electron-specific.

### Changed — Framework wiring

- `backend/api_main.py` — TikTok service wiring in `initialize_services`; `passive=True` flag from `PHOVEU_BACKEND_TIKTOK_LISTENER_MODE`; orphan-match closer + RBAC seeding in the background maintenance loop.
- `backend/routes/main.py` + `backend/routes/admin/__init__.py` — DI dispatch for `tiktok_service`.
- `backend/domain/entities/config_registry.py` — new TikTok config keys (listener mode, scrape intervals, worker capacity, etc.).
- `backend/database/__init__.py` — register TikTok models.
- `backend/config.py` — TikTok env-bootstrap defaults.
- `backend/requirements.txt` — TikTokLive, betterproto, async deps.
- `frontend/package.json` — ECharts, recharts, TanStack additions.
- `frontend/src/components/sidebar/Sidebar.tsx` — TikTok nav group.
- `frontend/src/routes/_app/admin.tsx` + `frontend/src/routes/_app/admin/tiktok/*.lazy.tsx` — TanStack routes.

### Tooling — `.gitignore`

- Added `oldi/` (legacy backup checkout)
- Added `.claude/settings.local.json` (per-machine permission allow-list)
- Added `**/node_modules/` (generic — covers `client/`)
- Added `dist-electron/`, `dist-ssr/`

---

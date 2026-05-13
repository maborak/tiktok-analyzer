# Changelog

All notable changes to this project will be documented here.
Format: https://keepachangelog.com/en/1.0.0/

---

## [Unreleased] — 2026-05-13

> Commit: `ae13809` — 42 files / +3,321 / −820. Lives-list page perf
> overhaul plus UI polish across the TikTok feature. Steady-state warm
> poll p50: **23.3 → 14.4 ms (−38 %)**. Bundle payload: **264 → 199 KB
> (−25 %)**. Main JS chunk (gzip): **488 → 264 KB (−46 %)**.

### Backend

- **`GET /admin/tiktok/lives/bundle`** collapses the prior three-call
  fan-out into one round-trip; killed the duplicate `list_subscriptions()`
  the old `/lives/summary` handler made on every cold mount.
  `GET /lives` retained as cheap subs-only for 5 other consumers
  (`routes/admin/tiktok.py:182-235`, `domain/services/tiktok_service.py`).
- **Pre-aggregated diamonds**: new `tiktok_event_hour_counts.diamonds`
  column. `get_lives_totals` reads `SUM(diamonds)` from the pre-agg
  (~1.9 K rows) instead of scanning gift events for 24 h (millions of
  rows + JSONB heap walk). Migration:
  `database/migrations/add_event_hour_counts_diamonds.py`.
- **4 new indexes** (CONCURRENTLY, idempotent): `tiktok_rooms`
  host+active partial, host+first_seen, `tiktok_events` room+type+ts,
  `tiktok_worker_log` JSONB host expression. Migration:
  `database/migrations/add_tiktok_lives_summary_indexes.py`.
- **Correlated `NOT EXISTS` → LEFT JOIN anti-join** in
  `_lives_summary_unique_and_session_stats` so Postgres can choose
  Hash Anti Join instead of N subplans per gifter.
- **RBAC token cache** in `AuthPersistenceAdapter` (30 s TTL,
  SHA256(token|ip|ua) key) — short-circuits the 3–4 DB roundtrips
  per authenticated request after the first hit.
- **Service-cache TTLs** bumped 35 → 60 s so the 30 s poll cycle
  hits warm cache with headroom.
- **Bundle response trims**: 9 fields the React grid never reads
  dropped via `_BUNDLE_OMIT_SUMMARY_FIELDS` deny-list;
  `last_broadcasts` sliced to `[0:1]`. Same trims mirrored on the
  public path via the `_PUBLIC_SUMMARY_FIELDS` allowlist.

### Frontend

- **`SubscriptionCard` memoized**; row handlers `useCallback`-wrapped
  with the row passed directly (no inline arrow closures). Structural
  sharing on `summary` state preserves per-host object identity across
  polls when JSON unchanged → only changed cards re-render.
- **Lazy modals**: `TikTokGifterDetailModal` (carries ~692 KB of
  echarts) and `TikTokAddLiveModal` migrated to `React.lazy` +
  Suspense across all 4 consumers (lives page, public lives,
  common-gifters table, favorite-gifters table).
- **`/lives/bundle` integration**: two useEffects collapsed into one
  bundle call. Public path got the same structural-sharing fix in
  `PublicLives.tsx`.
- **`WeekHeatmap`** in lives list refactored to a single-row 7-cell
  strip with weekday letter inside each cell, sky-blue intensity ramp,
  inset-ring borders; paired with a dashed "no activity" placeholder
  in the activity row's 50/50 grid.
- **New shared `TikTokDailyHeatmap30`** (calendar-style 30-day
  heatmap, sky-blue palette) used by gifter-detail and timeline tabs.
- **New public `/lives` route** + landing page at `/`. Old public
  lives content moved out of `/`.
- **Timezone selector**: UTC offsets in option labels, DST-aware
  sorting. Calendar grid now built in active page tz (anchored via
  `partsInZone(now, tz)` + fake-UTC stepping) so cells line up with
  backend-bucketed data instead of browser-local.
- **Calendar click**: single-broadcast day keeps `dayWindow` set so
  the chart re-fetches with day bounds (previously fell back to full
  broadcast extent and showed wrong totals across midnight).

### Tooling / Docs

- **`python cli.py system tiktok perf endpoints / compare`**
  benchmark CLI (`backend/cli/commands/system/perf.py`). Cold-miss
  timing + 15-run warm batch, JSON snapshot + colored diff.
- **5 perf snapshots** under `.claude/tracking/perf/` (Phase 2
  baseline → Phase 8 final) plus `REPORT.md` with per-phase table.
- **`PHASE9_PLAN.md`**: full plan for the WS-pushed live state
  rollout (replaces the 30 s poll). Locked decisions: both
  deployment modes, both surfaces, day-by-day rollout, strong
  consistency via per-host monotonic version + snapshot resync.
- **`CLAUDE.md`** gained 5 new subsections under TikTok module:
  bundle endpoint, pre-agg diamonds, RBAC token cache, index
  coverage, perf CLI.
- **`api-performance-auditor.md`** agent: hot-endpoints list updated
  for the bundle endpoint.

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

# tiktok-bot

A TikFinity-style desktop tool, built as a module on a custom Phoveus
SaaS framework (FastAPI backend + React/TanStack frontend, hexagonal
architecture). Reads TikTok live events into a UI and posts comments
back into chat as the logged-in user.

```
backend/    Phoveus FastAPI backend
            └─ tiktok module:
               domain/entities/tiktok_models.py
               domain/services/tiktok_service.py
               ports/tiktok_persistence.py + tiktok_live.py
               adapters/persistence/tiktok_persistence.py
               adapters/tiktok_live_client.py
               database/tiktok/models.py
               database/migrations/add_tiktok_tables.py
               routes/admin/tiktok.py

frontend/   Phoveus web UI (Vite + React + TanStack Router)
            └─ tiktok module:
               modules/admin/services/tiktok.ts
               modules/admin/pages/TikTokLives.tsx
               routes/_app/admin/tiktok/index.lazy.tsx
               sidebar entry under "TikTok"

client/     Electron desktop client. Loads the framework's web UI in a
            BrowserWindow and exposes window.api.* for posting. The web
            UI auto-detects the runtime and shows the chat composer
            only when window.api.sendComment is present.

docs/       tikfinity-analysis.md — research that informed the
            posting architecture (fetch() against /webcast/room/chat/,
            CSP strip + CORS rewrite + CSRF preflight forge).

oldi/       previous MVP (kept as porting source; safe to delete).
```

## Run it

From the repo root:

```sh
./build.sh dev          # backend (FastAPI) + frontend (Vite)
./build.sh client       # Electron desktop client (assumes dev is running)
./build.sh prod         # framework frontend prod build
./build.sh client:dmg   # build distributable .dmg of the Electron client
./build.sh status       # env state
./build.sh help
```

## Two ways to use the app

**Browser (read-only)** — open `http://localhost:5173` in any browser
after `./build.sh dev`. Log in with your Phoveus user. Sidebar →
TikTok → Lives. You can subscribe to `@usernames`, see real-time event
streams, browse stats, etc. **Posting comments is not available** —
it requires the desktop client.

**Desktop client (full access)** — `./build.sh client` launches the
Electron app. It loads the same web UI but with `window.api.*`
exposed. Posting widgets light up. To post:

1. Click **Login to TikTok** in the Lives page → a TikTok login
   window appears (inside the Electron app, not your browser). Log
   in (QR is fastest). Cookies persist in `persist:tiktok` partition.
2. Subscribe to a `@user` who's currently live → the chat composer
   appears in their row.
3. Type → Send. The comment posts via `fetch()` to TikTok's webcast
   chat API from inside the user's authenticated session.

## Architecture (one-liner)

- **Read pipeline** (TikTokLive) is server-side. One async task per
  enabled subscription. Multi-tenant friendly. Events go to Postgres
  AND to a WebSocket fan-out for real-time UI.
- **Write pipeline** (chat posting) is client-side, in Electron. Must
  run on the user's machine with their TikTok session and residential
  IP. The framework backend never touches TikTok directly for writes.

## Reference

- `CLAUDE.md` — Phoveus framework architecture and conventions (read
  this first when editing).
- `docs/tikfinity-analysis.md` — why we send chat the way we do.

## Notes / caveats

- TikTokLive uses EulerStream as a sign server for the read pipeline.
  Free tier is fine for dev; production scale needs a paid key.
- The Electron client uses Electron's bundled Chromium and runs on the
  user's machine with their residential IP — TikTok's anti-bot is
  forgiving when requests come from real users with real cookies, and
  TikTok's own JS in the page handles request signing for us.
- TikTok ToS prohibits automated commenting. Use your own account,
  accept the ban risk.

## Tracking framework upstream

To pull future framework updates into this project:

```bash
git remote add framework /Users/wilmeradalid/code/maborak/framework
git fetch framework
git merge --allow-unrelated-histories framework/main
```

Resolve conflicts in the brand strings and env prefix as needed.

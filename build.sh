#!/usr/bin/env bash
# tiktok-bot orchestrator. Runs the framework + the Electron client.
#
#   ./build.sh dev      backend (FastAPI) + frontend (Vite)
#                       both reload on change. Open http://localhost:5173
#                       in any browser to use the read-only web view.
#   ./build.sh client   start the Electron desktop client. Loads the
#                       running framework web UI and adds TikTok-side
#                       capabilities (login, posting). Run ./build.sh dev
#                       in another terminal first.
#   ./build.sh prod     framework prod build (frontend → static; backend
#                       runs from gunicorn/uvicorn under whatever process
#                       manager you choose).
#   ./build.sh client:dmg  build distributable .dmg of the Electron client.
#   ./build.sh worker   run the TikTokLive listener pool as a separate
#                       worker process (so API restarts don't drop active
#                       battle/connection state). Requires the API to run
#                       with PHOVEU_BACKEND_TIKTOK_LISTENER_MODE=worker.
#   ./build.sh status   what's set up and what's not.
#   ./build.sh help     this message.

set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

C_BLUE="\033[1;36m"; C_YEL="\033[1;33m"; C_RED="\033[1;31m"; C_GRN="\033[1;32m"; C_RST="\033[0m"
say()  { printf "\n${C_BLUE}==> %s${C_RST}\n" "$*"; }
ok()   { printf "${C_GRN}✓ %s${C_RST}\n" "$*"; }
warn() { printf "${C_YEL}! %s${C_RST}\n" "$*" >&2; }
die()  { printf "${C_RED}✗ %s${C_RST}\n" "$*" >&2; exit 1; }

# ── prereqs ──────────────────────────────────────────────────────────

ensure_backend_venv() {
  if [ ! -d "$ROOT/backend/.venv" ]; then
    say "Creating Python venv at backend/.venv"
    command -v python3 >/dev/null || die "python3 not found in PATH"
    python3 -m venv "$ROOT/backend/.venv"
  fi
  # shellcheck disable=SC1091
  source "$ROOT/backend/.venv/bin/activate"
  if [ ! -f "$ROOT/backend/.venv/.deps-installed" ] \
     || [ "$ROOT/backend/requirements.txt" -nt "$ROOT/backend/.venv/.deps-installed" ]; then
    say "Installing backend Python deps"
    pip install -q -r "$ROOT/backend/requirements.txt"
    touch "$ROOT/backend/.venv/.deps-installed"
  fi
}

ensure_frontend_deps() {
  if [ ! -d "$ROOT/frontend/node_modules" ] \
     || [ "$ROOT/frontend/package.json" -nt "$ROOT/frontend/node_modules/.deps-installed" ]; then
    say "Running npm install in frontend/"
    ( cd "$ROOT/frontend" && npm install --silent )
    touch "$ROOT/frontend/node_modules/.deps-installed"
  fi
}

ensure_client_deps() {
  if [ ! -d "$ROOT/client/node_modules" ] \
     || [ "$ROOT/client/package.json" -nt "$ROOT/client/node_modules/.deps-installed" ]; then
    say "Running npm install in client/"
    ( cd "$ROOT/client" && npm install --silent )
    touch "$ROOT/client/node_modules/.deps-installed"
  fi
}

# ── status ───────────────────────────────────────────────────────────

cmd_status() {
  say "Status"
  command -v python3 >/dev/null && ok "python3 present" || warn "python3 missing"
  command -v npm     >/dev/null && ok "npm present"     || warn "npm missing"
  [ -d "$ROOT/backend/.venv" ] && ok "backend/.venv present" || warn "backend/.venv missing (./build.sh dev will create)"
  [ -d "$ROOT/frontend/node_modules" ] && ok "frontend/node_modules present" || warn "frontend/node_modules missing"
  [ -d "$ROOT/client/node_modules" ] && ok "client/node_modules present" || warn "client/node_modules missing (./build.sh client will install)"
}

# ── dev (framework backend + frontend) ──────────────────────────────

cmd_dev() {
  command -v python3 >/dev/null || die "python3 required"
  command -v npm     >/dev/null || die "npm required"

  ensure_backend_venv
  ensure_frontend_deps

  BACKEND_PID=
  cleanup() {
    if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
      say "stopping backend (pid $BACKEND_PID)"
      kill "$BACKEND_PID" 2>/dev/null || true
      wait "$BACKEND_PID" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT INT TERM

  say "Starting backend → http://localhost:8000"
  ( cd "$ROOT/backend" && exec "$ROOT/backend/.venv/bin/uvicorn" api_main:app --reload ) &
  BACKEND_PID=$!
  sleep 1

  say "Starting frontend (Vite) → http://localhost:5173 — Ctrl+C to stop both"
  ( cd "$ROOT/frontend" && npm run dev )
}

# ── tiktok listener worker ──────────────────────────────────────────

cmd_worker() {
  command -v python3 >/dev/null || die "python3 required"
  ensure_backend_venv
  say "Starting TikTok listener worker"
  warn "Make sure the API is running with PHOVEU_BACKEND_TIKTOK_LISTENER_MODE=worker"
  ( cd "$ROOT/backend" && exec "$ROOT/backend/.venv/bin/python" cli.py system tiktok run-listener )
}

# ── client (Electron app pointing at the running framework) ─────────

cmd_client() {
  command -v npm >/dev/null || die "npm required"
  ensure_client_deps
  say "Starting Electron client (loads http://localhost:5173)"
  ( cd "$ROOT/client" && npm run dev )
}

# ── prod ────────────────────────────────────────────────────────────

cmd_prod() {
  command -v npm >/dev/null || die "npm required"
  ensure_frontend_deps
  say "Building framework frontend"
  ( cd "$ROOT/frontend" && npm run build )
  ok "Static assets in frontend/dist/. Run uvicorn (or gunicorn) on backend/api_main.py for the API."
}

cmd_client_dmg() {
  command -v npm >/dev/null || die "npm required"
  ensure_client_deps
  say "Packaging Electron client into .dmg"
  ( cd "$ROOT/client" && npm run package:mac )
  DMG=$(ls -1t "$ROOT/client/release"/*.dmg 2>/dev/null | head -1 || true)
  [ -n "$DMG" ] && ok "Output: $DMG" || die "package:mac finished but no .dmg appeared"
}

# ── usage / dispatch ────────────────────────────────────────────────

usage() {
  cat <<EOF
Usage: ./build.sh <command>

  dev          Run framework backend + frontend with hot reload.
  client       Run Electron client (requires dev to be running in another terminal).
  prod         Build framework frontend for production.
  client:dmg   Build distributable .dmg of the Electron client.
  worker       Run the TikTok listener pool as a standalone worker process.
  status       Show env state.
  help         This message.
EOF
}

mode="${1:-}"
case "$mode" in
  dev)         cmd_dev ;;
  client)      cmd_client ;;
  prod)        cmd_prod ;;
  client:dmg)  cmd_client_dmg ;;
  worker)      cmd_worker ;;
  status)      cmd_status ;;
  help|-h|--help|"") usage ;;
  *) usage; exit 1 ;;
esac

#!/usr/bin/env bash
# dev.sh — local-dev supervisor for the tiktok-bot stack.
#
# Manages:
#   backend   — FastAPI / uvicorn (the API; default 9020, matches
#               frontend/.env VITE_API_BASE_URL).
#   frontend  — Vite dev server (default 5173).
#   worker    — TikTokLive listener pool (`python cli.py system tiktok
#               run-listener`). Optional; required when
#               PHOVEU_BACKEND_TIKTOK_LISTENER_MODE=worker (it is).
#   client    — Electron desktop client. Optional; needs a display.
#
# State lives in `.dev/`. PID + log + resolved-port snapshot per service
# so subsequent `status` / `stop` / `restart` calls don't need flags.
#
# Usage: ./dev.sh -h
#
# Compatibility note: macOS ships bash 3.2 — this script avoids
# associative arrays and case-modifying expansions for that reason.

set -uo pipefail   # NOT -e: we want to surface failures with our own
                   # error formatter rather than exiting the whole
                   # script silently on a probe miss.

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

STATE_DIR="$ROOT/.dev"
mkdir -p "$STATE_DIR"

# ── colours ────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RST=$'\033[0m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'
  C_BLU=$'\033[34m'; C_MAG=$'\033[35m'; C_CYA=$'\033[36m'
else
  C_RST=""; C_DIM=""; C_BOLD=""; C_RED=""; C_GRN=""
  C_YEL=""; C_BLU=""; C_MAG=""; C_CYA=""
fi

say()  { printf "%s==>%s %s\n" "$C_BOLD$C_BLU" "$C_RST" "$*"; }
ok()   { printf "%s✓%s %s\n" "$C_GRN" "$C_RST" "$*"; }
warn() { printf "%s!%s %s\n" "$C_YEL" "$C_RST" "$*" >&2; }
err()  { printf "%s✗%s %s\n" "$C_RED" "$C_RST" "$*" >&2; }
die()  { err "$*"; exit 1; }

upper() { echo "$1" | tr '[:lower:]' '[:upper:]'; }

# ── service registry ───────────────────────────────────────────────────
#
# All four services declared upfront. Add/remove is one line in each
# small lookup function below.

ALL_SERVICES="backend frontend worker client"
DEFAULT_SERVICES="backend frontend"
OPTIONAL_SERVICES="worker client"

# Default port per service (0 = service doesn't bind a port).
default_port_for() {
  case "$1" in
    backend)  echo 9020 ;;
    frontend) echo 5173 ;;
    worker)   echo 0 ;;
    client)   echo 0 ;;
    *)        echo "" ;;
  esac
}

# Working directory.
svc_dir_for() {
  case "$1" in
    backend|worker) echo "$ROOT/backend" ;;
    frontend)       echo "$ROOT/frontend" ;;
    client)         echo "$ROOT/client" ;;
    *)              echo "" ;;
  esac
}

# Per-service log-prefix tint.
svc_color() {
  case "$1" in
    backend)  echo "$C_CYA" ;;
    frontend) echo "$C_MAG" ;;
    worker)   echo "$C_YEL" ;;
    client)   echo "$C_BLU" ;;
    *)        echo "" ;;
  esac
}

is_known_service() {
  case "$1" in
    backend|frontend|worker|client) return 0 ;;
    *) return 1 ;;
  esac
}

is_known_optional() {
  case "$1" in
    worker|client) return 0 ;;
    *) return 1 ;;
  esac
}

# ── persisted port resolution ─────────────────────────────────────────
#
# Resolution priority (highest → lowest):
#   1. --ports flag                       (PORTS_FLAG_<SVC>)
#   2. caller env var                     (BACKEND_PORT etc.)
#   3. last persisted port                (PERSISTED_<SVC>_PORT)
#   4. default

PORT_STATE="$STATE_DIR/ports.env"

load_ports_state() {
  if [ -f "$PORT_STATE" ]; then
    # shellcheck disable=SC1090
    . "$PORT_STATE"
  fi
}

save_ports_state() {
  {
    for s in $ALL_SERVICES; do
      p="$(get_port "$s")"
      [ "$p" = "0" ] && continue
      echo "PERSISTED_$(upper "$s")_PORT=$p"
    done
  } >"$PORT_STATE"
}

get_port() {
  s="$1"
  cache_var="RESOLVED_PORT_$(upper "$s")"
  cached="$(eval "echo \${$cache_var:-}")"
  if [ -n "$cached" ]; then
    echo "$cached"; return 0
  fi
  default="$(default_port_for "$s")"
  if [ "$default" = "0" ]; then
    eval "$cache_var=0"; echo 0; return 0
  fi
  # 1. --ports flag
  flag_var="PORTS_FLAG_$(upper "$s")"
  v="$(eval "echo \${$flag_var:-}")"
  if [ -n "$v" ]; then eval "$cache_var=$v"; echo "$v"; return 0; fi
  # 2. caller env
  env_var="$(upper "$s")_PORT"
  v="$(eval "echo \${$env_var:-}")"
  if [ -n "$v" ]; then eval "$cache_var=$v"; echo "$v"; return 0; fi
  # 3. persisted
  pers_var="PERSISTED_$(upper "$s")_PORT"
  v="$(eval "echo \${$pers_var:-}")"
  if [ -n "$v" ]; then eval "$cache_var=$v"; echo "$v"; return 0; fi
  # 4. default
  eval "$cache_var=$default"
  echo "$default"
}

validate_port() {
  p="$1"; s="${2:-?}"
  case "$p" in
    *[!0-9]*|"") die "Invalid port '$p' for $s — must be integer." ;;
  esac
  if [ "$p" -lt 1 ] || [ "$p" -gt 65535 ]; then
    die "Port $p out of range for $s."
  fi
}

validate_port_uniqueness() {
  seen=""
  for s in $ALL_SERVICES; do
    p="$(get_port "$s")"
    [ "$p" = "0" ] && continue
    case " $seen " in
      *" $p:"*)
        other="$(echo "$seen" | tr ' ' '\n' | grep "^$p:" | head -1 | cut -d: -f2)"
        die "Port collision: $s and $other both want :$p."
        ;;
    esac
    seen="$seen $p:$s"
  done
}

# ── pid/state helpers ─────────────────────────────────────────────────

pidfile()  { echo "$STATE_DIR/$1.pid"; }
logfile()  { echo "$STATE_DIR/$1.log"; }
metafile() { echo "$STATE_DIR/$1.meta"; }

# Returns: pid (live) | "" (dead or absent — cleans stale pidfile)
read_pid() {
  f="$(pidfile "$1")"
  if [ ! -f "$f" ]; then echo ""; return 0; fi
  pid="$(cat "$f" 2>/dev/null || true)"
  if [ -z "$pid" ]; then echo ""; return 0; fi
  if kill -0 "$pid" 2>/dev/null; then
    echo "$pid"
  else
    rm -f "$f"
    echo ""
  fi
}

# Returns the LISTEN-side pid bound to a TCP port, or empty.
pid_on_port() {
  p="$1"
  [ "$p" = "0" ] && { echo ""; return 0; }
  lsof -nP -iTCP:"$p" -sTCP:LISTEN -t 2>/dev/null | head -1
}

# Walks a process's child tree (uvicorn-reload child, npm's vite child).
collect_descendants() {
  parent="$1"
  kids="$(pgrep -P "$parent" 2>/dev/null || true)"
  for k in $kids; do
    collect_descendants "$k"
    echo "$k"
  done
}

# ── service runners ───────────────────────────────────────────────────

backend_python() {
  if [ -x "$ROOT/backend/.venv/bin/python" ]; then
    echo "$ROOT/backend/.venv/bin/python"
  elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    echo "$CONDA_PREFIX/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    echo ""
  fi
}

ensure_backend_venv() {
  if [ -d "$ROOT/backend/.venv" ]; then
    if [ ! -f "$ROOT/backend/.venv/.deps-installed" ] \
       || [ "$ROOT/backend/requirements.txt" -nt "$ROOT/backend/.venv/.deps-installed" ]; then
      say "Installing backend Python deps into existing .venv"
      "$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
      touch "$ROOT/backend/.venv/.deps-installed"
    fi
    return 0
  fi
  if [ -n "${CONDA_PREFIX:-}" ]; then
    return 0
  fi
  command -v python3 >/dev/null 2>&1 || die "python3 not found"
  say "Creating backend/.venv (first run)"
  python3 -m venv "$ROOT/backend/.venv"
  "$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
  touch "$ROOT/backend/.venv/.deps-installed"
}

ensure_frontend_deps() {
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    command -v npm >/dev/null 2>&1 || die "npm not found"
    say "Running npm install in frontend/"
    ( cd "$ROOT/frontend" && npm install --silent )
  fi
}

ensure_client_deps() {
  if [ ! -d "$ROOT/client/node_modules" ]; then
    command -v npm >/dev/null 2>&1 || die "npm not found"
    say "Running npm install in client/"
    ( cd "$ROOT/client" && npm install --silent )
  fi
}

# Build per-service start command (printed to stdout for caller to eval).
build_start_cmd() {
  s="$1"; port="$2"
  py="$(backend_python)"
  case "$s" in
    backend)
      [ -n "$py" ] || { err "no python found for backend"; return 1; }
      # `--timeout-graceful-shutdown 5` is critical for `--reload`:
      # without it, when WatchFiles signals the child to die, any
      # background asyncio task that doesn't honor cancellation cleanly
      # (e.g. the run_background_maintenance loop, or an open Redis
      # pubsub subscription) leaves uvicorn stuck on
      #   "Waiting for background tasks to complete. (CTRL+C to force quit)"
      # The new worker is never spawned and `/health` blackholes — only
      # `dev.sh restart backend` (SIGKILL) recovers it. The 5-second
      # cap forces uvicorn to give up gracefully and respawn.
      printf 'exec "%s" -m uvicorn api_main:app --host 0.0.0.0 --port %d --reload --timeout-graceful-shutdown 5' \
        "$py" "$port"
      ;;
    frontend)
      command -v npm >/dev/null 2>&1 || { err "npm not found"; return 1; }
      printf 'exec npm run dev -- --host --port %d' "$port"
      ;;
    worker)
      [ -n "$py" ] || { err "no python found for worker"; return 1; }
      printf 'exec "%s" cli.py system tiktok run-listener' "$py"
      ;;
    client)
      command -v npm >/dev/null 2>&1 || { err "npm not found"; return 1; }
      printf 'exec npm run dev'
      ;;
    *)
      err "unknown service '$s'"; return 1
      ;;
  esac
}

# Best-effort detect this machine's LAN IPv4 address. Tries macOS
# `ipconfig getifaddr` on the active interface, falls back to Linux
# `hostname -I`, then a broad `ifconfig` parse for an RFC 1918 inet.
# Prints nothing when no LAN IP is reachable (laptop on cellular,
# no LAN interfaces up, etc.) — callers must handle that.
detect_lan_ip() {
  ip=""
  if command -v ipconfig >/dev/null 2>&1; then
    # macOS — probe likely-active interfaces in order.
    for iface in en0 en1 en2 en3; do
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      [ -n "$ip" ] && break
    done
  fi
  if [ -z "$ip" ] && command -v hostname >/dev/null 2>&1; then
    # Linux: hostname -I returns space-separated IPs.
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [ -z "$ip" ] && command -v ifconfig >/dev/null 2>&1; then
    # Generic fallback: grab the first non-loopback RFC 1918 address.
    ip="$(ifconfig 2>/dev/null | awk '
      /inet 192\.168\.|inet 10\.|inet 172\.(1[6-9]|2[0-9]|3[01])\./ {
        print $2; exit
      }
    ')"
  fi
  echo "$ip"
}

# Per-service environment overrides exported into the child process.
#
# Frontend: we inject BOTH the backend port AND a freshly-detected
# `VITE_API_BASE_URL=//<lan-ip>:<port>`. The full URL takes precedence
# over the `.env` value (Vite layers process.env on top of .env files
# at load time), so a stale baked-in IP in frontend/.env from a prior
# network — like 192.168.0.15 when the laptop has since moved to
# 192.168.0.2 — gets transparently overridden. The detection happens
# every start/restart so re-running `./dev.sh restart frontend` after
# the LAN IP changes is the one-command fix.
#
# If detection returns empty (no LAN IP — cellular only, etc.) we
# only set the port and let the bundle fall back to its own
# auto-detect logic in `frontend/src/config/env.ts`.
build_start_env() {
  s="$1"
  case "$s" in
    frontend)
      back_port="$(get_port backend)"
      lan_ip="$(detect_lan_ip)"
      if [ -n "$lan_ip" ]; then
        printf 'export VITE_API_BASE_URL="//%s:%d"\n' "$lan_ip" "$back_port"
      fi
      printf 'export VITE_API_BACKEND_PORT="%d"\n' "$back_port"
      ;;
    *) ;;
  esac
}

# ── start / stop / restart ────────────────────────────────────────────

start_service() {
  s="$1"
  port="$(get_port "$s")"
  # Some services (worker) don't bind a port — `0` is the sentinel
  # for "no port". Validate only for port-bearing services.
  if [ "$port" != "0" ]; then
    validate_port "$port" "$s"
  fi

  existing="$(read_pid "$s")"
  if [ -n "$existing" ]; then
    if [ "$port" != "0" ]; then
      ok "$s already running (pid $existing, :$port)"
    else
      ok "$s already running (pid $existing)"
    fi
    return 0
  fi

  if [ "$port" != "0" ]; then
    foreign="$(pid_on_port "$port")"
    if [ -n "$foreign" ]; then
      err "$s wants :$port but pid $foreign already holds it (foreign — not started by dev.sh)."
      err "  use 'kill $foreign' or '$0 reset' if it's a stale orphan, then retry."
      return 1
    fi
  fi

  case "$s" in
    backend|worker) ensure_backend_venv ;;
    frontend)       ensure_frontend_deps ;;
    client)         ensure_client_deps ;;
  esac

  cmd="$(build_start_cmd "$s" "$port")" || return 1
  env_block="$(build_start_env "$s")"

  log="$(logfile "$s")"
  pidf="$(pidfile "$s")"

  : > "$log"

  # Detach from this terminal: nohup + redirect + bg + disown so closing
  # the supervisor or ctrl+C-ing it doesn't kill the child.
  (
    cd "$(svc_dir_for "$s")"
    eval "$env_block"
    nohup bash -c "$cmd" >>"$log" 2>&1 < /dev/null &
    echo $! > "$pidf"
    disown || true
  )

  pid="$(cat "$pidf")"
  if ! kill -0 "$pid" 2>/dev/null; then
    err "$s failed to start (pid $pid died immediately). Tail of log:"
    tail -10 "$log" >&2 || true
    rm -f "$pidf"
    return 1
  fi

  cat >"$(metafile "$s")" <<META
PORT=$port
STARTED_AT=$(date +%s)
PID=$pid
META

  readiness="$(probe_readiness "$s" "$port" "$pid")"
  case "$readiness" in
    ready)
      if [ "$port" != "0" ]; then
        ok "$s ready (pid $pid, :$port) — $(svc_url "$s" "$port")"
      else
        ok "$s ready (pid $pid) — $(svc_url "$s" "$port")"
      fi
      ;;
    slow)
      if [ "$port" != "0" ]; then
        warn "$s started (pid $pid, :$port) but health probe still pending — tail logs to confirm"
      else
        warn "$s started (pid $pid) but readiness probe still pending"
      fi
      ;;
    failed)
      err "$s exited during startup. Tail of log:"
      tail -15 "$log" >&2 || true
      rm -f "$pidf"
      return 1
      ;;
  esac
}

probe_url() {
  s="$1"; port="$2"
  case "$s" in
    backend)  echo "http://localhost:$port/health" ;;
    frontend) echo "http://localhost:$port/" ;;
    *)        echo "" ;;
  esac
}

svc_url() {
  s="$1"; port="$2"
  case "$s" in
    backend)  echo "http://localhost:$port (api) · /health · /docs" ;;
    frontend) echo "http://localhost:$port (ui)" ;;
    worker)   echo "(no port — heartbeats via tiktok_workers)" ;;
    client)   echo "(electron window)" ;;
  esac
}

# ready | slow | failed
probe_readiness() {
  s="$1"; port="$2"; pid="$3"
  timeout="${DEV_HEALTH_TIMEOUT_S:-30}"
  url="$(probe_url "$s" "$port")"

  if [ -z "$url" ]; then
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then echo "ready"; else echo "failed"; fi
    return 0
  fi

  deadline=$(( $(date +%s) + timeout ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "failed"; return 0
    fi
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      echo "ready"; return 0
    fi
    sleep 0.5
  done
  if kill -0 "$pid" 2>/dev/null; then echo "slow"; else echo "failed"; fi
}

stop_service() {
  s="$1"
  pid="$(read_pid "$s")"
  if [ -z "$pid" ]; then
    port="$(get_port "$s")"
    if [ "$port" != "0" ]; then
      foreign="$(pid_on_port "$port")"
      if [ -n "$foreign" ]; then
        warn "$s — port :$port held by pid $foreign (foreign, not started by dev.sh). Skipping."
      fi
    fi
    say "$s — not running"
    rm -f "$(pidfile "$s")" "$(metafile "$s")"
    return 0
  fi

  descendants="$(collect_descendants "$pid" | tr '\n' ' ')"
  all_pids="$descendants $pid"

  if [ -n "$descendants" ]; then
    say "Stopping $s (pid $pid + descendants: $descendants)"
  else
    say "Stopping $s (pid $pid)"
  fi
  for p in $all_pids; do kill -TERM "$p" 2>/dev/null || true; done

  grace="${DEV_STOP_GRACE_S:-8}"
  deadline=$(( $(date +%s) + grace ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      ok "$s stopped"
      rm -f "$(pidfile "$s")" "$(metafile "$s")"
      return 0
    fi
    sleep 0.3
  done

  warn "$s did not exit in ${grace}s — SIGKILL"
  for p in $all_pids; do kill -KILL "$p" 2>/dev/null || true; done
  sleep 0.3
  rm -f "$(pidfile "$s")" "$(metafile "$s")"
  ok "$s stopped (forced)"
}

restart_service() {
  s="$1"
  stop_service "$s"
  start_service "$s"
}

# ── argument parsing ──────────────────────────────────────────────────

ACTION=""
EXPLICIT_SERVICES=""
EXPLICIT_OPTIONALS=""
WANT_ALL=0
FOLLOW_LOGS=0
SHOW_HELP=0
PORTS_RAW=""

parse_args() {
  positionals=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -h|--help)      SHOW_HELP=1 ;;
      -f|--follow)    FOLLOW_LOGS=1 ;;
      --all)          WANT_ALL=1 ;;
      --with-*)
        EXPLICIT_OPTIONALS="$EXPLICIT_OPTIONALS ${1#--with-}"
        ;;
      --ports=*)
        PORTS_RAW="${1#--ports=}"
        ;;
      --ports)
        shift
        PORTS_RAW="${1:-}"
        ;;
      --)
        shift
        for x in "$@"; do positionals="$positionals $x"; done
        break
        ;;
      --*)
        die "Unknown option '$1'. Try '$0 --help'."
        ;;
      -*)
        die "Unknown short option '$1'. Try '$0 --help'."
        ;;
      *)
        positionals="$positionals $1"
        ;;
    esac
    shift || true
  done

  # First positional = action verb (or service shorthand).
  set -- $positionals
  if [ "$#" -gt 0 ]; then
    case "$1" in
      start|stop|restart|status|tailf|logs|open|psql|reset|preflight)
        ACTION="$1"
        shift
        EXPLICIT_SERVICES="$*"
        ;;
      *)
        ACTION="start"
        EXPLICIT_SERVICES="$*"
        ;;
    esac
  else
    ACTION="status"
  fi

  # --ports — comma-separated, positional by service order.
  if [ -n "$PORTS_RAW" ]; then
    OLDIFS="$IFS"; IFS=','
    idx=0
    for raw in $PORTS_RAW; do
      svc="$(echo "$ALL_SERVICES" | awk -v i=$((idx+1)) '{print $i}')"
      if [ -z "$svc" ]; then
        IFS="$OLDIFS"
        warn "--ports has more entries than known services; ignoring '$raw'"
        break
      fi
      if [ -n "$raw" ]; then
        IFS="$OLDIFS"
        validate_port "$raw" "$svc"
        eval "PORTS_FLAG_$(upper "$svc")=$raw"
        IFS=','
      fi
      idx=$((idx+1))
    done
    IFS="$OLDIFS"
  fi
}

TARGETS=""

resolve_target_services() {
  load_ports_state

  if [ "$WANT_ALL" -eq 1 ]; then
    if [ -z "${DEV_ALL_INCLUDE_CLIENT:-}" ]; then
      TARGETS=""
      for s in $ALL_SERVICES; do
        [ "$s" = "client" ] && continue
        TARGETS="$TARGETS $s"
      done
    else
      TARGETS="$ALL_SERVICES"
    fi
    return 0
  fi

  if [ -n "${EXPLICIT_SERVICES// }" ]; then
    TARGETS="$EXPLICIT_SERVICES"
    expanded=""
    for s in $TARGETS; do
      if [ "$s" = "all" ]; then
        expanded="$expanded $ALL_SERVICES"
        continue
      fi
      if ! is_known_service "$s"; then
        die "Unknown service '$s'. Known: $ALL_SERVICES"
      fi
      expanded="$expanded $s"
    done
    # Dedupe preserving order.
    seen=":"
    uniq=""
    for s in $expanded; do
      case "$seen" in
        *":$s:"*) ;;
        *) uniq="$uniq $s"; seen="$seen$s:" ;;
      esac
    done
    TARGETS="$uniq"
    return 0
  fi

  TARGETS="$DEFAULT_SERVICES"
  for opt in $EXPLICIT_OPTIONALS; do
    if ! is_known_optional "$opt"; then
      die "Unknown --with-$opt — known optionals: $OPTIONAL_SERVICES"
    fi
    TARGETS="$TARGETS $opt"
  done
}

# ── commands ──────────────────────────────────────────────────────────

cmd_start() {
  preflight_warn_only
  for s in $TARGETS; do
    start_service "$s" || true
  done
  validate_port_uniqueness
  save_ports_state
  if [ "$FOLLOW_LOGS" -eq 1 ]; then
    cmd_tailf
  fi
}

cmd_stop() {
  for s in $TARGETS; do
    stop_service "$s"
  done
}

cmd_restart() {
  for s in $TARGETS; do
    restart_service "$s"
  done
  if [ "$FOLLOW_LOGS" -eq 1 ]; then
    cmd_tailf
  fi
}

cmd_status() {
  printf "\n%s%-10s %-20s %-8s %-10s %s%s\n" \
    "$C_BOLD" "SERVICE" "STATE" "PID" "PORT" "URL" "$C_RST"
  printf "%s%s%s\n" "$C_DIM" "──────────────────────────────────────────────────────────────────────" "$C_RST"
  for s in $ALL_SERVICES; do
    port="$(get_port "$s")"
    pid="$(read_pid "$s")"
    foreign=""
    if [ "$port" != "0" ]; then
      foreign="$(pid_on_port "$port")"
    fi

    if [ -n "$pid" ]; then
      state="${C_GRN}running${C_RST}"; pid_disp="$pid"
    elif [ -n "$foreign" ]; then
      state="${C_YEL}foreign${C_RST}"; pid_disp="$foreign"
    else
      state="${C_DIM}stopped${C_RST}"; pid_disp="-"
    fi

    if [ "$port" = "0" ]; then
      port_disp="-"
    else
      port_disp=":$port"
    fi
    url="$(svc_url "$s" "$port")"

    # %b honours the colour-escape sequences.
    printf "%-10s %-20b %-8s %-10s %s\n" \
      "$s" "$state" "$pid_disp" "$port_disp" "$url"
  done
  echo
}

cmd_tailf() {
  if [ -n "${TARGETS// }" ]; then
    svcs="$TARGETS"
  else
    svcs="$ALL_SERVICES"
  fi
  if [ "$svcs" = "all" ]; then svcs="$ALL_SERVICES"; fi

  files=""; prefixes=""
  for s in $svcs; do
    f="$(logfile "$s")"
    [ -f "$f" ] || continue
    files="$files $f"
    prefixes="$prefixes $s"
  done
  if [ -z "$files" ]; then
    warn "no log files yet — services may not have started"; return 0
  fi

  say "Tailing$prefixes — Ctrl+C to stop"
  pids=""
  trap 'for p in $pids; do kill "$p" 2>/dev/null || true; done; exit 0' INT TERM
  for s in $svcs; do
    f="$(logfile "$s")"
    [ -f "$f" ] || continue
    col="$(svc_color "$s")"
    (
      tail -n 50 -F "$f" 2>/dev/null | awk -v p="[$s]" -v c="$col" -v r="$C_RST" '
        { printf "%s%-10s%s %s\n", c, p, r, $0; fflush() }
      '
    ) &
    pids="$pids $!"
  done
  wait
}

cmd_open() {
  command -v open >/dev/null 2>&1 || die "macOS 'open' not found"
  opened=0
  for s in $ALL_SERVICES; do
    port="$(get_port "$s")"
    [ "$port" = "0" ] && continue
    [ -z "$(read_pid "$s")" ] && continue
    url="$(probe_url "$s" "$port" | sed -E 's,/health$,,')"
    [ -z "$url" ] && continue
    say "Opening $s → $url"
    open "$url"
    opened=$((opened+1))
  done
  [ "$opened" -gt 0 ] || warn "nothing running with a URL"
}

cmd_psql() {
  command -v psql >/dev/null 2>&1 || die "psql not in PATH"
  url="$(grep -E '^PHOVEU_BACKEND_DATABASE_URL=' "$ROOT/backend/.env" 2>/dev/null \
         | head -1 | cut -d= -f2-)"
  [ -z "$url" ] && die "PHOVEU_BACKEND_DATABASE_URL not in backend/.env"
  say "Connecting to dev DB"
  exec psql "$url"
}

cmd_reset() {
  say "Reset — stopping tracked services"
  for s in $ALL_SERVICES; do
    stop_service "$s" || true
  done
  say "Force-killing anything still bound to configured ports (orphans)"
  for s in $ALL_SERVICES; do
    port="$(get_port "$s")"
    [ "$port" = "0" ] && continue
    foreign="$(pid_on_port "$port")"
    if [ -n "$foreign" ]; then
      warn "killing orphan pid $foreign on :$port (held by something not in our state)"
      kill -KILL "$foreign" 2>/dev/null || true
    fi
  done
  say "Wiping state directory"
  rm -rf "$STATE_DIR"
  mkdir -p "$STATE_DIR"
  ok "Reset complete."
}

# Pre-flight: warning-only.
preflight_warn_only() {
  pg_ok=1; redis_ok=1
  if command -v pg_isready >/dev/null 2>&1; then
    if ! pg_isready -h localhost -p 6432 -t 2 >/dev/null 2>&1; then
      warn "Postgres write engine localhost:6432 not reachable (pgbouncer down?)"
      pg_ok=0
    fi
    if ! pg_isready -h localhost -p 6433 -t 2 >/dev/null 2>&1; then
      warn "Postgres read replica localhost:6433 not reachable (pgbouncer-replica down?)"
    fi
  else
    warn "pg_isready not in PATH; skipping Postgres preflight"
  fi
  if command -v redis-cli >/dev/null 2>&1; then
    if ! redis-cli -h localhost -p 6379 ping >/dev/null 2>&1; then
      warn "Redis localhost:6379 not reachable (worker fan-out + WS will be degraded)"
      redis_ok=0
    fi
  elif command -v nc >/dev/null 2>&1; then
    # `nc -z` is a port probe; -G sets connect timeout on macOS,
    # -w on BSD/Linux nc — we use a subshell with a hard timeout
    # via the shell's `kill` so we never block.
    if ! nc -z -G 2 localhost 6379 >/dev/null 2>&1 \
       && ! nc -z -w 2 localhost 6379 >/dev/null 2>&1; then
      warn "Redis localhost:6379 not reachable (worker fan-out + WS will be degraded)"
      redis_ok=0
    fi
  else
    warn "Neither redis-cli nor nc in PATH; skipping Redis preflight"
  fi
  if [ "$pg_ok" = 1 ] && [ "$redis_ok" = 1 ]; then
    ok "preflight: Postgres + Redis OK"
  fi
}

cmd_preflight() { preflight_warn_only; }

# ── help ──────────────────────────────────────────────────────────────

show_help() {
  back_def="$(default_port_for backend)"
  front_def="$(default_port_for frontend)"
  cat <<USAGE
${C_BOLD}dev.sh${C_RST} — local-dev supervisor

  ${C_BOLD}USAGE${C_RST}
    ./dev.sh [start] [services...] [-f] [--ports=A,B[,...]] [--with-<svc>] [--all]
    ./dev.sh stop    [services...]
    ./dev.sh restart [services...] [-f]
    ./dev.sh status                    table of services with state + URLs
    ./dev.sh tailf [svc|all]           follow logs (default: all, prefixed)
    ./dev.sh logs  [svc|all]           alias for tailf
    ./dev.sh open                      open running URLs in browser
    ./dev.sh psql                      drop into the dev DB shell
    ./dev.sh preflight                 ping Postgres + Redis (warn-only)
    ./dev.sh reset                     stop everything, kill orphans, clear state
    ./dev.sh -h | --help

  ${C_BOLD}SERVICES${C_RST}
    backend   FastAPI / uvicorn  (default port $back_def)
    frontend  Vite               (default port $front_def)
    worker    TikTokLive listener (no port)         — start with --with-worker
    client    Electron desktop app                  — start with --with-client

  ${C_BOLD}DEFAULT SET${C_RST}
    \`./dev.sh\` (no args) → status
    \`./dev.sh start\`     → backend + frontend
    \`./dev.sh start --with-worker\` → backend + frontend + worker
    \`./dev.sh start --all\`         → everything except Electron client (use --with-client to add it)
    \`./dev.sh <svc>\`               → start <svc>  (shorthand)

  ${C_BOLD}PORTS${C_RST}
    --ports=A,B[,...]    positional by service order: backend,frontend,worker,client
                         empty slots keep defaults: --ports=,5180  → frontend=5180
    Resolution priority: --ports flag > caller env (BACKEND_PORT etc.) > persisted state > defaults
    Resolved ports are persisted to .dev/ports.env so subsequent
    status / stop / restart calls don't need the flag.

  ${C_BOLD}FLAGS${C_RST}
    -f, --follow         tail logs after start/restart
    --with-<svc>         add an optional service to the default start set
    --all                start everything (excludes client by default)
    --ports=…            override ports (see above)
    -h, --help           this message

  ${C_BOLD}STATE${C_RST}
    .dev/<svc>.pid    process id
    .dev/<svc>.log    stdout + stderr
    .dev/<svc>.meta   port + start time
    .dev/ports.env    persisted port resolution

  ${C_BOLD}ENV TUNABLES${C_RST}
    DEV_HEALTH_TIMEOUT_S   readiness probe deadline (default 30)
    DEV_STOP_GRACE_S       SIGTERM-to-SIGKILL grace (default 8)
    DEV_ALL_INCLUDE_CLIENT non-empty → --all also starts the Electron client

USAGE
}

# ── main ──────────────────────────────────────────────────────────────

main() {
  parse_args "$@"
  if [ "$SHOW_HELP" -eq 1 ]; then
    show_help; exit 0
  fi
  resolve_target_services

  case "$ACTION" in
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    restart)    cmd_restart ;;
    status)     cmd_status ;;
    tailf|logs) cmd_tailf ;;
    open)       cmd_open ;;
    psql)       cmd_psql ;;
    reset)      cmd_reset ;;
    preflight)  cmd_preflight ;;
    *)          die "Unknown action '$ACTION'." ;;
  esac
}

main "$@"

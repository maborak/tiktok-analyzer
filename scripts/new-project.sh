#!/usr/bin/env bash
#
# Scaffold a new project from this framework template.
#
# Copies the framework into a target directory, renames brand strings
# and the env-var prefix, then initialises a fresh git history with one
# initial commit referencing the framework SHA the project was forked
# from. Modules (tickets, billing, livechat, …) come along; delete what
# you don't need before your first business commit.
#
# Usage:
#     scripts/new-project.sh <target-dir>
#
# Inputs are prompted interactively, or set via env vars to skip:
#     PROJECT_NAME="Acme SaaS"
#     LEGAL_ENTITY="Acme Inc."           (defaults to PROJECT_NAME)
#     ENV_PREFIX="ACME_"                  (replaces APT_; auto-derived if blank)
#     SUPPORT_EMAIL="support@acme.com"

set -euo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  sed -n '/^# Scaffold/,/^# *SUPPORT_EMAIL/p' "$0" | sed 's/^# \{0,1\}//'
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || -z "${1:-}" ]]; then
  usage
  exit $([[ -z "${1:-}" ]] && echo 1 || echo 0)
fi

TARGET_DIR=$1

# ── Prompt helpers ─────────────────────────────────────────────────────────

ask() {
  local var=$1 label=$2 default=${3:-} input
  if [[ -z "${!var:-}" ]]; then
    if [[ -t 0 ]]; then
      if [[ -n "${default}" ]]; then
        read -r -p "${label} [${default}]: " input || input=
        eval "${var}=\${input:-\${default}}"
      else
        read -r -p "${label}: " input || input=
        eval "${var}=\${input}"
      fi
    else
      eval "${var}=\${default}"
    fi
  fi
}

ask PROJECT_NAME "Project display name" "Acme SaaS"
: "${LEGAL_ENTITY:=${PROJECT_NAME}}"
ask LEGAL_ENTITY "Legal entity"

if [[ -z "${ENV_PREFIX:-}" ]]; then
  derived=$(printf '%s' "${PROJECT_NAME}" \
    | tr '[:lower:]' '[:upper:]' | tr -dc 'A-Z0-9' | cut -c1-6)
  ENV_PREFIX="${derived}_"
fi
ask ENV_PREFIX "Env-var prefix (replaces APT_)"

ask SUPPORT_EMAIL "Support email" "support@example.com"

SLUG=$(printf '%s' "${PROJECT_NAME}" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')

# ── Validate ───────────────────────────────────────────────────────────────

if [[ -e "${TARGET_DIR}" ]]; then
  echo "❌ Target already exists: ${TARGET_DIR}" >&2
  exit 1
fi

if [[ "${ENV_PREFIX}" != *_ ]]; then
  echo "❌ ENV_PREFIX should end with an underscore (got: ${ENV_PREFIX})" >&2
  exit 1
fi

mkdir -p "$(dirname "${TARGET_DIR}")"
ABS_TARGET=$(cd "$(dirname "${TARGET_DIR}")" && pwd)/$(basename "${TARGET_DIR}")

cat <<INFO

About to create new project:
  Path:           ${ABS_TARGET}
  Name:           ${PROJECT_NAME}
  Legal entity:   ${LEGAL_ENTITY}
  Env prefix:     ${ENV_PREFIX}
  Slug:           ${SLUG}
  Support email:  ${SUPPORT_EMAIL}
  From framework: ${FRAMEWORK_ROOT}
INFO

if [[ -t 0 && "${ASSUME_YES:-}" != "1" ]]; then
  read -r -p "Proceed? [y/N] " ok
  case "${ok}" in y|Y|yes|YES) ;; *) echo "Aborted."; exit 1 ;; esac
fi

# ── 1. Copy ────────────────────────────────────────────────────────────────

echo "→ Copying framework files…"
rsync -a \
  --exclude='.git/' \
  --exclude='.claude/' \
  --exclude='node_modules/' \
  --exclude='dist/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='backend/data/' \
  --exclude='backend/.venv/' \
  --exclude='frontend/src/routeTree.gen.ts' \
  --exclude='backend/openapi.snapshot.json' \
  "${FRAMEWORK_ROOT}/" "${ABS_TARGET}/"

cd "${ABS_TARGET}"

# ── 2. Rename strings ──────────────────────────────────────────────────────

echo "→ Renaming brand strings + env prefix…"

# Escape for perl regex/replacement (handles $, @, \, /).
escape() { printf '%s' "$1" | perl -pe 's/([\$\@\\\/])/\\$1/g'; }

P_NAME=$(escape "${PROJECT_NAME}")
P_ENTITY=$(escape "${LEGAL_ENTITY}")
P_EMAIL=$(escape "${SUPPORT_EMAIL}")
P_SLUG=$(escape "${SLUG}")
P_PREFIX=$(escape "${ENV_PREFIX}")

# Files to touch — code + docs + env files. Ordering of substitutions
# matters: most-specific phrase first so we don't double-substitute.
find . -type f \( \
    -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' \
    -o -name '*.jsx' -o -name '*.md' -o -name '*.json' -o -name '*.html' \
    -o -name '*.yaml' -o -name '*.yml' -o -name '.env*' \
  \) \
  -not -path './.git/*' \
  -not -path '*/node_modules/*' \
  -not -path '*/dist/*' \
  -not -path '*/__pycache__/*' \
  -not -path './backend/data/*' \
  -not -path './backend/.venv/*' \
  -not -name 'package-lock.json' \
  -not -name 'openapi.snapshot.json' \
  -print0 \
  | xargs -0 perl -pi -e "
      s/Maborak Framework/${P_NAME}/g;
      s/Maborak Inc\\./${P_ENTITY}/g;
      s/Maborak Support/${P_NAME} Support/g;
      s/Maborak-Framework/${P_SLUG}/g;
      s/\\bMaborak\\b/${P_ENTITY}/g;
      s/Legal AI/${P_NAME}/g;
      s/support\@maborak\\.com/${P_EMAIL}/g;
      s/\\bAPT_/${P_PREFIX}/g;
    "

# ── 3. Root README ─────────────────────────────────────────────────────────

cat > README.md <<README
# ${PROJECT_NAME}

Scaffolded from a custom framework template.

## Structure

\`\`\`
.
├── backend/    # FastAPI + Hexagonal Architecture (Python)
├── frontend/   # React + TypeScript + Vite + Tailwind CSS
└── README.md
\`\`\`

See each directory's README for details:

- [Backend](backend/README.md)
- [Frontend](frontend/README.md)

## Tracking framework upstream

To pull future framework updates into this project:

\`\`\`bash
git remote add framework ${FRAMEWORK_ROOT}
git fetch framework
git merge --allow-unrelated-histories framework/main
\`\`\`

Resolve conflicts in the renamed brand strings and env prefix as needed.
README

# ── 4. Fresh git history ───────────────────────────────────────────────────

echo "→ Initialising fresh git history…"
FW_SHA=$(cd "${FRAMEWORK_ROOT}" && git rev-parse HEAD)
FW_BRANCH=$(cd "${FRAMEWORK_ROOT}" && git rev-parse --abbrev-ref HEAD)

git init -q -b main 2>/dev/null || git init -q
git add .
git commit -q -m "Initial commit — scaffolded from framework@${FW_SHA} (${FW_BRANCH})"

cat <<DONE

✅ ${PROJECT_NAME} scaffolded at ${ABS_TARGET}

Next steps:
  cd ${ABS_TARGET}
  # Backend
  cp backend/.env.example backend/.env 2>/dev/null || true
  cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
  # Frontend
  cd ../frontend && npm install

Modules you may want to remove (delete the files + clean up imports):
  - Tickets:  backend/routes/admin/tickets.py, frontend/src/modules/admin/pages/Tickets.tsx, …
  - Billing:  backend/routes/admin/billing.py, backend/domain/services/payment_service.py, …
  - Livechat: backend/routes/admin/livechat*.py (if any), frontend/src/modules/admin/pages/LiveChat*.tsx
DONE

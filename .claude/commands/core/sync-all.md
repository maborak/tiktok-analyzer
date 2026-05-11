Synchronize all project artifacts — agents, tracking docs, and master context — with the current codebase state. Run after significant changes to eliminate stale references.

## Step 1 — Build the Truth Snapshot

Scan the codebase in parallel to build a single canonical snapshot. Run ALL of these simultaneously:

**Backend routes:**
```bash
grep -n "include_router\|setup_routes" backend/routes/main.py
```
```bash
grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/routes/ --include="*.py" | grep -v __pycache__
```

**Domain entities and DB models:**
```bash
grep -rn "^class " backend/domain/entities/ --include="*.py" | grep -v __pycache__
```
```bash
grep -rn "^class.*Base\)" backend/database/ --include="*.py" | grep -v __pycache__
```

**Ports and adapters:**
```bash
grep -rn "class.*Port\|class.*ABC" backend/ports/ --include="*.py" | grep -v __pycache__
```
```bash
ls -1 backend/adapters/ backend/adapters/persistence/ 2>/dev/null
```

**Architecture violations (current):**
```bash
grep -rn "from database\." backend/routes/ --include="*.py" | grep -v __pycache__
```
```bash
grep -rn "from adapters\.\|from database\." backend/domain/ --include="*.py" | grep -v __pycache__
```

**TikTok module (the primary feature):**
```bash
grep -rn "^class \|^async def " backend/domain/services/tiktok_service.py | head -40
```
```bash
ls -1 backend/database/tiktok/ backend/database/migrations/ | head -30
```

**Frontend routes and pages:**
```bash
find frontend/src/routes -name "*.lazy.tsx" -o -name "*.tsx" | grep -v routeTree | sort
```
```bash
find frontend/src/modules -name "*.tsx" -path "*pages*" -type f | sort
```

**Inventories:**
```bash
ls -1R .claude/agents/
ls -1R .claude/commands/
```

**Typed config registry (Phoveus feature):**
```bash
grep -n "ConfigKeyDef(" backend/domain/entities/config_registry.py | wc -l
```

Collect all outputs into a mental model. This is the **Truth Snapshot**.

---

## Step 2 — Refresh Tracking Documents

Tracking docs in this repo live under `.claude/tracking/` (create the directory + files if absent). The canonical set is:

| Doc | Purpose |
|-----|---------|
| `CHANGELOG.md` | Per-session change log (managed by `/session-commit`) |
| `TODO.md` | In-flight work + Done section |
| `OPEN_ISSUES.md` | Known architectural / security violations |

### 2a. `.claude/tracking/OPEN_ISSUES.md`

Read the full file (or create it if absent). For each issue:
- Verify the cited `file:line` still exists and the issue is still present
- Mark genuinely FIXED issues with strikethrough and move to "Recently Fixed"
- Add any NEW violations discovered in Step 1
- Update issue counts

Verification checks against current code:
```bash
grep -n "JWT_SECRET.*your-super-secret-jwt-key-here" backend/config.py
grep -rn "from adapters\.\|from database\." backend/domain/ --include="*.py" | grep -v __pycache__
grep -rn "from database\." backend/routes/ --include="*.py" | grep -v __pycache__
```

### 2b. Project-specific docs (when present)

If any of these exist, cross-reference and update:

| Doc | Cross-reference against |
|-----|------------------------|
| `docs/tikfinity-analysis.md` | `client/` Electron + `backend/adapters/tiktok_live_client.py` |
| `backend/docs/*` | Whatever the doc names — match to its scope (e.g. config_registry.py for config docs) |

Skip any doc that doesn't apply.

### 2c. Top-level `CLAUDE.md`

`/CLAUDE.md` is the project's primary context doc (hexagonal architecture, TikTok module overview, recipes). Update only:
- **Architecture diagram** — refresh if ports/adapters/services changed structure
- **TikTok module section** — add new event types, signals, or pipeline pieces from the Truth Snapshot
- **Listener-pool deployment modes** — verify `in_process` vs `worker` env-var docs match `api_main.py`
- **Pitfalls** — add new audited patterns

Do NOT touch:
- Quick start commands
- Recipe templates (Add a typed config key, Add an admin endpoint, etc.)

---

## Step 3 — Refresh Agent Files

Agents live in `.claude/agents/{core,project}/`. For each, read the full file and update **only factual / business-context sections**.

### What to update per agent:

| Section type | Action |
|-------------|--------|
| Sources of Truth file lists | Add new files, remove deleted ones |
| Route maps / endpoint tables | Add new routes from Truth Snapshot |
| Entity / model lists | Add new entities, update field lists |
| Known issues references | Update status from Step 2a findings |
| File path references | Fix any paths that moved |
| Feature descriptions | Add new features that affect this agent's domain |

### What to NEVER touch:

- Identity (role, scope, authority, tone)
- Methodology / approach descriptions
- Output format templates
- Anti-pattern lists (unless a concrete new anti-pattern was discovered in code)

### Processing order (this repo):

**Core agents:**
- `session-commit.md` — usually no factual content; skip unless commit conventions changed

**Project agents:**
- `ai-slop-detector.md` — refresh sample passages from current codebase if conventions shifted
- `frontend-dark-mode-auditor.md` — verify framework's auto-inversion rules if `styles/themes.css` changed
- `frontend-responsive-auditor.md` — refresh breakpoint rules + known offending components
- `ux-designer.md` — add new pages / components observed in Step 1

**Skip rule**: If nothing in the Truth Snapshot affects an agent's factual sections, skip it entirely. Do not make gratuitous edits.

---

## Step 4 — Refresh user-level memory (if relevant)

Persistent memory for this project lives at:
`~/.claude/projects/-Users-wilmeradalid-code-maborak-tiktok-bot/memory/`

Only update these IF the related state changed:

| Memory file | When to update |
|-------------|---------------|
| `project_tiktok_module.md` | Worker coordination, scrape throttling, heartbeat split changed |
| `project_pending_work.md` | Pending UI features completed or new gaps discovered |
| `project_event_emission_gaps.md` | New TikTokLive event types tested for emission |
| `user_profile.md` | Never — user-managed |
| `feedback_*.md` | Never auto-write — only on explicit user feedback |

Do NOT create new memory files in this step; that's reserved for explicit user-feedback persistence.

---

## Step 5 — Report

Output this summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SYNC-ALL COMPLETE
  Date: YYYY-MM-DD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Tracking Documents
| Document | Status | Changes |
|----------|--------|---------|
| OPEN_ISSUES.md | Updated / Current / Created | N issues updated, M new, K fixed |
| CHANGELOG.md | Current | (managed by /session-commit) |
| TODO.md | Current | (managed by user) |

## Agent Files
| Agent | Status | What Changed |
|-------|--------|-------------|
| ai-slop-detector | Updated / Skipped | … |
| frontend-dark-mode-auditor | Updated / Skipped | … |
| frontend-responsive-auditor | Updated / Skipped | … |
| ux-designer | Updated / Skipped | … |

## Master Context
| File | Status |
|------|--------|
| /CLAUDE.md | Updated / Current |

## Architecture Violations Found
- [Any violations not previously documented]

## Issue Status Changes
- [Issues that changed: OPEN→FIXED, new discoveries, etc.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Rules

1. **This is a sync, not an audit** — update docs to match code reality, do not evaluate code quality
2. **Never rewrite agent identity or methodology** — only update factual business context
3. **Skip agents with no stale facts** — no gratuitous edits
4. **Every fact you write must be verifiable** against what you scanned in Step 1
5. **Preserve formatting** — match each file's existing markdown style
6. **Track what you change** — you need the details for the Step 5 report
7. **If a doc does not exist**, note it in the report and skip (or create with a stub if it's a tracking doc)

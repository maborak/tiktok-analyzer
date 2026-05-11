Wrap up the current work session: analyze all changes since the last git push, generate a detailed commit for any uncommitted work, update .claude/tracking/CHANGELOG.md, and refresh .claude/memory/MEMORY.md so the next session resumes with full context.

## Step 1 — Assess the session delta

Run in parallel:
```bash
git log origin/$(git branch --show-current)..HEAD --oneline
git diff origin/$(git branch --show-current)...HEAD --stat
git status --short
```

- If no commits and no working tree changes: report "Nothing to commit" and stop.
- If there are unpushed commits only (no working tree changes): skip to Step 4 (just update changelog and memory).
- If there are working tree changes (staged or unstaged): proceed to Step 2.

## Step 2 — Read and understand what changed

Identify the key changed files from `git diff --stat`. Read the most significant ones:
- Any new backend route, domain entity, adapter method, or port change
- Any new frontend page, component, repository implementation, or type change
- Any migration file, config change, or .claude tooling file

For each file group, determine: **what changed** and **why** (feature, fix, refactor, docs).

## Step 3 — Stage and commit uncommitted changes

Stage tracked modifications:
```bash
git add -u
```

Stage new files individually if they're part of the session's work (source files, migrations, components). Never `git add .`.

Verify staged set:
```bash
git diff --cached --stat
```

Write a conventional commit:
- Format: `<type>(<scope>): <imperative subject>`
- Body: bullet points — what changed and why, with file references for key changes
- Footer: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`

Type guide: `feat` (new capability), `fix` (bug fix), `refactor` (no behavior change), `chore` (config/deps/tooling), `docs` (docs only)
Scope guide: `backend`, `frontend`, `tooling`, `config`, or omit for cross-cutting changes

Commit using HEREDOC to preserve formatting:
```bash
git commit -m "$(cat <<'EOF'
type(scope): subject line here

- Bullet explaining change 1
- Bullet explaining change 2

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

If a pre-commit hook fails: fix the issue, re-stage, create a NEW commit (never --amend, never --no-verify).

## Step 4 — Update .claude/tracking/CHANGELOG.md

CHANGELOG is at `.claude/tracking/CHANGELOG.md`. Create it if absent.

Prepend an entry (or merge into today's existing entry):

```markdown
## [Unreleased] — YYYY-MM-DD

### Backend
- **type**: what changed (`backend/path/file.py`)

### Frontend
- **type**: what changed (`frontend/src/path/file.tsx`)

### Tooling / Docs
- **type**: what changed

---
```

Only include sections that have actual changes. Keep bullets factual and human-readable — not a copy of the commit body.

## Step 5 — Update MEMORY.md Last Session

Edit the file at:
`.claude/memory/MEMORY.md`

### 5a — Read current state and reconcile

Before writing, read:
1. The CURRENT `## Last Session` section in MEMORY.md (previous session's "Remaining Work")
2. The `.claude/tracking/TODO.md` file — check its "Done" section

For each item in the previous session's "Remaining Work":
- If it appears in `.claude/tracking/TODO.md`'s "Done" section → **drop it** (completed)
- If the code/git history shows it was completed this session → **drop it**
- If it is still genuinely incomplete → **carry it forward**

### 5b — Write the updated section

Replace `## Last Session` with:

```markdown
## Last Session
Date: YYYY-MM-DD
Branch: <current-branch>
Summary: <one-line session theme>

### Remaining Work
- <genuinely incomplete items — carried forward from previous + new from this session>
```

Rules:
- **No "What was worked on" or "Files touched" lists** — the git log and CHANGELOG cover that
- **"Remaining Work" is the only high-value field** — be specific so the next session can pick up immediately
- **Never carry forward completed work** — always reconcile against `.claude/tracking/TODO.md` and git history
- Max 10 bullets. If an item has been "remaining" for 3+ sessions, flag it with (STALE)

## Step 6 — Report to user

Output:
```
### Session Commit Summary

**Commit**: `type(scope): subject`
**Files**: N changed, M insertions, K deletions
**Branch**: <branch> (not pushed)

**.claude/tracking/CHANGELOG.md** ✓
**MEMORY.md** ✓

**To push**: git push origin <branch>
**Left off**: <one-line summary of in-progress state>
```

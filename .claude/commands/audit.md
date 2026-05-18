Deep multi-agent audit of the latest changes. The default scope is the
most recent commit on the current branch + any uncommitted modifications
in the working tree.

**Why this command exists**: a perf-overhaul session shipped a commit
that bundled pre-existing modifications with new work; one of the
pre-existing modifications had dropped an `s.commit()` in a top-level
session-opening method (`open_match`), poisoning the in-memory
`_active_match` cache and producing FK violations on every event after
a match started. The single-target audit run at the time only audited
the new perf code, NOT the pre-existing modifications that got swept
into the same commit. This command exists to make that miss impossible
to repeat — it audits the FULL DIFF, not "what we think we wrote."

---

## Step 1 — Scope the audit

Resolve the audit target. Default is `HEAD~1..HEAD` plus working-tree
modifications, but the user can pass:
- A range: `/audit HEAD~3..HEAD`
- A single commit: `/audit 260dbfb`
- A range against a base: `/audit main..HEAD`
- The literal `staged` for the staging area only
- The literal `worktree` for uncommitted modifications only

Resolution shell sketch:

```bash
# Detect target. If user passed args via $ARGUMENTS, use that range.
# Otherwise default to last commit + uncommitted work.
target="${ARGUMENTS:-HEAD~1..HEAD}"
case "$target" in
  staged)   diff_cmd="git diff --cached" ;;
  worktree) diff_cmd="git diff" ;;
  *)        diff_cmd="git diff $target" ;;
esac

# Get the file list + size delta
git diff --stat "$target" 2>&1 | tail -50

# Show the latest commit(s) for context
git log --oneline "$target" 2>&1 | head -10

# Working tree status (untracked / unstaged)
git status --short
```

If `git diff --stat` returns nothing AND `git status --short` is empty:
report "Nothing to audit" and stop.

---

## Step 2 — Triage what changed

Look at the file list. Categorize each path into one or more dimensions
so the right specialists get dispatched:

| Dimension | Signals (path / content) |
|---|---|
| **DB read/write** | `backend/adapters/persistence/*.py`, `backend/database/migrations/*.py` |
| **HTTP routes — admin** | `backend/routes/admin/*.py` |
| **HTTP routes — public** | `backend/routes/public_*.py`, `backend/routes/auth.py` |
| **WebSocket / SSE** | grep diff for `@router.websocket`, `WebSocket` |
| **Service layer / business logic** | `backend/domain/services/*.py` |
| **Auth / RBAC / token handling** | `backend/adapters/auth_persistence.py`, anything matching `Depends(...rbac\|auth)` |
| **Frontend React / TS** | `frontend/src/**/*.tsx`, `frontend/src/**/*.ts` |
| **Schema migrations** | `backend/database/migrations/*.py` |
| **Config / env / secrets** | `backend/config.py`, `backend/domain/entities/config_registry.py`, anything matching `os.getenv\|CONFIG\|PHOVEU_` |
| **Removed code** | `git diff --diff-filter=D` shows deleted lines — note them |

For each touched file, read the diff with `git show <commit> -- <path>`
or `git diff <range> -- <path>` so the agents have specific evidence
to cite later.

---

## Step 3 — Flag pre-existing modifications

This is the step the previous audit missed. Identify changes in the
diff that aren't part of the "headline theme" of the commit:

```bash
# Show commit message vs file list mismatch
git log -1 --format='%s%n%b' <commit>
git diff --stat <commit>~1 <commit>
```

If the commit message describes feature X but the diff also touches
files Y, Z that look unrelated to X — flag those for extra scrutiny.
Pre-existing modifications swept into a commit are the highest-risk
category because the commit author didn't write them, didn't reason
about them, and didn't audit them.

Specifically check:
- Any file modified that the commit message doesn't reference
- Any refactor inside an otherwise feature-only diff (changing a
  method's transaction-management without flagging it)
- Any signature change to a widely-called helper (the cache-header
  default flip pattern)
- Any change to a `_with_commit` / `_in_session` / context-manager
  pattern (transaction scope corruption is the silent killer)

---

## Step 4 — Dispatch specialists in parallel

Based on what categories Step 2 surfaced, dispatch the matching
agents IN PARALLEL (single message, multiple Agent tool calls). The
list below is the catalogue; only dispatch agents for categories that
actually appeared.

| If category touched | Dispatch agent(s) |
|---|---|
| DB read/write OR migrations | `db-performance-auditor` |
| HTTP admin routes added/changed | `security-fastapi-auth-auditor` + `api-performance-auditor` |
| Public routes / public-visibility changes | `security-public-surface-auditor` + `security-channel-auditor` |
| WS/SSE channels | `security-channel-auditor` |
| Service layer or anything else | `general-purpose` reviewer (full diff, write-path correctness, race conditions) |
| Frontend changes | `frontend-dark-mode-auditor` + `frontend-responsive-auditor` + `ai-slop-detector` (only if visual changes) |
| Mixed / non-obvious | `general-purpose` as catch-all |

Briefing template for each agent (adapt to specifics):

```
Audit task — the user just shipped commit(s) <SHA> on branch <branch>.
Run `git show <SHA> -- <files>` to see the change. Hunt for:

1. <category-specific concerns>
2. ANY pre-existing modification that snuck into this commit and looks
   unrelated to the headline theme. Read the full diff of every
   touched file — not just the lines that match the commit message.
3. Transaction scope: any method that opens its own session must call
   s.commit() before returning. Re-querying inside the same uncommitted
   transaction silently returns the row, but `__exit__` rolls it back.
4. Default-argument flips on shared helpers — verify all callers were
   audited for the new default's behaviour.
5. INNER vs LEFT joins on any backfill / pre-agg writes — silent
   row drops are a regression vs raw-scan reads.
6. Public route surface — `Cache-Control`, allowlist completeness,
   differential-404 leaks, intentional vs accidental opt-in to caching.
7. Auth gates — every admin route under `routes/admin/` must carry a
   `Depends(...rbac...)` or equivalent. WebSocket routes do NOT inherit
   Depends from the router and must validate in-handler.

Report under <N> words. Triage matrix:
  🚨 CRITICAL — block deploy; will cause data loss / FK violation / outage
  🔴 HIGH      — block merge; correctness or security regression
  🟡 MEDIUM    — fix before next session
  🟢 LOW       — cleanup, doc-fix, nit
For each finding: file:line, evidence, one-line repro/description.
NO FIXES — findings only.
```

When the user passes scoped args (`/audit HEAD`, `/audit staged`, etc.),
respect that scope and brief the agents accordingly.

---

## Step 5 — Cross-check against the known-bug catalogue

After agents return, compare findings against these landmines that
have actually bit this codebase before:

| Landmine | What to grep for | Where it bit us |
|---|---|---|
| Top-level method opens session, mutates, returns without `s.commit()` | `def <name>.*\n.*with self\._get_session.*\n.*pg_insert\b.*\n(?!.*s\.commit)` | `open_match` (2026-05-15, FK violation flood) |
| Helper default-arg flip cascading to N callers | `def <helper>.*cacheable\|read_only.*=` then grep all callers | `_set_cache_headers` (2026-05-15, audit caught) |
| INNER JOIN on backfill where LEFT JOIN is correct | `JOIN tiktok_subscriptions sub` in any migration | `add_tiktok_room_stats.py` (2026-05-15, audit caught — 35 orphan rooms) |
| New public route lacking `Cache-Control` audit | Public route handler without `_set_cache_headers` call | n/a (pattern to watch) |
| Admin route missing `Depends(rbac.require_*)` | `@router.(get\|post\|put).*\n.*async def.*:\n.*(?!.*Depends\()` under `routes/admin/` | n/a (pattern to watch) |
| WebSocket route trusting `query.get('token')` without validating | WS routes that read token but don't call `auth_service.get_auth_context` | `/admin/tiktok/ws` (caught earlier — fixed in TOKEN_KEY=auth_token) |
| PG-only SQL in a function that falls through on SQLite without `_is_postgres()` guard | `ANY(:` `INTERVAL` `NOW()` `date_trunc` in `else:` branches | `_lives_summary_hourly`, `_daily_buckets_cached` (carried — flagged) |
| Sequence advanced but no row committed (silent rollback) | `pg_insert(.*).returning(...)` + no surrounding `s.commit()` | `open_match` (2026-05-15) |
| Cache key not including TZ / handle-set when payload depends on those | `_*_cache: dict` definitions | n/a (pattern was fixed once) |
| `async def` FastAPI route calling sync `svc.method(...)` without `asyncio.to_thread` | `async def \w+\(.*\n(?:.*\n){0,40}\s+return\s+svc\.` in `backend/routes/`, then verify the call is wrapped | 6 endpoints on the detail page (2026-05-16; surfaces under concurrent load only — single-user bench is fine) |
| Same logical question implemented in N read paths that drift over time | grep for the question's domain field (`is_live`, `n_live`, `active_room_id`); count distinct read paths | `n_live` totals vs `active_room_id` cards vs `state_cache.active_room_id` WS — 3 paths, 3 different answers (2026-05-16) |
| State-cache overlay re-asserts stale data when no clearing event fires | `_overlay_state_cache` / cache read paths that don't check SQL authority | session state persisted for 8+ hours after worker silently dropped (2026-05-16) |
| New shared component created but call sites not migrated | newly-created `*.tsx` in `components/` with zero/few imports elsewhere | `SafeAvatar` (2026-05-15: built, 19 call sites stayed raw `<img>` for weeks) |
| Approximation/heuristic that breaks at scale | `avg.*\*.*N\|* 0\.\d` in chart-data prep code | Pie "Others" slice (2026-05-16: heuristic was wrong by 1000× → #1 rendered as 0%) |
| Frontend page with high-frequency state churn but no `React.memo` on heavy children | `export function .*` in `components/` AND parent has `setState` in a WS / interval handler | `TikTokLiveDetailBody` 5046-line tree reconciled per WS event before 2026-05-16 |
| Pre-existing modification swept into commit without scrutiny | Files in `git diff --stat HEAD` whose path doesn't match the commit's headline theme | `open_match` refactor bundled into Phase 9 perf commit (2026-05-15, FK flood) |
| New hook (`useCallback` / `useMemo` / `useRef`) added to a component without updating the top-of-file React import | new `useCallback(...)`/`useMemo(...)` call in file's diff + grep file's `from 'react'` import for the symbol | `TikTokLiveDetail.tsx` `useCallback` (2026-05-16, runtime ReferenceError crashed `<TikTokLiveDetailBody>`) |
| Verification step that ran but did nothing (no-op pass mistaken for clean) | `npx tsc --noEmit` against a references-only tsconfig (e.g. root has `"files": []`); use `tsc -b --noEmit` instead | TikTokLiveDetail.tsx useCallback miss (2026-05-16 — empty tsc output trusted as "clean" when it was scoped to zero files) |
| User-facing cached endpoint without ownership check at the route layer | `routes/user/*.py` calls a cached `svc.<method>` without a `_resolve_owned_*` resolver above it; per-handle data leaks across users via shared cache slot | n/a (pattern to watch — added 2026-05-18 with the per-user monitoring rollout). The 25 cached service methods are keyed on `(handle, ...)` and assume the route layer is the auth gate; any new user-facing route that skips ownership check exposes another user's data. |
| Service-layer method whose name suggests "global" but is now ownership-aware | `list_subscriptions()` returning all subs even when called from a user-context — caller must filter in Python (wasteful) or there's a dedicated `_for_user(user_id)` variant | `list_subscriptions()` currently returns admin-shape across all owners; `/tiktok/lives` filters in Python. Acceptable until install grows past ~1000 subs. |

If any finding matches one of these landmines, mark it CRITICAL
regardless of the agent's original severity.

### Frontend verification commands (use these, not the no-ops)

| Goal | Correct command | Wrong command (no-op) |
|---|---|---|
| Type-check the whole frontend | `cd frontend && npx tsc -b --noEmit` | `cd frontend && npx tsc --noEmit` (with references-only root tsconfig, this checks zero files) |
| Verify runtime correctness | Start dev server, exercise the feature in a browser, watch the console | tsc passing alone |
| Verify a memoization fix | React DevTools "Highlight updates" — confirm child doesn't re-render on parent state change | "looks right in the diff" |

---

## Step 6 — Synthesize and report

Produce a single report with:

```markdown
# Audit Report — <target> — <date>

## Scope
- Target: <SHA range / "working tree" / "staged">
- Files: N changed, +M / −K
- Commit message theme: <one line>
- Files that DIDN'T match the theme (pre-existing modifications): <list>

## Findings — Triage Matrix

### 🚨 CRITICAL
| # | What | File:line | Evidence | Required action |
|---|---|---|---|---|

### 🔴 HIGH
…

### 🟡 MEDIUM
…

### 🟢 LOW
…

## Agents consulted
- <agent name>: <one-line summary>

## Landmine-catalogue hits
<list any findings that matched the known-bug catalogue>

## Recommendation
- Block / proceed with fixes / proceed
```

Print this report to the user. Do NOT apply fixes — that's a follow-up
decision. The audit's job is to surface; the fix decision is the
user's.

---

## Rules

1. **Audit the FULL diff, not just "what I wrote."** Pre-existing
   modifications swept into a commit are the highest-risk category
   because nobody reviewed them.
2. **Dispatch agents in parallel.** Single message, multiple Agent
   tool calls. Saves wall-clock time and stops sequential dependency
   thinking.
3. **Cite file:line.** Every finding must have specific evidence.
   "There might be a bug" without a line number gets dropped on
   the floor.
4. **Severity comes from impact, not effort.** A one-character fix
   that prevents a production outage is CRITICAL. A 200-line refactor
   that improves clarity is LOW.
5. **Don't fix during the audit.** Report → human decides → fix in a
   separate step. Conflating audit and fix is how missed-bug pattern
   started.
6. **Always cross-check against the landmine catalogue.** If we hit
   the same bug twice, the catalogue is failing — update it.

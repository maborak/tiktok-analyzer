# RCA — `open_match` missing-commit silently poisoned `_active_match`
**Incident date:** 2026-05-15
**Detected:** 2026-05-15 ~22:09 UTC (user spotted FK violations in worker logs)
**Resolved:** 2026-05-15 ~22:20 UTC (commit `0cf0384`)
**Severity:** HIGH — every active battle in a tracked live produced a
flood of FK-violation errors. Event persistence failed for `match_id`-
carrying events (`match_update`, `match_begin`, gifts/likes/comments
during a battle). The WS delta channel still fanned out, so the admin
UI continued updating from in-memory state; but the durable event
log diverged from the live feed for any event ingested while an
active match was poisoned in the in-memory cache.

---

## What broke

`tiktok_matches.id` sequence diverged from row count:

```
seq = 9936
max(id) = 9842
rows = 9773
→ 94 sequence values consumed with zero rows committed
```

Worker logs (real example, redacted):

```
22:09:58 ❌ ERROR  Persist failed for @luzy.pe type=like room=7640216343054813972
   (IntegrityError: insert or update on table "tiktok_events" violates foreign
    key constraint "tiktok_events_match_id_fkey"
    DETAIL: Key (match_id)=(9936) is not present in table "tiktok_matches".
    ...) — event broadcast still proceeds
22:09:58 ❌ ERROR  Persist failed for @luzy.pe type=match_update room=…
   (IntegrityError: ... match_id=9936 ...)
```

Every event carrying `match_id=9936` failed because the matches row
for id 9936 was never committed.

## The bug

`backend/adapters/persistence/tiktok_persistence.py:open_match`
was refactored from an explicit `SELECT-then-INSERT-or-UPDATE`
pattern to an atomic `pg_insert + on_conflict_do_update`. Sound idea.
But the refactor **dropped the `s.commit()` call** in the PG branch.
The SQLite fallback retained its commit; only the PG path was broken.

The flow per call:

1. `pg_insert(...).on_conflict_do_update(...)` runs → sequence
   advances by 1 (Postgres consumes the sequence value when the
   `INSERT` is parsed/executed, regardless of whether the txn
   ultimately commits).
2. Re-query within the same uncommitted txn: `s.query(Model).filter_by(
   room_id, battle_id).one()` → returns the row with its newly-assigned
   id (visible to itself; this is `READ COMMITTED` within the same
   txn).
3. `_match_to_dataclass(row)` builds the return value with the new
   id.
4. The function returns. The `with self._get_session() as s:`
   context manager exits, calling `RetrySession.__exit__` →
   `self.close()` → `self._session.close()`.
5. SQLAlchemy's `Session.close()` on a session with pending
   uncommitted changes **rolls back** the open transaction.
6. The row is gone. The sequence is advanced. The dataclass id
   returned in step 3 is invalid.
7. Caller stores `match.id` in `TikTokService._active_match[room_id]`.
8. Subsequent `persist_event_full(room_id, …, match_id=invalid_id)`
   calls fail `tiktok_events_match_id_fkey`. The event is lost from
   the persistent log. The WS broadcast goes out anyway because
   it's keyed on the room's in-memory state, not the DB write.

## Recovery

Commit `0cf0384` added `s.commit()` between the `s.execute(stmt)` and
the re-query. Direct test confirmed: `open_match` for a synthetic
battle now correctly advances the sequence AND lands the row.

The worker's in-memory `_active_match[room_id]` was still poisoned
with id=9936 after the code fix. A worker restart cleared it.

Going forward: every `open_match` call persists correctly. No DB
data needed repair (the orphan sequence values 9843..9936 will
simply be unused; Postgres sequences never reuse).

## Timeline

- **Earlier**: another AI session refactored `open_match` to the
  atomic-UPSERT pattern. The change was left uncommitted in the
  working tree.
- **2026-05-15 21:44 UTC**: this session committed `260dbfb`
  (perf overhaul). The pre-existing `open_match` refactor was
  swept into the same commit. The commit message described the
  perf work, NOT the `open_match` refactor.
- **2026-05-15 21:56 UTC**: this session ran a multi-agent audit
  on the perf changes. The audit prompt was scoped to the new
  perf code (cache observability, pre-agg switches, public route
  async). The agents found 5 real issues (LEFT JOIN, default flips,
  effect-dep churn, doc-mismatch). None of them looked at
  `open_match` because it wasn't part of the perf-overhaul's
  diff narrative.
- **2026-05-15 ~22:00 UTC**: user restarted the worker. The new
  worker process started with empty `_active_match` cache.
- **2026-05-15 ~22:00 UTC onward**: as battles began, the worker
  called the now-broken `open_match`. Each call:
  - Returned a dataclass with a fresh `match.id`
  - Stored that id in `_active_match`
  - Failed silently to persist the row
- **2026-05-15 22:09:58 UTC**: first FK violation logged. User
  noticed the worker log.
- **2026-05-15 22:18 UTC**: root cause identified by reading the
  diff of `open_match` in commit `260dbfb`.
- **2026-05-15 22:20 UTC**: commit `0cf0384` shipped with `s.commit()`
  restored. Direct test confirmed fix.

## The miss — why the audit didn't catch it

The Round-2 audit (commit `42a706d`) dispatched 4 specialists:

1. `db-performance-auditor` — DB query correctness
2. `general-purpose` reviewer — write-path correctness, race conditions
3. `security-public-surface-auditor` — public surface privacy
4. `security-fastapi-auth-auditor` — auth gates

ALL of them were briefed with a list of files modified in MY perf
work specifically. The brief said things like:

> 1. NEW WRITE PATH: `_bump_room_stats` in `…`
> 2. NEW READ PATHS: Four query helpers now read `tiktok_room_stats`…
> 3. PRE-AGG READ for `wk_diam`…

**The brief did not enumerate the `open_match` refactor.** It was
buried in the same diff (commit `260dbfb`) but the perf-work
narrative didn't surface it. The auditors honored the brief.

Specifically, the `general-purpose` code reviewer DID read the
diff of `tiktok_persistence.py` but treated changes outside the
perf-narrative as "pre-existing operational work, folded in" —
the same framing I used in the commit message. This was the
exact wrong framing: pre-existing modifications are the highest-
risk category precisely because the committer didn't write or
audit them.

## Root cause

Two distinct root causes, in order of severity:

**RC-1 — Audit scope mismatch.** The audit brief enumerated the
*new* perf code but didn't enumerate the pre-existing modifications
swept into the same commit. The auditors had no signal to scrutinize
the `open_match` refactor.

**RC-2 — The refactor itself.** The pre-existing `open_match`
refactor dropped `s.commit()` in the PG path. This is a localized
bug in the refactor — the SQLite path still committed, suggesting
the refactor author thought the PG `pg_insert.returning(...)` would
auto-commit or that the `with` block would commit on exit. Neither
is true with this codebase's session management.

A useful question: why did `RetrySession.__exit__` not commit by
default? Some session-context implementations do. This one
deliberately doesn't — the `_in_session` helper pattern relies on
the caller managing commit so that multiple writes can be bundled
into a single transaction. The pattern works correctly when used
correctly; it just doesn't catch a forgotten commit on a top-level
method.

## What would have caught it

Three independent checks. Any one would have stopped this:

**1. Audit the full diff, not just the headline narrative.**
The new `/audit` slash command at `.claude/commands/audit.md` is
the structural fix. It explicitly Step-3-flags "pre-existing
modifications that snuck into a commit" and dispatches agents on
the FULL diff.

**2. Landmine-catalogue grep.**
A targeted regex over the diff:

```bash
git diff <commit> | grep -B 20 "pg_insert" | grep -A 20 "_get_session" | grep -v "s.commit"
```

A method that opens a session, calls `pg_insert`, and returns without
`s.commit()` is the exact pattern of this bug. The `/audit` command's
Step 5 landmine catalogue now includes this rule.

**3. Round-trip test on hot paths.**
A 5-line smoke test that calls `open_match` with a synthetic
battle_id and verifies the row exists in a *new* session would have
caught this immediately. The session-commit-or-die check is so
specific that a unit test is cheap to write. Adding one to
`tests/test_match_lifecycle.py` would prevent recurrence.

## Action items

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Fix `open_match` PG path (`s.commit()` restored) | Claude | ✅ commit `0cf0384` |
| 2 | Build `/audit` slash command to enforce full-diff audits | Claude | ✅ `.claude/commands/audit.md` |
| 3 | Add "missing commit on session-opening method" to the audit landmine catalogue | Claude | ✅ in `/audit` Step 5 |
| 4 | Write this RCA | Claude | ✅ this document |
| 5 | Unit test: `open_match` writes through in a fresh transaction | TBD | open |
| 6 | Run `/audit HEAD~3..HEAD` retroactively to find any other missed bugs | TBD | open |
| 7 | When committing pre-existing modifications, split the commit into per-theme commits OR call them out explicitly in the commit message | Claude / Wilmer (process) | adopted going forward |

## Detection signals that should have raised the alarm earlier

- The error message text — "violates foreign key constraint
  tiktok_events_match_id_fkey ... is not present in table
  tiktok_matches" — is unambiguous. Worker logs always surface
  these but they're easy to miss in a noisy stream.
- The `tiktok_matches_id_seq` value vs `max(id)` gap. A
  monitoring query that alerts when `seq - max(id) > 10` would
  detect this within seconds. Pre-existing healthy gaps from
  rolled-back transactions are typically 1-3 per day; a sudden
  jump to 94 is a clear alarm.
- The `n_dead_tup` / `n_live_tup` ratio on `tiktok_matches` —
  not load-bearing, but autovacuum stats are a free signal.

## Reference

- Bug fix commit: `0cf0384 fix(tiktok): commit open_match PG path so matches actually persist`
- Audit miss commit (where pre-existing modification was committed): `260dbfb perf(tiktok): pre-agg DB + realtime WS gaps + cache observability`
- File: `backend/adapters/persistence/tiktok_persistence.py:1073-1100` (PG branch of `open_match`)
- New audit command: `.claude/commands/audit.md`
- Caller using the poisoned id: `backend/domain/services/tiktok_service.py:4460-4509` (`_handle_match_event`)

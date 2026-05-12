# Open Issues

Known architectural / security violations in the repo. Each entry
carries `file:line` evidence so a future scan can re-verify status.

Severity tiers:

| Tag | Meaning |
|-----|---------|
| **CRITICAL** | Active security exposure |
| **HIGH** | Architectural violation that bypasses hexagonal contracts |
| **MEDIUM** | Defense-in-depth weakness; deferrable with note |
| **LOW** | Cosmetic / convention drift; safe to defer |

Last audit: 2026-05-12 (pre-prod gate, see `.claude/tracking/CHANGELOG.md`).

---

## CRITICAL

(none open — see "Recently Fixed" below for items closed during the
pre-prod audit cycle.)

---

## HIGH — Hexagonal contract violations

These are documented in `CLAUDE.md` as the explicit anti-pattern
("never import an adapter into a service or route; depend on the port
ABC"). All are pre-existing.

### ARC-1 — Routes import `database.*` directly
Routes should depend on services + ports, not DB models.

- `backend/routes/admin/security.py:13` — `from database.auth.models import User as UserModel`
- `backend/routes/user/account/oauth.py:169` — `from database.auth.utils import generate_salt, hash_password` (lazy import inside handler)

### ARC-2 — Domain services import adapters directly
Domain should not reach into adapter modules. All instances are lazy
imports inside method bodies — they exist because the relevant
capabilities (sign-engine globals, gap tracker, profile scraper,
throttled fetch) were never given a port abstraction.

- `tiktok_service.py:340` — `from adapters.tiktok_live_client import _apply_sign_globals`
- `tiktok_service.py:928` — `from adapters.tiktok_offset_tracker import gap_tracker`
- `tiktok_service.py:1080,1657,1978` — `from adapters.tiktok_profile_scraper import fetch_public_profile`
- `tiktok_service.py:1751` — `from adapters.tiktok_live_client import fetch_public_profile_throttled`

**Fix shape:** add a `TikTokSignEnginePort`, `TikTokOffsetTrackerPort`,
and `TikTokProfileScraperPort`; inject through `initialize_services`.

---

## HIGH — Frontend (security audit, not yet patched)

These were flagged HIGH during the 2026-05-12 frontend audit but
deferred — not ship-blockers when paired with the CRITICAL fixes
already in place, but should be tackled before the next major release.

### FE-H1 — Impersonation `stopImpersonation` trusts localStorage unverified
- `frontend/src/contexts/AuthContext.tsx:431–463`
- Risk: any XSS or compromised extension that writes attacker-
  controlled JSON to `admin_auth_user` + admin token to
  `admin_auth_token` can call `stopImpersonation()` to elevate to admin.
  Also: stale-token restoration after server-side revocation.
- Fix: re-fetch `/auth/me` on `stopImpersonation`; validate restored
  user is still server-side admin before flipping `isImpersonating`.

### FE-H2 — JWT in localStorage + cached role for permission gating
- `frontend/src/contexts/AuthContext.tsx:140–179, 520`
- Risk: XSS that writes `{"role":"admin"}` to `auth_user` flips
  `isAdmin` synchronously, unlocks admin sidebar + routes until
  `/auth/me` resolves. Compounds with FE-H1.
- Short-term fix: gate admin UI affordances on the FRESH `/auth/me`
  response, not the cached user object.
- Long-term fix: HttpOnly + SameSite=Strict cookie session (bigger
  refactor).

### FE-H3 — Invoice viewer iframe has no `sandbox`
- `frontend/src/modules/user/components/billing/InvoiceViewer.tsx:14–35`
- `frontend/src/modules/user/pages/billing/InvoiceDetail.tsx:197–202`
- Risk: server-returned `htmlContent` written into a same-origin iframe
  via `doc.write`. Any unescaped user-controlled field in the backend
  invoice template (customer name, billing address, custom notes)
  becomes self-XSS — and when an admin views that user's invoice, the
  script runs with the admin's JWT in localStorage.
- Fix: add `sandbox="allow-same-origin"` (no `allow-scripts`) to both
  iframes.

### FE-H4 — Admin WebSocket reads the wrong localStorage key
- `frontend/src/modules/admin/services/tiktok.ts:1633, 1655`
- Reads `localStorage.getItem('token')` / `sessionStorage.getItem('token')` —
  framework key is `auth_token`. The admin WS connects with empty
  `?token=` in real sessions; likely broken since day one.
- Fix: read `auth_token`. (Backend WS rejects empty token at L2014–2024,
  so the failure mode today is "WS doesn't work" not "WS is exposed",
  but the bug should be fixed.)

### FE-H5 — `document.write` interpolates unescaped `sessionId`
- `frontend/src/modules/livechat/components/LiveChatWidget.tsx:256–265`
- Risk: if session ID ever returns non-UUID content, it's
  `</p><script>…` injection in an opener-origin window with
  localStorage access.
- Fix: escape `sessionId` through the same helper used for `text`.

### FE-H6 — 401 refresh loop has no retry-count guard
- `frontend/src/api/client.ts:177–228`
- Availability concern (not exploitable): server-side permission flicker
  can chain refreshes faster than necessary, burning refresh-token
  rotation.
- Fix: add `__retryCount` on the request config; cap at 1.

### AUTH-Y6 — `GET /admin/users/{id}` requires `admin:write` (read endpoint, write dep)
- `backend/routes/admin/users.py:274`
- Inconsistent with the list endpoint at `:171` which uses
  `require_any_read_only(["admin:write"])`. Users with `admin:read`
  can list but not fetch a single user.
- Fix: swap to `require_any_read_only(["admin:write"])`.

### AUTH-Y7 — `GET /admin/rbac/roles/{id}/permissions` uses write dep instead of read-only
- `backend/routes/admin/rbac.py:919`
- Minor consistency issue; the dep enforces the same `admin:write`
  permission either way, but pins the read replica unnecessarily.
- Fix: swap `get_admin_write_permission` → `get_admin_write_permission_read_only`.

---

## MEDIUM — Defense-in-depth

### PUB-M1 — `cross-live-gifters.other_hosts` leaks non-public host names
- `backend/adapters/persistence/tiktok_persistence.py:2854–2876`
- Same shape as the C1 fix (filter by `is_public`), but in a separate
  service method. Public mirror at
  `/public/tiktok/lives/{handle}/cross-live-gifters` returns per-row
  `other_hosts: [{host, ...}]` containing every tracked host the viewer
  also gifted to — private handles leak.

### PUB-M2 — `cross-live-gifters` + `rooms/{room_id}/stats` lack top-level allowlist
- `backend/routes/public_tiktok.py:637, 667`
- Returns the raw service-method dict. Fail-open if persistence adds
  new fields.

### PUB-M3 — WS `get_public_handle_set()` 30s TTL bleed window
- `backend/routes/public_tiktok.py:474–492`,
  `backend/domain/services/tiktok_service.py:2639–2668`
- Privacy toggles bleed for up to 30s on connected WS clients. Either
  document as SLA or drop TTL to 5s.

### PUB-M4 — Redis `tiktok:events` channel is unfiltered
- `backend/adapters/tiktok_event_bus.py:31–58`
- All consumers must apply `passes_filter`. Add inline warning in
  `EventPublisher.publish`.

### FE-M1 — No CSP / X-Frame-Options / Referrer-Policy on `index.html`
- `frontend/index.html`
- At minimum add `<meta name="referrer" content="no-referrer">`.

### FE-M2 — `oauth_link_data` sessionStorage trust
- `frontend/src/contexts/AuthContext.tsx:67–76`
- An XSS that survives a single render cycle could inject a `link_data`
  shape with a forged `link_token`. Note: `oauth_link_intent` was
  replaced by the CSPRNG-state `oauth_flow_<provider>` keys in C4 —
  this finding is now narrower (only the `oauth_link_data` blob from
  Google's flow remains in this category).

### FE-M3 — PUT/DELETE in retry whitelist
- `frontend/src/api/client.ts:45–48`
- Review payment-adjacent PUT/DELETE endpoints to confirm idempotency
  before deciding whether to keep them in the whitelist.

### CFG-M1 — JWT payload `exp` trusted unverified
- `frontend/src/contexts/AuthContext.tsx:85`
- `atob(token.split('.')[1])` is decoded with no signature verification
  before scheduling proactive refresh. An attacker who can write to
  localStorage could insert a JWT with far-future `exp` to disable
  refresh. Compounds with FE-H2.

---

## LOW

### PUB-L1 — `/public/tiktok/lives/{handle}/status` missing enumeration counter
- `backend/routes/public_tiktok.py:529–564`
- The 3-state response (`not_found` / `private` / `public`) is the one
  intentional opacity-rule exception. No metrics counter to detect
  handle-enumeration scans.

### PUB-L2 — Stale module docstring
- `backend/routes/public_tiktok.py:26–31`
- Says `Cache-Control: public, max-age=15` but `_set_cache_headers` at
  `:188` emits `no-store`. Docstring should match.

### FE-L* — Console-leak hygiene
- Various `console.log` / `console.error` of request URLs, current
  path, server error responses. All gated by Vite's
  `mode === 'production'` drop. If staging is ever built non-prod,
  these surface.

---

## Recently Fixed (pre-prod audit cycle, 2026-05-12)

- **CFG-1 — Default JWT_SECRET fail-open boot.** Was: required explicit
  `PHOVEU_PRODUCTION=true` to bite. Now: fail-CLOSED — refuses to boot
  unless `PHOVEU_DEV_MODE=true` is set, regardless of any other env
  var. Fixed in `backend/api_main.py:113–127`. Docs updated in
  `.env.example`. Tracked as task #168.

- **PUB-C1 — `/public/tiktok/common-gifters/{user_id}/detail` leaked
  every non-public host name.** Was: hosts, whale_sessions, daily_series,
  intensity.biggest_session, recent_activity, identity_progression,
  loyalty.top_host all surfaced private handles to anonymous viewers
  who knew an active gifter's `user_id`. Now: `common_gifter_detail`
  accepts `public_only=True`, filters every host-emitting field through
  `is_public=True`. Fix verified live (`pulpiza` no longer surfaces).
  Tracked as task #164.

- **PUB-C2 — `gifters_by_side.totals.sibling_room_ids` leaked private
  opponent room ids.** Introduced earlier in the same week by the
  sibling-merge fix. Now: `get_match_gifters_by_side` accepts
  `public_only=True`, filters siblings by `is_public` before
  surfacing their `room_id` AND before merging their gift events.
  Tracked as task #165.

- **FE-C1 — JWT in URL query for livechat media.** Was: `?token=<JWT>`
  appended to `<img src>` / `<a href>` for livechat attachments
  (leaks to logs, Referer, history, autocomplete). Now: backend
  `/media/livechat/*` and `/media/tickets/*` no longer accept
  `?token=`; require `Authorization: Bearer` header. Frontend uses
  new `<AuthImage>` / `<AuthLink>` components in
  `frontend/src/components/AuthMedia.tsx` that fetch via XHR + blob
  URLs. Guest path (`?session_token=`) preserved — bounded blast
  radius. Tracked as task #166.

- **FE-C2 — OAuth state / PKCE / nonce missing.** Was: GitHub +
  Facebook authorize URLs built with no `state`, callbacks accepted
  whatever `?code=` arrived (login CSRF + account fixation
  primitives). Now: CSPRNG `state` generated in `startOAuthFlow`
  (`frontend/src/utils/oauthState.ts`), persisted in sessionStorage,
  verified in callbacks via `consumeOAuthFlow` (single-use, 10-min
  TTL, length-and-XOR compare). Sign-in buttons + the
  link-from-settings path all send state; callbacks reject mismatches.
  Google flow uses `@react-oauth/google` implicit access-token via
  postMessage — origin-checked by the library, not affected.
  Tracked as task #167.

- **AUTH-Y1..Y5 — Five admin mutation endpoints gated by
  `require_any_read_only` (read dep) instead of `require` (write dep).**
  `admin:read` could pause/resume/kill the listener, release a worker
  slot, and create notifications. Fixed in
  `backend/routes/admin/tiktok.py:805, 824, 841, 866, 1525`. Tracked
  as task #169.

---

## Counts

| Severity | Open | Recently Fixed |
|---------:|-----:|---------------:|
| CRITICAL | 0    | 5              |
| HIGH     | 2 (8 call sites) + 7 FE/AUTH = 9 entries | 5 |
| MEDIUM   | 8    | 0              |
| LOW      | 3+   | 0              |

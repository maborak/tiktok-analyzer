# TikFinity-Electron Static Analysis: How They Send Chat Messages

> **Disclaimer.** This is reverse-engineered analysis of the third-party `TikFinity-Electron`
> bootstrap (https://github.com/zerodytrash/TikFinity-Electron) and its remotely-fetched
> `bridge.js` payload. All work was done from publicly distributed binaries / public source
> for compatibility/learning purposes. Findings here may be incomplete or wrong; the
> remote `bridge.js` they ship is heavily obfuscated (obfuscator.io string-array, control-flow
> flattening, dead-code) and we only deobfuscated it well enough to read the chat / network
> path — not every branch.
>
> Nothing in this document is a verbatim copy of their code; everything is paraphrased.

Inputs analyzed:

- `/tmp/tikfinity-app/index.js` — 51-line bootstrap that fetches `electron/main.js` from
  the TikFinity server at `https://tikfinity.zerody.one` (or `tikfinity-origin.zerody.one`
  fallback) and `require()`s it from `userData/res/main.js`.
- `/tmp/tikfinity-main.js` — 1227-line Electron main process (cleartext).
- `/tmp/tf-bridge.js` — heavily obfuscated 91 KB preload (`tiktok_live_bridge_electron.user.js`
  on the server side). Manually deobfuscated to `/tmp/tf-bridge-deobf.js` (~1400 lines) by
  capturing the `_0x11c5(idx)` decoder via `vm.runInContext`, walking all `_0xXXXXXX(a,b,c,d)`
  wrapper functions (78 of them, recursively chained), and substituting all 1038 wrapper calls
  with their literal strings. Property-name aliases on the per-function "alias object"
  (`_0x33dba5['DAISD']` => `"log"`, etc.) are still present but trivial to read inline.

---

## 1. Architecture overview

1. **Bootstrap (`index.js`)** runs in the published Electron app. It fetches `main.js` from
   the TikFinity server, writes it to `userData/res/main.js`, and `require()`s it. So the
   "real" main process is server-controlled and updates without a release.
2. **Main process (`main.js`)** at runtime fetches several auxiliary scripts from the same
   server and writes them to `userData/res/`:
   - `bridge.js` — preload for TikTok windows (the obfuscated one we analyzed)
   - `cookies.js`, `fetchhelper.js`, `closeonredirect.js`,
     `autoupdater.forge.js`, `autoupdater.electronbuilder.js`,
     `websocketserver.js`, `keyboardlistener.js`
   - It also writes a `preload.js` to disk as a string literal, which is the preload for the
     **main** TikFinity window (their own UI hosted at `tikfinity.zerody.one`). That preload
     uses `contextBridge.exposeInMainWorld('API', { … })` so the renderer can call
     `API.toMain({action:'fetchUrl', …})` and similar.
3. **Main window**: `BrowserWindow({ minWidth:1230, webPreferences:{ preload: <preload.js>,
   backgroundThrottling:false, allowRunningInsecureContent:true } })`.
   It loads `process.env.TIKFINITY_HOST` (`https://tikfinity.zerody.one/`).
   Their UI sets the user agent for that window via
   `mainWindow.webContents.setUserAgent(originalUA)` (so it carries the standard Electron UA),
   while `app.userAgentFallback` is overridden globally to a TikTokLIVEStudio-flavored UA
   (see `main.js:81`).
4. **Child TikTok window(s)**: When the renderer calls `window.open('https://www.tiktok.com/...#tfbridge')`,
   `setWindowOpenHandler` in `main.js:1069` intercepts it and overrides options:

   ```text
   webPreferences: {
     preload: <RES_DIR>/bridge.js,
     contextIsolation: false,        // <-- key for Node access in renderer
     backgroundThrottling: false
   },
   height: random(900..1200),
   width:  random(1800..2300),
   show:   false  (unless URL has show=1)
   ```

   The randomized window dimensions are visible to webcast scripts via `screen.*`/`window.inner*`,
   which is a soft anti-fingerprinting touch. Random per-process — not per-account.
5. **Bridge (`bridge.js`)** runs as preload in that hidden TikTok window.
   With `contextIsolation:false`, it can do anything in the page context. It:
   - Listens for `window.addEventListener('message', …)` from the parent window
     (`window.opener`, the TikFinity main window).
   - Posts events back via `window.opener.postMessage({app:'tfbridge', type, info, …}, '*')`.
   - On startup, polls `https://www.tiktok.com/api-live/user/room/?aid=1988&sourceType=54&uniqueId=…`
     to resolve the broadcaster's `roomId` and confirm the live status.
   - Reads the page's SSR `<div id="api-domains">` JSON to get the actual webcast host
     (`webcast4-normal-useast1a.tiktok.com` or similar regional CDN).
   - Connects directly to `wss://…/webcast/im/push/v2/` (after `/webcast/im/fetch/?…`
     hands back a "WS upgrade" descriptor with cursor + token), receives protobuf-encoded
     chat messages, decodes them, and forwards them to `opener` via postMessage.
   - **Sends chat** by calling `fetch()` against `/webcast/room/chat/` (see Section 2).

6. **Login window**: a separate BrowserWindow opened with `closeonredirect.js` preload when
   the URL has `#ttlogin` / `#ttlogout`. Different size, no contextIsolation override.
7. **WebSocket server (port 21213, `127.0.0.1`)**: `main.js:1132–1151`. This is a `ws` server
   that lets local clients (their "DAPI") connect and listen to events relayed from the
   renderer. Not relevant to chat-send but explains the `dapiClientConnected` handler.

```
  ┌──────────────────────────────────────────────────────┐
  │ Electron main process (main.js, fetched from server) │
  │  - userAgentFallback patched                         │
  │  - webRequest hooks (CORS rewrites for TikTok APIs)  │
  │  - bytedance:// protocol blocked                     │
  └──────────────────────────────────────────────────────┘
            │                    │
            │ preload.js         │ bridge.js (preload, contextIsolation:false)
            ▼                    ▼
  ┌──────────────────────┐  ┌──────────────────────────────┐
  │ MainWindow           │  │ TikTok BrowserWindow         │
  │ tikfinity.zerody.one │◄─┤ www.tiktok.com/<user>/live   │
  │  (their UI)          │──►   (hidden, randomized size)  │
  │                      │  │  bridge.js handles cmds &    │
  │ window.open(url)     │  │  posts events back via       │
  │  + #tfbridge          │  │  window.opener.postMessage  │
  └──────────────────────┘  └──────────────────────────────┘
```

---

## 2. Message-send flow (the headline answer)

**They do not interact with the DOM at all.** No selectors, no input field, no click,
no synthetic Enter key, no focus, no execCommand. They issue a **direct HTTP POST** to
TikTok's webcast `room/chat` API from inside the TikTok-origin BrowserWindow, riding on
the cookies the user already has from logging in to that same window.

Sequence (deobfuscated `bridge.js`, around line 894–989; alias-object lookups still present
but trivial to read):

1. Parent window posts a message: `{ cmd: 'sendChatMsg', data: { messageText: '...' } }`
   via `tiktokWindow.postMessage(...)` (or `child.webContents.executeJavaScript('window.postMessage…')`,
   either works — both arrive in the bridge's `'message'` handler).
2. Bridge listener at `bridge.js:894` fires. It switches on `data.cmd`. The `'sendChatMsg'`
   case starts at line 928.
3. Pre-checks:
   - `messageText` non-empty
   - `webcastApiHost` resolved (`_0x151a0e` in the deobfuscated source)
   - `roomId` resolved (`_0x3f5c39`)

   If any is missing, throws `'WrongState'`.
4. Resolves the webcast API host once at startup from
   `JSON.parse(document.getElementById('api-domains').innerText).webcastApi`,
   strips the leading `https://`, and caches it in a module-scoped variable. If that fails
   it falls back to the literal `'webcast.tiktok.com'`.
5. Builds the URL by string-concat (line 933 in `tf-bridge-deobf.js`). Reconstructed:

   ```
   https://{WEBCAST_HOST}/webcast/room/chat/?aid=1988
     &app_language=en-US
     &app_name=tiktok_web
     &browser_language=en
     &browser_name=Mozilla
     &browser_online=true
     &browser_platform=Win32
     &browser_version=5.0%20(Windows%20NT%2010.0;%20Win64;%20x64)%20AppleWebKit/537.36%20(KHTML,%20like%20Gecko)%20Chrome/135.0.0.0%20Safari/537.36
     &channel=tiktok_web
     &content={URL-ENCODED MESSAGE TEXT}
     &cookie_enabled=true
     &data_collection_enabled=true
     &device_id=                       ← intentionally empty
     &device_platform=web_pc
     &emotes_with_index=
     &focus_state=true
     &from_page=
     &history_len=6
     &is_fullscreen=false
     &is_page_visible=true
     &os=windows
     &priority_region=US
     &referer=https%3A%2F%2Fwww.tiktok.com%2F
     &region=US
     &room_id={ROOM_ID}
     &root_referer=https%3A%2F%2Fwww.tiktok.com%2F
     &screen_height=1152
     &screen_width=2048
     &tz_name=Europe%2FBerlin
     &user_is_login=true
     &webcast_language=en-US
   ```

   Two notes:
   - The URL hard-codes `tz_name=Europe/Berlin` and the Win11 desktop UA. They do **not**
     try to vary these per session — the only randomized values are the BrowserWindow size
     in `main.js`.
   - `aid` is `1988` normally, but when `window.chfi` is set (a flag they raise on a prior
     malformed-response, line 953) they prefix it to `01988`. This looks like a "did the
     CDN/Workers strip it" defensive retry, not anti-detect.

6. Performs `fetch(url, options)` where options are:

   ```js
   {
     method: 'POST',
     credentials: 'include',                                    // sends tt_csrf_token, sessionid etc.
     headers: { 'content-type': 'application/json; charset=UTF-8' },
     body: JSON.stringify({ content: <messageText>, emotes_with_index: '', room_id: <ROOM_ID> })
   }
   ```

   No `Authorization`, no `msToken`, no `X-Bogus`, no `X-Gnarly`, no `tt_csrf_token` set
   manually. Cookies cover auth; CSRF and signing are added by **TikTok's own webcast
   bundle** that the page loaded (the same SDK that powers tiktok.com/<user>/live). The
   bridge inherits the CSRF + signature pipeline that TikTok's runtime injected into
   `window.fetch` / XHR for that origin.
7. Reads response body as text, parses as JSON. Success when `status_code === 0`. On error
   it pulls `data.message` / `data.prompts` / `status_code` for diagnostics.
8. Posts `{ type: 'chatResult', info: { messageText, success, error } }` back to opener.

> **The killer simplification:** they let TikTok's own page sign the request. Because the
> bridge runs same-origin in the actual `tiktok.com` page (not a headless Playwright
> instance), every page load brings the live webcast SDK and its `fetch`/XHR shim with it.
> All the `msToken`, `X-Bogus`, `X-Gnarly` math gets done by tiktok.com's own JS.

---

## 3. Stealth techniques

This is the most interesting *negative* finding. **The bridge does no JS-environment patching.**

Searches across the deobfuscated 1400-line file return **no** matches for:

- `Object.defineProperty` (no `navigator.webdriver` override, no plugin spoof)
- `Function.prototype.toString` (no anti-toString patch)
- `chrome.loadTimes`, `chrome.csi`, `Notification.permission`
- `userAgentData`, `WebGLRenderer`, `iframeContentWindow`
- `Permissions.query`
- `dispatchEvent`, `KeyboardEvent`, `MouseEvent` (no automation events)

The only "stealth" they apply is at the **process / network layer** in `main.js`:

- `app.userAgentFallback` is replaced with a fixed TikTokLIVEStudio UA (`main.js:81`).
  This is what hits any external request that doesn't override its UA.
- The TikTok BrowserWindow is created with `mainWindow.webContents.setUserAgent(originalUA)`
  for the *main* window (their own site), but the child TikTok windows inherit
  `app.userAgentFallback` which by then has been overridden.
- Random window size (`width 1800–2300, height 900–1200`).
- `bytedance://` protocol is registered and unconditionally cancelled
  (`main.js:663–674`) — that's the URL scheme TikTok's anti-fraud SDK tries to use to
  open their native MSDK helper on Windows; cancelling it neutralizes a probe without a
  visible failure. Worth replicating.
- They DO carry the standard Electron renderer JS env, including `navigator.webdriver===false`
  by default in Electron (Electron does not set `webdriver=true` the way Playwright/Puppeteer
  do). That alone removes one major fingerprinting tell.
- `contextIsolation:false` in the TikTok window — this is the inverse of "stealth" in the
  Playwright sense. The bridge is part of the page; TikTok's scripts can see and call its
  globals. They lean into being a page-co-resident extension rather than an external puppet.

So: **the stealth they rely on is mostly "be Electron, not Chromium-via-CDP"**. Electron
ships with `navigator.webdriver` = false out of the box, no `cdc_` injected globals, no
`HeadlessChrome` UA, no `--enable-automation` flag, no Page.addScriptToEvaluateOnNewDocument
trace, etc. Combined with letting TikTok's own fetch shim sign the request, there's just
not much surface left for TikTok's bot detection to bite on.

---

## 4. HTTP-layer manipulations (`main.js`, the cleartext side)

These are in `main.js:692–850` — `webRequest.onHeadersReceived` and `onBeforeSendHeaders`:

### onHeadersReceived

Filtered to: `https://*.tiktok.com/*`, `accounts.spotify.com`, `clienttoken.spotify.com`,
`api-partner.spotify.com`, `*.easemob.com`, `*.agora.io`.

For TikTok specifically:

- Strips `content-security-policy` (and `-report-only` variants) from any
  `https://www.tiktok.com/*` response. This is what lets the bridge's locally-injected
  scripts and inline event handlers run inside tiktok.com without CSP violations.
- For any `webcast` URL, appends `x-mssdk-info` to `Access-Control-Allow-Headers` so
  TikTok's anti-fraud SDK header is allowed cross-origin.
- For `/webcast/room/chat`, completely rewrites CORS headers (adds an aggressive
  `Access-Control-Allow-Headers` list including `X-Tt-Env`, `X-Use-Boe`, `X-Tt-Logid`,
  `X-Secsdk-*`, `Tt-Ticket-Guard-*`, `x-cthulhu-csrf`, etc.), forces
  `Access-Control-Allow-Origin: https://www.tiktok.com`,
  `Access-Control-Allow-Credentials: true`, and on `HEAD`/`OPTIONS` preflight responses
  it forges status to `200 OK` and **fakes a `x-ware-csrf-token` header**
  (`main.js:766`) when the upstream didn't return one. This is a key trick — it enables
  preflighted POSTs to `/webcast/room/chat/` that would otherwise fail because the
  browser couldn't satisfy CORS.

### onBeforeSendHeaders

For TikTok URLs they don't touch outgoing headers (they let TikTok's own fetch shim and
cookies handle it). For Spotify/Younow/Agora/Easemob they swap in random Chrome desktop
UAs and Younow Origin/Referer (decoy). Not relevant to chat.

### Cookie handling

There's a `cookies.js` (downloaded at runtime) that does export/restore against backups
written under `userData`. It's used to preserve the TikTok session across version updates.
`browser_profile/` is the persistent Chromium user-data dir used by Electron's default
session. **Login persists in the Chromium profile**, which is critical: they only log in
once per machine, and every subsequent run reuses the cookies (just like a real browser).

---

## 5. Selectors and DOM hooks used

- `document.getElementById('api-domains').innerText` — TikTok's SSR JSON blob with the
  webcast API host. Read once at bridge init.
- That's it. **No chat input selector, no send button, no message-list selector, no
  `data-e2e` lookups.** The bridge does not read or write the chat UI at all.

(Their main UI window does its own thing on `tikfinity.zerody.one`, but that's their own
React app, not TikTok.)

---

## 6. Actionable delta vs. our current Playwright approach

Our project (`tiktok-bot/frontend`) currently drives a vendored Chromium via Playwright,
finds the chat input, types into it, and clicks send. Compared to TikFinity:

| Dimension | TikFinity | Ours |
|---|---|---|
| Browser engine | Electron (Chromium under our control, but **not** marked as automated) | Playwright launches Chromium with `--enable-automation` and the WebDriver protocol |
| `navigator.webdriver` | `false` (Electron default) | `true` unless explicitly patched |
| Send mechanism | Direct `fetch` POST `/webcast/room/chat/` with cookies, body `{content, room_id, emotes_with_index}` | DOM input → click |
| Signing (`msToken`, `X-Bogus`, `X-Gnarly`) | Done by TikTok's own loaded webcast bundle (free) | Same, if we use a real browser tab |
| CSRF | Bypassed via `webRequest.onHeadersReceived` rewrite + forged `x-ware-csrf-token` on preflight | Bypassed by browser doing real preflight |
| Cookies / login | Persisted in Electron's `userData/browser_profile/`, login once per machine | Playwright `storageState` or persistent context |
| Dock / taskbar icon | Hidden TikTok windows (`show:false`); main UI window only | Playwright's Chromium always brings up a dock icon on macOS |
| CSP | Stripped via `webRequest.onHeadersReceived` so they can inject scripts | N/A (they're driving an actual TikTok tab) |
| Anti-detect navigator patches | None | None we've added |
| Random fingerprint variation | Window size only | None |

**The most actionable items for our app**, ordered by impact:

1. **Switch from Playwright to Electron `BrowserWindow`s.** This single change moves us
   from "automated Chromium that announces itself" to "regular Chromium". Electron does
   not set `navigator.webdriver`, doesn't inject `cdc_*` globals, and doesn't run with the
   `--enable-automation` flag set on Chromium. Most "is this a bot?" sniffers are
   defeated by this alone.

2. **Hide the visible TikTok window.** Open it with `show:false` and `webPreferences.preload`
   pointing at a script that does the work. On macOS this still shows a dock icon for the
   *app*, but not for the hidden window. To suppress the dock entirely use
   `app.dock.hide()` — Electron supports it; Playwright's launched Chromium does not, hence
   the icon you can't kill today.

3. **Send chat via direct fetch from the same-origin TikTok page**, not via DOM. Once we're
   in an Electron BrowserWindow loaded on `https://www.tiktok.com/<user>/live`, all of
   TikTok's webcast SDK is loaded into the page, and `fetch('/webcast/room/chat/?…', {…,
   credentials:'include', body: JSON.stringify({content, room_id, emotes_with_index:''})})`
   "just works". No selector brittleness; no input-event simulation; the body is trivial.

4. **Strip CSP via `session.defaultSession.webRequest.onHeadersReceived`** for
   `https://www.tiktok.com/*`, exactly as `main.js:708–713`. This lets us inject our
   bridge as a preload script via `webPreferences.preload` and let it run inline.

5. **Forge `x-ware-csrf-token` on preflight HEAD/OPTIONS** for `/webcast/room/chat`
   (`main.js:765–774`). Without this, Chrome fails the preflight and the `fetch` never
   ships. This is the single non-obvious trick that makes the cross-origin chat POST work.
   Token value they hardcode (constants change — this is one snapshot):
   `0,0001000000012db621dc1c8a3d754421950a085bb964d1c3fbe73ca0d82b62ae44dabe2937cf183971c03b415a31,86370200,success,3cd8260afaef2dfe8830cc1c7dd9d8ff`.
   It only needs to satisfy the preflight; the actual POST round-trips with whatever
   token TikTok's own webcast SDK adds via headers.

6. **Add `Access-Control-Allow-Headers: …,x-mssdk-info,…` rewrite** for `*webcast*` URLs
   (`main.js:738–746`). TikTok's MSDK adds `x-mssdk-info` to outgoing webcast requests; if
   the server preflight doesn't whitelist it, the request fails.

7. **Block the `bytedance://` protocol** (`main.js:663–674`) by registering it and calling
   `callback({cancel:true})`. TikTok's anti-fraud SDK sometimes probes for the native
   `MSSDK://bytedance` helper; failure-by-cancel looks like "not installed" rather than
   "trapped".

8. **`contextIsolation:false`** for the TikTok preload window. Required if you want your
   preload to share globals with the page (and to read `document.getElementById('api-domains')`
   directly). Yes, it's a security tradeoff; for a single-purpose tool talking to one
   site, it's worth it.

9. **Use a persistent user-data dir** (Electron default `userData/`). Then login is
   one-time and survives upgrades — exactly what TikFinity does with their
   `browser_profile/` move and `cookies.js` backup/restore.

10. **Don't attempt navigator/UserAgent fingerprint spoofing.** TikFinity proves you don't
    need it. The single change "Electron, not headless Chromium" gets you the rest of the
    way. Adding fingerprint patches actually creates new tells (e.g., a `webdriver` getter
    that returns `false` from a non-prototype location).

---

## 7. Open questions / things obfuscation hides

- **Exact protocol of the WebSocket frames sent BACK to TikTok's webcast WS** — we can see
  they `WebSocket.send()` a manually-constructed protobuf message with field tags `6`, `7`,
  `8` and a BigInt room_id (line 1248–1253). We didn't trace their full schema. Not
  required for chat-send (chat is HTTP POST, separate from the IM WebSocket).
- **The `chfi` fallback path** — when `window.chfi` is set, the URL `aid` becomes `01988`
  and a `replace(...)` swaps something on the URL. We didn't fully decode the alias-object
  references for `gDEgT`/`GzhjY`/`ZrzMW`. Looks like a CDN-host fallback (wcsg/wcaeue
  variants). Not load-bearing.
- **Anti-bridge guards** — we noted a `window.bridgeInjected` check (line 841) preventing
  double-injection, and a `__agencyChecked` flag (line 815) gating the agency-info fetch
  to once-per-day. No other anti-introspection patterns in the bridge.
- **The "errorCount > 6 → ApplyFix1 / ApplyFix2" branches** — there's some self-healing
  logic with two named fix paths (`Bridge alr`eady`inject`ed, `Bridge\x20alr`+`eady\x20injec`+`ted`,
  etc.). We didn't trace what `ApplyFix1` and `ApplyFix2` do — likely WS reconnect with
  different parameters. Not chat-relevant.
- **Whether they hold a long-lived `tt_csrf_token` cookie value or rely on it being set
  by the page** — we didn't observe explicit cookie reads. The page's webcast SDK
  manipulates `document.cookie`; the bridge piggybacks on it transparently.
- **Whether `tt_csrf_token` is the only relevant CSRF, or whether `x-secsdk-csrf-token`
  matters too** — both are in the CORS allow-list rewrite, suggesting both can appear.
- **Their server-side `extension/tiktok_live_bridge_electron.user.js` could change at any
  time.** Anything we copy is a snapshot. We should treat the technique (HTTP POST +
  Electron + CSRF preflight forge) as durable, but the parameter list and CDN host
  resolution could shift.

---

## 8. Files of record

- `/tmp/tikfinity-app/index.js` — bootstrap (cleartext)
- `/tmp/tikfinity-main.js` — main process, full source (cleartext)
- `/tmp/tf-bridge.js` — original obfuscated preload
- `/tmp/tf-bridge-deobf.js` — manually deobfuscated preload, ~1400 lines, mostly readable
- `/tmp/decoder-strings.json` — extracted string table from the obfuscator
- `/tmp/wrappers.json` — table of wrapper-function offsets used during deobfuscation
- `/tmp/deobf-step{1..7}.js` — the deobfuscation pipeline scripts

The deobfuscated file still has alias-object lookups (`_0x33dba5["DAISD"]`) and
control-flow flattening artifacts. Property names like `DAISD` are mostly resolved by
reading the `_0x33dba5` initializer at the top (lines 31–360). Numeric switch dispatch
constants (e.g., `0x1289+-0x11a5*-0x1+-0x242c`) are the protobuf wire-type codes
(0=varint, 1=fixed64, 2=length-delimited, 5=fixed32) and don't need further work.

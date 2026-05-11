/**
 * Hidden Electron BrowserWindow that owns the TikTok page. Posts
 * comments via the in-page bridge (window.__tfBot.sendChat) using
 * fetch — no DOM automation.
 *
 * Two modes for the same window:
 *   - LOGIN  → small (480×780), centered, visible. User logs in here.
 *   - POSTING → randomly sized (1800-2300 × 900-1200), hidden offscreen.
 *               Random size is light fingerprint variation TikFinity uses.
 *
 * The window switches between modes by resizing + show()/hide(). One
 * BrowserWindow lifecycle, two visual states.
 */

import { BrowserWindow, session } from "electron";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PARTITION = "persist:tiktok";
const IDLE_URL = "https://www.tiktok.com/setting";
const LOGIN_URL = "https://www.tiktok.com/login";

const LOGIN_POLL_INTERVAL_MS = 1000;
const LOGIN_TIMEOUT_MS = 180_000;

// Compact login window — fits TikTok's QR code + login form comfortably.
const LOGIN_BOUNDS = { width: 480, height: 780 };

// Random posting window dimensions (offscreen, never visible).
const POSTING_MIN = { width: 1800, height: 900 };
const POSTING_MAX = { width: 2300, height: 1200 };

const MIN_SEND_INTERVAL_MS = 2500;
const SEND_JITTER_MAX_MS = 1000;

function randInt(lo: number, hi: number): number {
  return Math.floor(Math.random() * (hi - lo + 1)) + lo;
}

function resolveBridgePreload(): string {
  for (const name of [
    "tiktok-bridge.mjs",
    "tiktok-bridge.cjs",
    "tiktok-bridge.js",
  ]) {
    const p = path.join(__dirname, name);
    if (existsSync(p)) return p;
  }
  throw new Error(`tiktok-bridge preload not found in ${__dirname}`);
}

export type SendResult =
  | { ok: true }
  | {
      ok: false;
      error:
        | "not_logged_in"
        | "not_on_live"
        | "rate_limited"
        | "send_failed";
      detail?: string;
      retryAfterMs?: number;
    };

export class TikTokWindow {
  private win: BrowserWindow | null = null;
  private currentRoomId: string | null = null;
  private webcastHost: string | null = null;
  private lastSendAt = 0;
  private appIcon: string | undefined = undefined;

  setAppIcon(p: string): void {
    this.appIcon = p;
  }

  // ── lifecycle ─────────────────────────────────────────────────────

  /**
   * Returns the existing window, or creates a new one in POSTING mode
   * (offscreen, randomized size). Used by sendComment + navigateToLive.
   */
  private ensureWindow(): BrowserWindow {
    if (this.win && !this.win.isDestroyed()) return this.win;

    this.win = new BrowserWindow({
      width: randInt(POSTING_MIN.width, POSTING_MAX.width),
      height: randInt(POSTING_MIN.height, POSTING_MAX.height),
      show: false,
      icon: this.appIcon,
      webPreferences: {
        partition: PARTITION,
        preload: resolveBridgePreload(),
        // contextIsolation:false is the key — preload globals merge with
        // the page's window, so __tfBot.* is callable as page JS and
        // shares the page's own fetch (which has TikTok's signing).
        contextIsolation: false,
        nodeIntegration: false,
        sandbox: false,
        backgroundThrottling: false,
      },
    });

    this.win.webContents.setAudioMuted(true);

    // Park on a lightweight TikTok page. Doesn't matter much;
    // navigateToLive replaces it.
    void this.win.loadURL(IDLE_URL);

    this.win.on("closed", () => {
      this.win = null;
    });

    return this.win;
  }

  async close(): Promise<void> {
    if (this.win && !this.win.isDestroyed()) {
      this.win.close();
    }
    this.win = null;
  }

  // ── auth ──────────────────────────────────────────────────────────

  async isLoggedIn(): Promise<boolean> {
    const ses = session.fromPartition(PARTITION);
    const cookies = await ses.cookies.get({ domain: ".tiktok.com" });
    return cookies.some(
      (c) => c.name === "sessionid" || c.name === "sessionid_ss",
    );
  }

  /**
   * Extract the persisted TikTok session cookie + companion fields so the
   * web UI can hand them off to the backend's sign-engine config. We use
   * the `sessionid` cookie value (matches TikTokLive's `set_session(...)`
   * input) and the `tt-target-idc` cookie when present (some accounts
   * need it paired with sessionid).
   *
   * Returns null fields when the user isn't logged in. Caller is expected
   * to trigger `login()` first if needed.
   */
  async getSessionCookies(): Promise<{
    session_id: string | null;
    tt_target_idc: string | null;
  }> {
    const ses = session.fromPartition(PARTITION);
    const cookies = await ses.cookies.get({ domain: ".tiktok.com" });
    const sid =
      cookies.find((c) => c.name === "sessionid")?.value ??
      cookies.find((c) => c.name === "sessionid_ss")?.value ??
      cookies.find((c) => c.name === "sid_tt")?.value ??
      null;
    const idc = cookies.find((c) => c.name === "tt-target-idc")?.value ?? null;
    return { session_id: sid, tt_target_idc: idc };
  }

  async login(): Promise<{ logged_in: boolean; error?: string }> {
    const win = this.ensureWindow();

    // Resize to a sane login dimension and center on screen.
    win.setResizable(true);
    win.setSize(LOGIN_BOUNDS.width, LOGIN_BOUNDS.height);
    win.center();

    try {
      await win.loadURL(LOGIN_URL);
    } catch {
      /* ignore — we'll poll */
    }

    win.show();
    win.focus();

    const deadline = Date.now() + LOGIN_TIMEOUT_MS;
    let loggedIn = false;
    while (Date.now() < deadline) {
      if (await this.isLoggedIn()) {
        loggedIn = true;
        break;
      }
      await sleep(LOGIN_POLL_INTERVAL_MS);
    }

    // Hide BEFORE navigating away — the user shouldn't see the /setting
    // flash. Also resize back to posting dimensions for next use.
    win.hide();
    win.setSize(
      randInt(POSTING_MIN.width, POSTING_MAX.width),
      randInt(POSTING_MIN.height, POSTING_MAX.height),
    );
    win.setResizable(false);

    if (loggedIn) {
      // Park on idle URL in the background so the session stays warm
      // and ready for the next navigateToLive call.
      win.loadURL(IDLE_URL).catch(() => {});
      return { logged_in: true };
    }
    return { logged_in: false, error: "login timed out" };
  }

  async logout(): Promise<void> {
    const ses = session.fromPartition(PARTITION);
    await ses.clearStorageData({
      storages: [
        "cookies",
        "localstorage",
        "indexdb",
        "websql",
        "serviceworkers",
      ],
    });
    if (this.win && !this.win.isDestroyed()) {
      try {
        await this.win.loadURL(IDLE_URL);
      } catch {
        /* ignore */
      }
    }
    this.currentRoomId = null;
  }

  // ── live navigation ───────────────────────────────────────────────

  async navigateToLive(username: string): Promise<void> {
    const handle = username.replace(/^@/, "");
    if (!handle) throw new Error("username required");

    const win = this.ensureWindow();
    const url = `https://www.tiktok.com/@${handle}/live`;
    console.log(`[tt] navigateToLive @${handle}`);
    try {
      await win.loadURL(url);
    } catch (e) {
      console.warn(`[tt] navigateToLive failed: ${e}`);
      return;
    }

    this.currentRoomId = null;

    // Wait for the bridge preload to expose __tfBot. The page may
    // navigate-redirect (region routing) so the preload runs more than
    // once; we poll until __tfBot is present.
    const bridgeReady = await this._waitForBridge(win, 5000);
    if (!bridgeReady) {
      console.warn(`[tt] __tfBot never appeared on @${handle}/live`);
      return;
    }

    // Retry resolveRoom — TikTok's api-live can return null briefly
    // after navigation while the page warms up.
    for (let attempt = 1; attempt <= 4; attempt++) {
      try {
        const room = (await win.webContents.executeJavaScript(
          `window.__tfBot.resolveRoom(${JSON.stringify(handle)})`,
          true,
        )) as { roomId?: string; status?: number } | null;
        if (room?.roomId) {
          this.currentRoomId = room.roomId;
          console.log(
            `[tt] resolved room_id=${room.roomId} status=${room.status} (attempt ${attempt})`,
          );
          break;
        }
        console.log(`[tt] resolveRoom attempt ${attempt} returned null`);
      } catch (e) {
        console.warn(`[tt] resolveRoom attempt ${attempt} threw: ${e}`);
      }
      await sleep(700);
    }

    if (!this.currentRoomId) {
      console.warn(
        `[tt] could not resolve room_id for @${handle} after retries`,
      );
    }

    try {
      this.webcastHost = (await win.webContents.executeJavaScript(
        `window.__tfBot.getWebcastHost()`,
        true,
      )) as string | null;
      if (this.webcastHost) {
        console.log(`[tt] webcast host=${this.webcastHost}`);
      }
    } catch (e) {
      console.warn(`[tt] webcast host lookup failed: ${e}`);
    }
  }

  /** Poll until window.__tfBot is defined or timeout. */
  private async _waitForBridge(win: BrowserWindow, timeoutMs: number): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const has = (await win.webContents.executeJavaScript(
          `Boolean(window.__tfBot && window.__tfBot.resolveRoom)`,
          true,
        )) as boolean;
        if (has) return true;
      } catch {
        /* navigation in flight, keep polling */
      }
      await sleep(150);
    }
    return false;
  }

  // ── posting ───────────────────────────────────────────────────────

  async sendComment(text: string): Promise<SendResult> {
    const trimmed = text.trim();
    if (!trimmed) {
      return { ok: false, error: "send_failed", detail: "empty" };
    }
    if (!(await this.isLoggedIn())) {
      return { ok: false, error: "not_logged_in" };
    }
    if (!this.currentRoomId) {
      return {
        ok: false,
        error: "not_on_live",
        detail: "no room — connect to a live first",
      };
    }

    const now = Date.now();
    const since = now - this.lastSendAt;
    if (since < MIN_SEND_INTERVAL_MS) {
      return {
        ok: false,
        error: "rate_limited",
        retryAfterMs: MIN_SEND_INTERVAL_MS - since,
      };
    }
    this.lastSendAt = now;
    await sleep(Math.random() * SEND_JITTER_MAX_MS);

    const win = this.ensureWindow();
    const host = this.webcastHost ?? "webcast.tiktok.com";

    const js = `(async () => {
      if (!window.__tfBot) return { ok: false, statusCode: -1, detail: 'bridge missing' };
      return await window.__tfBot.sendChat(
        ${JSON.stringify(trimmed)},
        ${JSON.stringify(this.currentRoomId)},
        ${JSON.stringify(host)},
      );
    })()`;

    let result: {
      ok: boolean;
      statusCode?: number;
      message?: string;
      detail?: string;
    };
    try {
      result = (await win.webContents.executeJavaScript(js, true)) as typeof result;
    } catch (e) {
      return { ok: false, error: "send_failed", detail: String(e) };
    }

    if (result.ok) {
      console.log(`[tt] chat sent ok: ${trimmed}`);
      return { ok: true };
    }
    console.warn(`[tt] chat failed`, result);
    return {
      ok: false,
      error: "send_failed",
      detail:
        result.detail ??
        result.message ??
        `status_code ${result.statusCode ?? "?"}`,
    };
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

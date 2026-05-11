/**
 * In-page bridge: runs as preload (with contextIsolation:false) inside
 * the hidden TikTok BrowserWindow. Mirrors TikFinity's bridge.js
 * approach (see docs/tikfinity-analysis.md §2).
 *
 * Exposes window.__tfBot.{ resolveRoom, sendChat, isLoggedIn } to the
 * page's main world. The Electron main process invokes these via
 * webContents.executeJavaScript('window.__tfBot.sendChat(...)') and
 * awaits the returned Promise.
 *
 * The whole point: we never touch the chat UI. We call the webcast HTTP
 * API directly. TikTok's already-loaded page JS has wrapped window.fetch
 * to add msToken / X-Bogus / X-Gnarly / tt_csrf_token automatically — so
 * our raw fetch with credentials:'include' rides on those signatures.
 */

declare global {
  interface Window {
    __tfBot?: {
      resolveRoom: (handle: string) => Promise<RoomInfo | null>;
      sendChat: (
        text: string,
        roomId: string,
        webcastHost: string,
      ) => Promise<ChatResult>;
      isLoggedIn: () => Promise<boolean>;
      getWebcastHost: () => string;
    };
    // TikTok's SSR JSON blobs — present on tiktok.com pages.
    SIGI_STATE?: Record<string, unknown> & {
      LiveRoom?: {
        liveRoomUserInfo?: {
          liveRoom?: { roomId?: string; id?: string; status?: number };
          user?: Record<string, unknown>;
        };
        roomInfo?: { roomId?: string; id?: string; status?: number };
      };
      UserModule?: { users?: Record<string, { roomId?: string }> };
    };
    __SIGI_STATE__?: Window["SIGI_STATE"];
  }
}

type RoomInfo = {
  roomId: string;
  uniqueId: string;
  status: number; // 2 = live
};

type ChatResult =
  | { ok: true; statusCode: 0 }
  | { ok: false; statusCode: number; message?: string; detail?: string };

const FALLBACK_HOST = "webcast.tiktok.com";

function getWebcastHost(): string {
  try {
    const el = document.getElementById("api-domains");
    if (!el) return FALLBACK_HOST;
    const j = JSON.parse(el.textContent || el.innerText || "{}");
    const host = (j.webcastApi || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
    return host || FALLBACK_HOST;
  } catch {
    return FALLBACK_HOST;
  }
}

async function resolveRoom(handle: string): Promise<RoomInfo | null> {
  // First attempt: TikTok's api-live endpoint.
  try {
    const u = `https://www.tiktok.com/api-live/user/room/?aid=1988&sourceType=54&uniqueId=${encodeURIComponent(handle)}`;
    const r = await fetch(u, { credentials: "include" });
    if (r.ok) {
      const j = await r.json();
      console.log("[tfBot] api-live response:", JSON.stringify(j).slice(0, 400));
      // Try every place the room id has been observed across responses:
      const fromUser = j?.data?.user?.roomId;
      const fromLive = j?.data?.liveRoom?.roomId ?? j?.data?.liveRoom?.id;
      const liveRoomStatus =
        j?.data?.liveRoom?.status ?? j?.data?.user?.status ?? 0;
      const roomId = String(fromUser ?? fromLive ?? "");
      if (roomId && roomId !== "0") {
        return {
          roomId,
          uniqueId: String(j?.data?.user?.uniqueId ?? handle),
          status: Number(liveRoomStatus) || 0,
        };
      }
    }
  } catch (e) {
    console.warn("[tfBot] api-live fetch failed:", e);
  }

  // Fallback: scrape the SSR'd JSON blob TikTok injects into the page.
  try {
    const fromState = window.SIGI_STATE ?? window.__SIGI_STATE__ ?? null;
    if (fromState) {
      const liveRoom =
        fromState.LiveRoom?.liveRoomUserInfo?.liveRoom ??
        fromState.LiveRoom?.roomInfo ??
        null;
      const userInfo =
        fromState.LiveRoom?.liveRoomUserInfo?.user ??
        fromState.UserModule?.users ??
        null;
      const rid =
        liveRoom?.roomId ??
        liveRoom?.id ??
        (userInfo && Object.values(userInfo)[0] as { roomId?: string })?.roomId;
      if (rid) {
        console.log("[tfBot] SIGI_STATE roomId:", rid);
        return {
          roomId: String(rid),
          uniqueId: handle,
          status: Number(liveRoom?.status ?? 0),
        };
      }
    }
  } catch (e) {
    console.warn("[tfBot] SIGI_STATE scrape failed:", e);
  }

  return null;
}

function buildChatUrl(host: string, roomId: string, content: string): string {
  // Most of these mirror what tiktok-web's own UI sends. The webcast
  // server validates room_id/content + cookies; the rest are tracking.
  const params = new URLSearchParams({
    aid: "1988",
    app_language: "en-US",
    app_name: "tiktok_web",
    browser_language: "en",
    browser_name: "Mozilla",
    browser_online: "true",
    browser_platform: navigator.platform,
    browser_version: navigator.userAgent.replace(/^Mozilla\/5\.0\s*/, ""),
    channel: "tiktok_web",
    content,
    cookie_enabled: "true",
    data_collection_enabled: "true",
    device_id: "",
    device_platform: "web_pc",
    emotes_with_index: "",
    focus_state: "true",
    from_page: "",
    history_len: "6",
    is_fullscreen: "false",
    is_page_visible: "true",
    os: "mac",
    priority_region: "",
    referer: "https://www.tiktok.com/",
    region: "",
    room_id: roomId,
    root_referer: "https://www.tiktok.com/",
    screen_height: String(screen.height),
    screen_width: String(screen.width),
    tz_name: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    user_is_login: "true",
    webcast_language: "en-US",
  });
  return `https://${host}/webcast/room/chat/?${params.toString()}`;
}

async function sendChat(
  text: string,
  roomId: string,
  webcastHost: string,
): Promise<ChatResult> {
  if (!text || !roomId) {
    return { ok: false, statusCode: -1, detail: "empty text or roomId" };
  }
  const host = webcastHost || getWebcastHost();
  const url = buildChatUrl(host, roomId, text);
  try {
    const r = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json; charset=UTF-8" },
      body: JSON.stringify({
        content: text,
        emotes_with_index: "",
        room_id: roomId,
      }),
    });
    const txt = await r.text();
    let body: { status_code?: number; message?: string; data?: { prompts?: string } } = {};
    try {
      body = JSON.parse(txt);
    } catch {
      return { ok: false, statusCode: r.status, detail: txt.slice(0, 200) };
    }
    if (body.status_code === 0) {
      return { ok: true, statusCode: 0 };
    }
    return {
      ok: false,
      statusCode: body.status_code ?? r.status,
      message: body.message,
      detail: body.data?.prompts || body.message,
    };
  } catch (e) {
    return { ok: false, statusCode: -1, detail: String(e) };
  }
}

async function isLoggedIn(): Promise<boolean> {
  // The cookie sessionid is HttpOnly; document.cookie can't see it.
  // Probe via TikTok's own profile endpoint.
  try {
    const r = await fetch("https://www.tiktok.com/api/user/profile/list/v2/", {
      credentials: "include",
    });
    if (!r.ok) return false;
    const j = await r.json();
    return Boolean(j?.userInfo || j?.data?.userInfo);
  } catch {
    return false;
  }
}

// Expose to the page's main world. `contextIsolation: false` means
// `window` here IS the page's window.
window.__tfBot = {
  resolveRoom,
  sendChat,
  isLoggedIn,
  getWebcastHost,
};

// ─── Sign-broker XHR interceptor ──────────────────────────────────
//
// When the BrowserWindow is loaded with hash fragment "#tfsign=<id>" by
// the sign broker, we monkey-patch XMLHttpRequest to capture the page's
// own /webcast/im/fetch?…&msToken=… response. That response body IS the
// protobuf payload TikTokLive expects from EulerStream — we forward it
// to the main process via IPC, which then returns it as the broker's
// HTTP response body.
//
// The trick is straight from TikFinity's userscript (extension/
// tiktok_live_bridge.user.js): it works because TikTok's loaded webcast
// SDK signs the request itself before XHR fires.

(function installSignCapture() {
  // Parse the capture id from the URL hash. Only activate when this
  // window was opened by the sign broker (not for chat-posting).
  const m = /#tfsign=([A-Za-z0-9-]+)/.exec(window.location.hash || "");
  if (!m) return;
  const captureId = m[1];

  let captured = false;
  const ipc =
    typeof require === "function" ? require("electron").ipcRenderer : null;
  if (!ipc) {
    console.warn("[tf-bridge] ipcRenderer unavailable; sign capture inert");
    return;
  }

  const NativeXhr = window.XMLHttpRequest;
  const NativeOpen = NativeXhr.prototype.open;

  // Promisify a "responseType=arraybuffer + done" capture. We call
  // .open() with the same args as the page does — but flip
  // responseType to arraybuffer so we get raw protobuf bytes.
  NativeXhr.prototype.open = function (
    method: string,
    url: string,
    ...rest: unknown[]
  ) {
    if (
      !captured &&
      typeof url === "string" &&
      url.includes("/webcast/im/fetch") &&
      url.includes("msToken")
    ) {
      this.addEventListener("readystatechange", function () {
        if (this.readyState !== 4 || captured) return;
        captured = true;
        try {
          // `this.response` is whatever responseType yields. Default is
          // text — fall back to that if the page didn't set arraybuffer.
          let body: ArrayBuffer | string = this.response;
          if (
            !(body instanceof ArrayBuffer) &&
            typeof this.responseText === "string"
          ) {
            // Reach into the binary body via Uint8Array on the text.
            body = this.responseText;
          }
          ipc.send("tiktok-bridge:fetch-captured", {
            id: captureId,
            status: this.status,
            body,
          });
        } catch (err) {
          console.error("[tf-bridge] sign capture forward failed:", err);
        }
      });
    }
    // @ts-expect-error rest spread is correct for XHR.open's variadic shape
    return NativeOpen.apply(this, [method, url, ...rest]);
  };
})();

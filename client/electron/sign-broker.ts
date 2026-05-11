/**
 * Local sign broker — replaces EulerStream with TikFinity's trick.
 *
 * Exposes an HTTP endpoint that mimics EulerStream's `/webcast/fetch/`
 * API. For each request:
 *   1. Open / re-use a hidden BrowserWindow on `tiktok.com/@<unique_id>/live`
 *      with the persistent partition (so the user's saved sessionid is in scope).
 *   2. Inject a preload that intercepts `XMLHttpRequest` and `WebSocket`:
 *        - The page's webcast SDK loads, then auto-fires
 *          `XHR /webcast/im/fetch?…&msToken=…`. The XHR response body is
 *          the same protobuf payload EulerStream returns.
 *        - Capture that response body + the partition's TikTok cookies.
 *   3. Return the body as the HTTP response, with `X-Set-TT-Cookie`
 *      mirroring what EulerStream sends so TikTokLive can plug straight
 *      in unchanged.
 *
 * The Python backend's TikTokLive points `WebDefaults.tiktok_sign_url` at
 * this broker (selected via the admin Sign Engine page → Local). Result:
 * zero EulerStream involvement.
 *
 * Health check: `GET /health` returns the partition's login state for the
 * admin GUI's "Test" button.
 */

import { BrowserWindow, ipcMain, session } from "electron";
import { existsSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PARTITION = "persist:tiktok";
const DEFAULT_PORT = 21214;
const NAVIGATE_TIMEOUT_MS = 25_000;
const CAPTURE_TIMEOUT_MS = 25_000;

interface CapturedFetch {
  status: number;
  body: Buffer;
  /** Cookie header in the form Set-Cookie sends (joined with newlines).
   *  Mirrors EulerStream's X-Set-TT-Cookie response header. */
  cookieHeader: string;
}

let server: http.Server | null = null;
let brokerWindow: BrowserWindow | null = null;
const inflight = new Map<
  string,
  { resolve: (c: CapturedFetch) => void; reject: (e: Error) => void; timer: NodeJS.Timeout }
>();

function resolveSignBridgePreload(): string {
  // We share a preload file with the chat-bridge BrowserWindow — same
  // partition, same need to inject into TikTok's page context. The
  // bridge file exposes the XHR/WebSocket capture in addition to the
  // chat-post helper.
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

function ensureBrokerWindow(): BrowserWindow {
  if (brokerWindow && !brokerWindow.isDestroyed()) return brokerWindow;
  brokerWindow = new BrowserWindow({
    show: false,
    width: 1280,
    height: 820,
    webPreferences: {
      preload: resolveSignBridgePreload(),
      partition: PARTITION,
      contextIsolation: false, // bridge runs in page context (TikFinity-style)
      nodeIntegration: false,
      sandbox: false,
    },
  });
  brokerWindow.on("closed", () => {
    brokerWindow = null;
  });
  return brokerWindow;
}

/**
 * Receive a captured XHR response from the page-side bridge.
 * The bridge calls `ipcRenderer.send('tiktok-bridge:fetch-captured', { id, status, body })`.
 */
ipcMain.on(
  "tiktok-bridge:fetch-captured",
  (
    _e,
    payload: { id: string; status: number; body: ArrayBuffer | Uint8Array | number[] | string },
  ) => {
    const pending = inflight.get(payload.id);
    if (!pending) return;
    inflight.delete(payload.id);
    clearTimeout(pending.timer);

    let buf: Buffer;
    if (payload.body instanceof ArrayBuffer) {
      buf = Buffer.from(payload.body);
    } else if (ArrayBuffer.isView(payload.body)) {
      buf = Buffer.from(payload.body.buffer);
    } else if (Array.isArray(payload.body)) {
      buf = Buffer.from(payload.body);
    } else if (typeof payload.body === "string") {
      buf = Buffer.from(payload.body, "binary");
    } else {
      pending.reject(new Error("Unsupported body shape from bridge"));
      return;
    }

    void readPartitionCookies().then((cookieHeader) => {
      pending.resolve({
        status: payload.status || 200,
        body: buf,
        cookieHeader,
      });
    });
  },
);

async function readPartitionCookies(): Promise<string> {
  const ses = session.fromPartition(PARTITION);
  const cookies = await ses.cookies.get({ domain: ".tiktok.com" });
  // EulerStream's X-Set-TT-Cookie uses `name=value; …` separated by `\n`,
  // matching SimpleCookie's load() format on the Python side. Keep it
  // minimal — name=value is enough for the Python http.cookies parser.
  return cookies.map((c) => `${c.name}=${c.value}`).join("\n");
}

async function captureSignedFetch(handle: string): Promise<CapturedFetch> {
  const win = ensureBrokerWindow();
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const url = `https://www.tiktok.com/@${encodeURIComponent(handle)}/live#tfsign=${id}`;

  const captured = new Promise<CapturedFetch>((resolve, reject) => {
    const timer = setTimeout(() => {
      inflight.delete(id);
      reject(new Error(`Timed out waiting for /webcast/im/fetch capture (handle=@${handle})`));
    }, CAPTURE_TIMEOUT_MS);
    inflight.set(id, { resolve, reject, timer });
  });

  try {
    await Promise.race([
      win.loadURL(url),
      new Promise<never>((_resolve, reject) =>
        setTimeout(
          () => reject(new Error(`loadURL timeout (handle=@${handle})`)),
          NAVIGATE_TIMEOUT_MS,
        ),
      ),
    ]);
  } catch (e) {
    inflight.delete(id);
    throw e;
  }

  return captured;
}

function extractHandle(req: http.IncomingMessage): string | null {
  const url = new URL(req.url ?? "/", "http://localhost");
  const fromQuery = url.searchParams.get("unique_id");
  if (fromQuery) return fromQuery.replace(/^@/, "").trim();
  // Fallback: Referer often carries it on EulerStream calls.
  const ref = req.headers["referer"];
  if (typeof ref === "string") {
    const m = /tiktok\.com\/@([A-Za-z0-9._-]+)/.exec(ref);
    if (m) return m[1];
  }
  return null;
}

async function handleFetchRoute(
  req: http.IncomingMessage,
  res: http.ServerResponse,
): Promise<void> {
  const handle = extractHandle(req);
  if (!handle) {
    res.writeHead(400, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "missing unique_id query param" }));
    return;
  }
  try {
    const c = await captureSignedFetch(handle);
    res.writeHead(c.status, {
      "Content-Type": "application/octet-stream",
      "Content-Length": c.body.length.toString(),
      "X-Set-TT-Cookie": c.cookieHeader,
    });
    res.end(c.body);
  } catch (e) {
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        error: (e as Error).message || "broker capture failed",
      }),
    );
  }
}

async function handleHealthRoute(
  _req: http.IncomingMessage,
  res: http.ServerResponse,
): Promise<void> {
  const ses = session.fromPartition(PARTITION);
  const cookies = await ses.cookies.get({ domain: ".tiktok.com" });
  const loggedIn = cookies.some((c) => c.name === "sessionid");
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      status: loggedIn ? "Local broker reachable, signed in" : "Local broker reachable, NOT signed in",
      logged_in: loggedIn,
      partition: PARTITION,
    }),
  );
}

export function startSignBroker(port: number = DEFAULT_PORT): http.Server {
  if (server) return server;

  server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    if (req.method === "GET" && url.pathname === "/health") {
      void handleHealthRoute(req, res);
      return;
    }
    if (req.method === "GET" && url.pathname === "/webcast/fetch/") {
      void handleFetchRoute(req, res);
      return;
    }
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "route not found" }));
  });

  server.listen(port, "127.0.0.1", () => {
    console.log(`[sign-broker] listening on http://127.0.0.1:${port}`);
  });
  server.on("error", (e) => {
    console.error(`[sign-broker] server error: ${e}`);
  });
  return server;
}

export function stopSignBroker(): Promise<void> {
  return new Promise((resolve) => {
    for (const p of inflight.values()) {
      clearTimeout(p.timer);
      p.reject(new Error("broker shutting down"));
    }
    inflight.clear();
    if (!server) return resolve();
    server.close(() => {
      server = null;
      if (brokerWindow && !brokerWindow.isDestroyed()) brokerWindow.destroy();
      brokerWindow = null;
      resolve();
    });
  });
}

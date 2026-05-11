/**
 * Electron client shell for tiktok-bot.
 *
 * This Electron app is a thin wrapper around the framework's web app.
 * It loads the same UI a browser sees (http://localhost:5173 in dev,
 * the deployed URL in prod) and additionally exposes window.api.* via
 * preload — so the React code can detect "I'm running inside Electron"
 * and conditionally enable the chat-posting widgets.
 *
 * The TikTok-side capabilities (login, room posting) live entirely in
 * this client. The framework backend never touches TikTok directly.
 */

import {
  app,
  BrowserWindow,
  ipcMain,
  nativeImage,
  protocol,
  session,
} from "electron";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { TikTokWindow } from "./tiktok-window";
import { installTikTokWebRequestHooks } from "./web-request-hooks";
import { startSignBroker, stopSignBroker } from "./sign-broker";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Where to load the web UI from. In dev the framework's Vite server is
// on :5173. In prod we point at the deployed URL (set via env).
const WEB_URL =
  process.env.PHOVEU_WEB_URL ?? process.env.VITE_DEV_SERVER_URL ?? "http://localhost:5173";

// Backend (FastAPI) URL — passed through to the renderer for direct calls
// when needed (most calls go through Vite's dev proxy in dev).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const BACKEND_TOKEN = process.env.BACKEND_TOKEN ?? "";

const BUILD_DIR = path.join(__dirname, "..", "build");

function resolveAppIcon(): string | undefined {
  for (const name of ["icon.png", "icon.icns"]) {
    const p = path.join(BUILD_DIR, name);
    if (existsSync(p)) return p;
  }
  return undefined;
}
const APP_ICON = resolveAppIcon();

const tiktok = new TikTokWindow();

// Register bytedance:// before app.whenReady — TikTok's anti-fraud SDK
// probes for it; cancelling silently looks like "not installed".
protocol.registerSchemesAsPrivileged([
  { scheme: "bytedance", privileges: { bypassCSP: true, secure: true } },
]);

// ── IPC handlers ────────────────────────────────────────────────────

ipcMain.handle("config:get", () => ({
  backendUrl: BACKEND_URL,
  backendToken: BACKEND_TOKEN,
}));

ipcMain.handle("auth:login", () => tiktok.login());
ipcMain.handle("auth:logout", async () => {
  await tiktok.logout();
  return { logged_in: false };
});
ipcMain.handle("auth:isLoggedIn", () => tiktok.isLoggedIn());
ipcMain.handle("auth:getSessionCookies", () => tiktok.getSessionCookies());

ipcMain.handle("tiktok:navigateToLive", (_e, username: string) =>
  tiktok.navigateToLive(username),
);
ipcMain.handle("tiktok:sendComment", (_e, text: string) =>
  tiktok.sendComment(text),
);

// ── main window (loads the framework's web UI) ─────────────────────

function resolveMainPreload(): string {
  for (const name of ["preload.mjs", "preload.cjs", "preload.js"]) {
    const p = path.join(__dirname, name);
    if (existsSync(p)) return p;
  }
  throw new Error(`preload not found in ${__dirname}`);
}

let mainWindow: BrowserWindow | null = null;
const IS_DEV =
  !!process.env.VITE_DEV_SERVER_URL || process.env.NODE_ENV === "development";

function createMainWindow(): void {
  console.log(`[tiktok-bot] WEB_URL = ${WEB_URL}`);
  console.log(`[tiktok-bot] BACKEND_URL = ${BACKEND_URL}`);

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    title: "tiktok-bot",
    icon: APP_ICON,
    webPreferences: {
      preload: resolveMainPreload(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  // Open DevTools in dev so a blank page shows its error reason.
  if (IS_DEV) {
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }

  // Log every loadURL failure (otherwise blank == silent). Chromium fires
  // `did-fail-load` for sub-resources, in-flight navigations, and its own
  // error page renders — filter to only the actual main-frame failure
  // for our target URL.
  mainWindow.webContents.on(
    "did-fail-load",
    (_e, errorCode, errorDescription, validatedURL, isMainFrame) => {
      if (!isMainFrame) return;
      // Chromium itself navigates to chrome-error://chromewebdata/ as
      // part of rendering an error — skip those secondary events.
      if (validatedURL.startsWith("chrome-error://")) return;
      // -3 / ERR_ABORTED also fires when a navigation is replaced by a
      // newer one (e.g. our fallback loadURL). Ignore that exact case.
      if (errorCode === -3) return;

      console.error(
        `[tiktok-bot] failed to load ${validatedURL}: ${errorCode} ${errorDescription}`,
      );
      // Render a tiny fallback page with the actual URL we tried — not
      // chrome-error://chromewebdata/, which is Chromium's internal
      // error page, not what we asked for.
      const html = `<!doctype html><meta charset="utf-8"><title>tiktok-bot</title>
<body style="font-family:-apple-system,system-ui,sans-serif;padding:24px;background:#0f172a;color:#e2e8f0">
<h2>Couldn't load the web UI</h2>
<p>The Electron client tried to load <code>${WEB_URL}</code> but got:<br>
<b>${errorCode} — ${errorDescription || "(no description)"}</b></p>
<p>Most likely the framework frontend isn't running on that URL.</p>
<ol>
  <li>Make sure <code>./build.sh dev</code> (or your <code>frontend/</code> Vite server) is up.</li>
  <li>If the frontend is on a non-default port, set
    <code>PHOVEU_WEB_URL</code> when launching the client, e.g.<br>
    <code>PHOVEU_WEB_URL=http://localhost:9021 npm run dev</code></li>
  <li>Cmd-R or restart the client to retry.</li>
</ol>
</body>`;
      mainWindow?.loadURL(
        "data:text/html;charset=utf-8," + encodeURIComponent(html),
      );
    },
  );

  void mainWindow.loadURL(WEB_URL).catch((e) => {
    console.error(`[tiktok-bot] loadURL threw: ${e}`);
  });
}

app.whenReady().then(() => {
  if (APP_ICON && app.dock) {
    try {
      app.dock.setIcon(nativeImage.createFromPath(APP_ICON));
    } catch {
      /* fine — Electron uses default */
    }
  }

  // Cancel every bytedance:// request silently.
  protocol.handle("bytedance", () => new Response(null, { status: 204 }));

  // webRequest hooks against the persist:tiktok partition (used by the
  // hidden TikTok BrowserWindow that does the actual posting).
  installTikTokWebRequestHooks(session.fromPartition("persist:tiktok"));

  // Local sign broker — replaces EulerStream when the backend's Sign
  // Engine is set to "local". Listens on 127.0.0.1:21214 by default.
  const brokerPort = Number(process.env.TIKTOK_SIGN_BROKER_PORT || 21214);
  startSignBroker(brokerPort);

  if (APP_ICON) tiktok.setAppIcon(APP_ICON);

  createMainWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
});

app.on("will-quit", async (event) => {
  event.preventDefault();
  try {
    await stopSignBroker();
  } catch {
    /* ignore */
  }
  try {
    await tiktok.close();
  } catch {
    /* ignore */
  }
  app.exit(0);
});

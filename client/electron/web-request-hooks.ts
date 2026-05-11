/**
 * webRequest hooks that make TikTok's webcast chat POST work from a
 * locally-controlled Electron BrowserWindow. Modeled on TikFinity's
 * approach (see docs/tikfinity-analysis.md §4).
 *
 * Three things are necessary:
 *
 *  1. Strip Content-Security-Policy from www.tiktok.com responses, so our
 *     bridge preload script can run inline without violating page CSP.
 *
 *  2. Rewrite Access-Control-Allow-{Origin,Headers,Credentials} for
 *     /webcast/* responses, so the cross-origin POST to webcast.tiktok.com
 *     from a www.tiktok.com page passes Chromium's CORS check.
 *
 *  3. Forge `x-ware-csrf-token` and force `200 OK` on HEAD/OPTIONS
 *     preflight requests to /webcast/room/chat. Without this the actual
 *     POST never ships — Chromium fails the preflight client-side because
 *     TikTok's CDN doesn't return the expected CSRF header on preflight.
 *
 * The fake CSRF token only needs to satisfy the preflight; the actual
 * POST round-trips with whatever token TikTok's own webcast SDK adds.
 */

import { type Session } from "electron";

// One opaque hardcoded value — TikFinity uses the same approach. The token
// just needs to be present and well-formed; TikTok validates the real CSRF
// on the actual POST, where the page's own cookies provide it.
const FAKE_CSRF_TOKEN =
  "0,0001000000012db621dc1c8a3d754421950a085bb964d1c3fbe73ca0d82b62ae44dabe2937cf183971c03b415a31,86370200,success,3cd8260afaef2dfe8830cc1c7dd9d8ff";

const TT_FILTER = {
  urls: [
    "https://*.tiktok.com/*",
    "https://*.tiktokv.com/*",
    "https://*.tiktokcdn.com/*",
  ],
};

const ALLOW_HEADERS = [
  "content-type",
  "x-tt-env",
  "x-use-boe",
  "x-tt-logid",
  "x-secsdk-csrf-token",
  "x-secsdk-csrf-version",
  "x-secsdk-csrf-request",
  "x-secsdk-csrf-session-id",
  "tt-ticket-guard-version",
  "tt-ticket-guard-iteration-version",
  "tt-ticket-guard-public-key",
  "tt-ticket-guard-client-data",
  "tt-ticket-guard-web-version",
  "x-cthulhu-csrf",
  "x-mssdk-info",
  "x-bogus",
  "x-gnarly",
].join(", ");

export function installTikTokWebRequestHooks(session: Session): void {
  session.webRequest.onHeadersReceived(TT_FILTER, (details, callback) => {
    const url = details.url;
    const responseHeaders: Record<string, string[]> = { ...details.responseHeaders };

    // 1. Strip CSP so our preload can inject without complaints.
    if (url.startsWith("https://www.tiktok.com/")) {
      for (const k of Object.keys(responseHeaders)) {
        if (k.toLowerCase().startsWith("content-security-policy")) {
          delete responseHeaders[k];
        }
      }
    }

    // 2 + 3. CORS rewrite for any webcast URL.
    if (url.includes("/webcast/")) {
      responseHeaders["access-control-allow-origin"] = ["https://www.tiktok.com"];
      responseHeaders["access-control-allow-credentials"] = ["true"];
      responseHeaders["access-control-allow-headers"] = [ALLOW_HEADERS];
      responseHeaders["access-control-allow-methods"] = [
        "GET, POST, OPTIONS, HEAD, PUT, DELETE",
      ];

      const isPreflight =
        details.method === "OPTIONS" || details.method === "HEAD";
      if (isPreflight && url.includes("/webcast/room/chat")) {
        // Force a 200 with our fake CSRF token so Chromium accepts the
        // preflight and lets the actual POST go through.
        responseHeaders["x-ware-csrf-token"] = [FAKE_CSRF_TOKEN];
        callback({
          cancel: false,
          responseHeaders,
          statusLine: "HTTP/1.1 200 OK",
        });
        return;
      }
    }

    callback({ cancel: false, responseHeaders });
  });
}

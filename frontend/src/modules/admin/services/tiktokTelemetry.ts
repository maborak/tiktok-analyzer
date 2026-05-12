/**
 * Module-level telemetry singleton for the TikTok WS + poll surface.
 *
 * Why this exists: the user can't tell at a glance whether the page
 * is actually receiving real-time events vs. silently polling. This
 * tracks the live WS state + a rolling event count so a status pill
 * can render "WS · 12 events · 2s ago" or "WS dropped · falling back
 * to poll" without each page wiring its own listeners.
 *
 * Why a module singleton: every `openTikTokWebSocket` call routes
 * through the same helper, so we can hook lifecycle events ONCE
 * inside that helper and broadcast updates to N React subscribers
 * via a tiny pub/sub. No prop drilling, no global Context, no
 * per-page wiring.
 *
 * State is per-process (per browser tab) — multiple admin tabs each
 * see their own telemetry. That matches user expectation: "what's
 * happening on THIS tab right now."
 */

export type TikTokWsState = 'off' | 'connecting' | 'open' | 'closed';

export interface TikTokTelemetrySnapshot {
  wsState: TikTokWsState;
  /** Performance.now() of the last received WS event, null if none. */
  lastEventAt: number | null;
  /** Rolling count of received events. Resets only on full page reload. */
  eventCount: number;
  /** True once at least one WS has been opened — distinguishes "WS
   *  not opened yet (still in mount cycle)" from "WS off by config". */
  wsAttempted: boolean;
}

const initial: TikTokTelemetrySnapshot = {
  wsState: 'off',
  lastEventAt: null,
  eventCount: 0,
  wsAttempted: false,
};

let state: TikTokTelemetrySnapshot = initial;
const listeners = new Set<(s: TikTokTelemetrySnapshot) => void>();

// When a WS closes, we keep the `closed` state visible for a few
// seconds so the operator notices a real drop. After that grace
// period, if no replacement WS has opened, we settle to `off` so
// pages that simply don't open a WS (e.g. the Lives index, when
// reached by navigating from a page that did) don't show a
// permanent "WS dropped" label.
const CLOSED_GRACE_MS = 4000;
let closedResetTimer: ReturnType<typeof setTimeout> | null = null;

function clearClosedReset(): void {
  if (closedResetTimer !== null) {
    clearTimeout(closedResetTimer);
    closedResetTimer = null;
  }
}

function notify() {
  // Snapshot the value once so each subscriber sees the same object.
  const snap = state;
  listeners.forEach((fn) => {
    try { fn(snap); } catch { /* swallow — bad subscriber shouldn't break others */ }
  });
}

export const tiktokTelemetry = {
  /** Read the current snapshot (sync). */
  get(): TikTokTelemetrySnapshot {
    return state;
  },
  /** Subscribe to changes. Returns an unsubscribe function. */
  subscribe(fn: (s: TikTokTelemetrySnapshot) => void): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  /** Called by `openTikTokWebSocket` when a connection is initiated. */
  noteWsAttempt(): void {
    // Cancel any pending grace-period reset — a new attempt
    // supersedes the previous close.
    clearClosedReset();
    state = { ...state, wsAttempted: true, wsState: 'connecting' };
    notify();
  },
  /** Called when the WS `open` event fires. */
  noteWsOpen(): void {
    clearClosedReset();
    state = { ...state, wsState: 'open' };
    notify();
  },
  /** Called when the WS closes or errors. */
  noteWsClosed(): void {
    clearClosedReset();
    state = { ...state, wsState: 'closed' };
    notify();
    // Schedule a grace-period reset: if no replacement WS opens
    // within CLOSED_GRACE_MS, fade to `off`. This is the path that
    // saves the Lives page (no WS opener of its own) from inheriting
    // a "WS dropped" label from a previous page's WS lifecycle.
    closedResetTimer = setTimeout(() => {
      closedResetTimer = null;
      if (state.wsState === 'closed') {
        state = { ...state, wsState: 'off', wsAttempted: false };
        notify();
      }
    }, CLOSED_GRACE_MS);
  },
  /** Called on every WS message — drives "last event Xs ago". */
  noteEvent(): void {
    state = {
      ...state,
      lastEventAt: performance.now(),
      eventCount: state.eventCount + 1,
    };
    notify();
  },
  /** Reset (useful in tests; not called in normal runtime). */
  reset(): void {
    state = initial;
    notify();
  },
};

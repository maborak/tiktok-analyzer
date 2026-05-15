/**
 * Phase 9D — WS-pushed per-host summary state with gap-detect resync.
 *
 * Wraps `openTikTokWebSocket` with the four protocol pieces from the
 * Phase 9 plan:
 *
 * 1. **Initial state via snapshot**: on connect (and on reconnect),
 *    the hook sends `{type:"request-snapshot", handles:[...]}` for
 *    every known host so the local state mirrors the cache before any
 *    deltas land. Without this, a client that connects between two
 *    events would miss the seed value and only ever see partial
 *    deltas. The bundle endpoint primes `versionByHost` so reconnect
 *    is bounded to the per-host gap rather than a wholesale reset.
 *
 * 2. **Streaming deltas via summary-delta**: every state mutation on
 *    the server publishes a `{type:"summary-delta", host, version,
 *    patch}` frame. The hook deep-merges `patch` into the host's
 *    local summary, advancing `versionByHost[host]` by 1 (the server
 *    guarantees monotonic per-host versions).
 *
 * 3. **Gap detection**: when an incoming delta's version is not
 *    `lastSeen + 1`, the hook silently requests a fresh snapshot for
 *    that host. Future deltas are paused until the snapshot replies
 *    (queued via a per-host pending set); after the snapshot lands,
 *    queued deltas are replayed in version order.
 *
 * 4. **Polling fallback on disconnect**: when the WS errors / closes,
 *    `status` flips to `'reconnecting'`. After `maxReconnectAttempts`,
 *    falls through to `'polling-fallback'` so the lives page knows to
 *    revert to the 30 s bundle poll until WS recovers.
 *
 * This hook does NOT touch the `summary` state on the page itself —
 * it surfaces the per-host updates via `onUpdate`. The page owner
 * decides how to merge them into the React state (e.g. preserving
 * the per-host object identity for `React.memo` short-circuit, the
 * Phase 9A pattern).
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  openTikTokWebSocket,
  type TikTokLiveSummary,
} from '@admin/services/tiktok';


/** Frame shapes the server sends. */
type SummaryDeltaFrame = {
  type: 'summary-delta';
  host: string;
  version: number;
  patch: Partial<TikTokLiveSummary>;
};
type SnapshotFrame = {
  type: 'snapshot';
  host: string;
  version: number;
  data: TikTokLiveSummary;
};
type ServerFrame = SummaryDeltaFrame | SnapshotFrame | { type: string };


export interface UseTikTokLivesSocketOptions {
  /** Which surface the client lives on. */
  audience?: 'admin' | 'public';
  /**
   * Map of host → seed version, primed from the bundle endpoint. The
   * hook uses this to detect gaps from the very first delta — if the
   * server jumps from version N to N+M, the hook requests a snapshot.
   *
   * Passing an empty map disables seeding; the first delta on each
   * host establishes the version unconditionally (acceptable for a
   * brand-new tab, lossy for a re-mount after a long idle).
   */
  initialVersions?: Record<string, number>;
  /** Handles to subscribe to. `'*'` / omitted = all. */
  handles?: string[] | '*';
  /**
   * Called whenever a host's summary changes — either a delta merged
   * into the current view or a snapshot wholesale-replaced. The hook
   * doesn't own the page's React state; the caller decides how to
   * merge.
   */
  onUpdate?: (host: string, summary: TikTokLiveSummary, version: number) => void;
  /** Max consecutive reconnect attempts before falling back to polling. */
  maxReconnectAttempts?: number;
}


export interface UseTikTokLivesSocketResult {
  /** Lifecycle state — drives the page's "WS armed / polling" pill. */
  status: 'connecting' | 'live' | 'reconnecting' | 'polling-fallback';
  /** Latest version observed for each host. Stays stable across
   *  reconnects when no events fire — the version only advances. */
  versionByHost: Record<string, number>;
  /**
   * Imperative snapshot request — call when the page becomes visible
   * after a long hidden period, or after a manual refresh. The server
   * replies with one snapshot frame per handle.
   */
  requestSnapshot: (handles: string[]) => void;
  /**
   * Seed the internal per-host version map from a bundle response so
   * an on-reconnect snapshot request covers every host the page already
   * knows about. Without this, the hook starts with an empty version
   * map; if the WS drops before the first delta arrives, the reconnect
   * skips the snapshot step and per-host cards stay stale until the
   * next 5-minute reconcile poll.
   *
   * Idempotent — only writes versions that are >= the currently-tracked
   * value, so a stale call doesn't roll the cursor backwards.
   */
  seedVersions: (versions: Record<string, number>) => void;
}


const DEFAULT_MAX_RECONNECT = 5;


export function useTikTokLivesSocket(
  opts: UseTikTokLivesSocketOptions,
): UseTikTokLivesSocketResult {
  const {
    audience = 'admin',
    initialVersions = {},
    handles = '*',
    onUpdate,
    maxReconnectAttempts = DEFAULT_MAX_RECONNECT,
  } = opts;

  const [status, setStatus] = useState<UseTikTokLivesSocketResult['status']>('connecting');
  const [versionByHost, setVersionByHost] = useState<Record<string, number>>(
    initialVersions,
  );

  // Per-host LIVE state mirror. We keep this in a ref rather than React
  // state because deltas can land 10s/s during a hot live — re-rendering
  // on every one would flood. The page mirrors via `onUpdate` and
  // decides its own batching cadence.
  const summaryByHostRef = useRef<Record<string, TikTokLiveSummary>>({});
  const versionByHostRef = useRef<Record<string, number>>(initialVersions);
  // Set of hosts with a snapshot request in flight — incoming deltas
  // for these are queued instead of applied, so we don't double-apply
  // when the snapshot lands.
  const pendingSnapshotRef = useRef<Set<string>>(new Set());
  // Per-host queued deltas during a snapshot wait.
  const pendingDeltasRef = useRef<Map<string, SummaryDeltaFrame[]>>(new Map());
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  // Stable refs for option callbacks so we don't reset the WS on every
  // render. Callers passing a new `onUpdate` lambda each render would
  // otherwise force a reconnect each time.
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  // Send a request-snapshot frame. Used for the on-connect seed AND
  // the on-gap recovery path.
  const requestSnapshot = useCallback((handlesToFetch: string[]) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const cleaned = handlesToFetch
      .map((h) => h.replace(/^@/, '').trim().toLowerCase())
      .filter(Boolean);
    if (cleaned.length === 0) return;
    for (const h of cleaned) {
      pendingSnapshotRef.current.add(h);
    }
    try {
      ws.send(JSON.stringify({ type: 'request-snapshot', handles: cleaned }));
    } catch {
      // Send failed → ws is closing. Reconnect will request snapshots again.
    }
  }, []);

  const applyDeltaToState = useCallback((host: string, frame: SummaryDeltaFrame) => {
    const prevSummary = summaryByHostRef.current[host] ?? {};
    // Deep-merge: dict values recurse, everything else (arrays,
    // scalars, nulls) replaces. Mirrors the backend's deep-merge so
    // the client view stays byte-equivalent to the server's cache.
    const merged = deepMerge(prevSummary, frame.patch) as TikTokLiveSummary;
    summaryByHostRef.current[host] = merged;
    versionByHostRef.current = {
      ...versionByHostRef.current,
      [host]: frame.version,
    };
    setVersionByHost(versionByHostRef.current);
    onUpdateRef.current?.(host, merged, frame.version);
  }, []);

  const applySnapshot = useCallback((frame: SnapshotFrame) => {
    const host = frame.host;
    summaryByHostRef.current[host] = frame.data;
    versionByHostRef.current = {
      ...versionByHostRef.current,
      [host]: frame.version,
    };
    setVersionByHost(versionByHostRef.current);
    // Drain queued deltas in version order. Discard any whose version
    // is <= the snapshot's version (those were applied at or before
    // the snapshot point already). Apply any with version > snapshot.
    const queue = pendingDeltasRef.current.get(host) ?? [];
    pendingDeltasRef.current.delete(host);
    pendingSnapshotRef.current.delete(host);
    queue
      .sort((a, b) => a.version - b.version)
      .filter((d) => d.version > frame.version)
      .forEach((d) => applyDeltaToState(host, d));
    onUpdateRef.current?.(host, frame.data, frame.version);
  }, [applyDeltaToState]);

  const handleFrame = useCallback((frame: ServerFrame) => {
    if (frame.type === 'snapshot') {
      applySnapshot(frame as SnapshotFrame);
      return;
    }
    if (frame.type === 'summary-delta') {
      const delta = frame as SummaryDeltaFrame;
      const host = delta.host;
      // Snapshot in flight → queue and wait.
      if (pendingSnapshotRef.current.has(host)) {
        const q = pendingDeltasRef.current.get(host) ?? [];
        q.push(delta);
        pendingDeltasRef.current.set(host, q);
        return;
      }
      const lastSeen = versionByHostRef.current[host];
      if (lastSeen != null && delta.version !== lastSeen + 1) {
        // Gap detected. Request a snapshot; queue this delta to
        // replay after the snapshot.
        const q = pendingDeltasRef.current.get(host) ?? [];
        q.push(delta);
        pendingDeltasRef.current.set(host, q);
        requestSnapshot([host]);
        return;
      }
      applyDeltaToState(host, delta);
    }
    // Other frame types (raw event envelopes from the legacy listener
    // stream, control acks) are ignored here — they're consumed by
    // other hooks if needed.
  }, [applyDeltaToState, applySnapshot, requestSnapshot]);

  // Connect / reconnect. The dependency list intentionally excludes
  // `handles` shape — we want one WS for the page lifetime, not a
  // reconnect when the user toggles a filter. If we ever need
  // per-filter reconnects we'd add it explicitly.
  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (cancelled) return;
      setStatus(
        reconnectAttemptsRef.current === 0 ? 'connecting' : 'reconnecting',
      );
      const ws = openTikTokWebSocket(
        // The raw onMessage callback receives every frame the server
        // sends — both the legacy event envelopes AND the new
        // summary-delta / snapshot frames. We route here by `type`.
        (msg) => {
          handleFrame(msg as unknown as ServerFrame);
        },
        () => {
          // onError → the `onclose` handler below kicks in; nothing
          // to do here beyond logging via the helper itself.
        },
        { audience, handles },
      );
      wsRef.current = ws;
      ws.addEventListener('open', () => {
        if (cancelled) return;
        reconnectAttemptsRef.current = 0;
        setStatus('live');
        // On (re)connect, request snapshots for every host we
        // already had a version for. This refills any state that
        // diverged during the disconnect window.
        const knownHosts = Object.keys(versionByHostRef.current);
        if (knownHosts.length > 0) {
          // Slight delay so the server-side subscriber registration
          // has time to settle before we ask for snapshots.
          setTimeout(() => {
            if (!cancelled) requestSnapshot(knownHosts);
          }, 50);
        }
      });
      ws.addEventListener('close', () => {
        wsRef.current = null;
        if (cancelled) return;
        reconnectAttemptsRef.current += 1;
        if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          setStatus('polling-fallback');
          return;
        }
        const backoff = Math.min(
          15_000,
          500 * 2 ** Math.min(reconnectAttemptsRef.current, 5),
        );
        setStatus('reconnecting');
        reconnectTimer = setTimeout(connect, backoff);
      });
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer != null) clearTimeout(reconnectTimer);
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* ignore */
        }
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audience, maxReconnectAttempts]);

  const seedVersions = useCallback((versions: Record<string, number>) => {
    let mutated = false;
    const next = { ...versionByHostRef.current };
    for (const [host, v] of Object.entries(versions)) {
      if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) continue;
      const cur = next[host];
      if (cur == null || v > cur) {
        next[host] = v;
        mutated = true;
      }
    }
    if (mutated) {
      versionByHostRef.current = next;
      setVersionByHost(next);
    }
  }, []);

  return { status, versionByHost, requestSnapshot, seedVersions };
}


// ── deep merge ─────────────────────────────────────────────────────


/** Same shape as the backend's `_deep_merge`: dict-into-dict recurses,
 *  everything else (lists, scalars, nulls) replaces. Returns a fresh
 *  object so React's referential equality checks fire correctly
 *  downstream. */
function deepMerge(target: Record<string, unknown>, source: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...target };
  for (const [k, v] of Object.entries(source)) {
    if (
      v != null
      && typeof v === 'object'
      && !Array.isArray(v)
      && out[k] != null
      && typeof out[k] === 'object'
      && !Array.isArray(out[k])
    ) {
      out[k] = deepMerge(out[k] as Record<string, unknown>, v as Record<string, unknown>);
    } else {
      out[k] = v;
    }
  }
  return out;
}

/**
 * Realtime / Poll indicator pill.
 *
 * Tells the operator at a glance whether THIS page is currently
 * receiving real-time events vs falling back to REST polling. Powered
 * by:
 *   - `useTikTokRuntimeConfig()` for the operator-configured mode
 *     (poll / ws / both) and the poll cadence (ms).
 *   - `useTikTokTelemetry()` for the live WS connection state +
 *     rolling event count (updated automatically inside
 *     `openTikTokWebSocket` — no per-page wiring).
 *
 * Renders different shapes:
 *   - WS green + N events + "1.2s ago"  → real-time stream is live.
 *   - WS amber "connecting…"            → handshake in flight.
 *   - WS red   "dropped"                → was open, now closed; the
 *                                          page is silently polling.
 *   - WS gray  "off — polling 30s"      → operator chose `poll` mode.
 *
 * Click the pill (or hover) to see the verbose tooltip with mode,
 * audience, configured interval, last event timestamp.
 */

import { useEffect, useState } from 'react';
import { Activity, Pause, Radio, Wifi, WifiOff } from 'lucide-react';

import { useTikTokRuntimeConfig } from '@admin/contexts/TikTokRuntimeConfigContext';
import {
  tiktokTelemetry,
  type TikTokTelemetrySnapshot,
} from '@admin/services/tiktokTelemetry';

interface Props {
  /** Which audience the page is in: `admin` (default) or `public`.
   *  Decides which configured mode (`adminRealtime` / `publicRealtime`)
   *  the indicator describes. */
  audience?: 'admin' | 'public';
}

export function TikTokRealtimeIndicator({ audience = 'admin' }: Props) {
  const cfg = useTikTokRuntimeConfig();
  const telemetry = useTikTokTelemetry();
  // Re-render once a second so the "Xs ago" relative time keeps
  // ticking even without new events. Cheap: just a single setState.
  const [, forceTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const mode = audience === 'admin'
    ? (cfg.adminRealtime ?? 'both')
    : cfg.publicRealtime;

  // Decide the visual shape from (configured mode) × (live WS state).
  // The order of checks matters — `mode=poll` should always show the
  // poll pill even if a leftover WS connection is somehow open.
  const wantsWs = mode === 'ws' || mode === 'both';
  const wsState = telemetry.wsState;
  const lastEventAt = telemetry.lastEventAt;
  const eventCount = telemetry.eventCount;

  let dotCls: string;
  let icon: React.ReactNode;
  let label: string;
  let detail: string;

  if (!wantsWs) {
    dotCls = 'bg-gray-400';
    icon = <Pause className="w-3 h-3" />;
    label = 'Poll only';
    detail = `every ${fmtMs(cfg.pollIntervalMs)}`;
  } else if (wsState === 'open') {
    dotCls = 'bg-emerald-500 animate-pulse';
    icon = <Wifi className="w-3 h-3" />;
    label = 'WS live';
    detail = lastEventAt != null
      ? `${eventCount.toLocaleString()} events · ${fmtAgo(lastEventAt)}`
      : `0 events yet`;
  } else if (wsState === 'connecting') {
    dotCls = 'bg-amber-400 animate-pulse';
    icon = <Radio className="w-3 h-3" />;
    label = 'WS connecting';
    detail = '…';
  } else if (wsState === 'closed') {
    dotCls = 'bg-rose-500';
    icon = <WifiOff className="w-3 h-3" />;
    label = 'WS dropped';
    detail = `polling ${fmtMs(cfg.pollIntervalMs)}`;
  } else {
    // wsState === 'off' but config says we want WS — page hasn't
    // opened one yet (cold mount), or the consumer page doesn't
    // open a WS at all (e.g. the Lives index — its detail children
    // are the WS openers, not the index itself). Show a neutral
    // "armed" pill that reflects the configured mode rather than
    // claiming the page is broken.
    dotCls = 'bg-sky-400';
    icon = <Activity className="w-3 h-3" />;
    label = `WS armed (${mode})`;
    detail = `polling every ${fmtMs(cfg.pollIntervalMs)}`;
  }

  const tooltip =
    `Mode: ${mode}\n` +
    `Audience: ${audience}\n` +
    `Poll interval: ${cfg.pollIntervalMs} ms\n` +
    `WS state: ${wsState}\n` +
    `Event count: ${eventCount}\n` +
    (lastEventAt != null ? `Last event: ${fmtAgo(lastEventAt)}` : 'Last event: —');

  return (
    <span
      title={tooltip}
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full border border-gray-200 dark:border-white/10 bg-white dark:bg-white/[0.03] text-[11px] font-mono"
    >
      <span className={`w-2 h-2 rounded-full ${dotCls}`} aria-hidden />
      {icon}
      <span className="font-semibold">{label}</span>
      <span className="text-gray-500">·</span>
      <span className="text-gray-600">{detail}</span>
    </span>
  );
}

/** Subscribe to telemetry updates. Returns the latest snapshot. */
function useTikTokTelemetry(): TikTokTelemetrySnapshot {
  const [snap, setSnap] = useState<TikTokTelemetrySnapshot>(() => tiktokTelemetry.get());
  useEffect(() => tiktokTelemetry.subscribe(setSnap), []);
  return snap;
}

// ── helpers ─────────────────────────────────────────────────────────

function fmtMs(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '?';
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s}s`;
  return `${(s / 60).toFixed(1)}m`;
}

function fmtAgo(perfTs: number): string {
  const ms = performance.now() - perfTs;
  if (ms < 1000) return 'just now';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

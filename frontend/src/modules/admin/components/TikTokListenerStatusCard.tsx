/**
 * Listener-pool health + control panel.
 *
 * Polls /admin/tiktok/listener/status every 5s and renders:
 *   - Mode (in_process / worker)
 *   - Process state (alive / dead, pid, uptime, paused, heartbeat age)
 *   - Per-handle session list (state, events_total, last event age)
 *   - Pause / Resume / Kill buttons (kill is gated to worker mode +
 *     requires a confirm).
 */

import { useCallback, useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { Activity, Database, Pause, Play, Power, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import {
  tiktokApi,
  type TikTokListenerStatus,
} from '@admin/services/tiktok';

const POLL_INTERVAL_MS = 5_000;

interface Props {
  /** Bumping this from the parent triggers an out-of-band refresh
   *  (used by the page-header refresh button). */
  refreshKey?: number;
}

export function TikTokListenerStatusCard({ refreshKey = 0 }: Props) {
  const [status, setStatus] = useState<TikTokListenerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<null | 'pause' | 'resume' | 'kill'>(null);

  const refresh = useCallback(async (showSpinner = true) => {
    if (showSpinner) setLoading(true);
    try {
      const s = await tiktokApi.listenerStatus();
      setStatus(s);
    } catch {
      // Don't toast on every poll — only on initial load failure.
      if (showSpinner) toast.error('Listener status unavailable');
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh(true);
    const t = setInterval(() => refresh(false), POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  // Parent-triggered refresh (header button on Worker tab).
  useEffect(() => {
    if (refreshKey > 0) refresh(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  const onPause = useCallback(async () => {
    setBusy('pause');
    try {
      await tiktokApi.listenerPause();
      toast.success('Listener paused');
      await refresh(false);
    } catch (e) {
      toast.error(`Pause failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  const onResume = useCallback(async () => {
    setBusy('resume');
    try {
      await tiktokApi.listenerResume();
      toast.success('Listener resumed');
      await refresh(false);
    } catch (e) {
      toast.error(`Resume failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  const onKill = useCallback(async () => {
    if (
      !confirm(
        'Kill the listener worker?\n\nIt will exit cleanly. To bring it back, ' +
          "run `python cli.py system tiktok run-listener` (or rely on whatever " +
          'supervisor manages it).',
      )
    )
      return;
    setBusy('kill');
    try {
      await tiktokApi.listenerKill();
      toast.success('SIGTERM sent — worker shutting down');
      // Pause-and-refresh so the UI shows "dead" once the heartbeat goes stale.
      setTimeout(() => refresh(false), 1000);
    } catch (e) {
      toast.error(`Kill failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  if (loading && !status) {
    return (
      <section className="card">
        <div className="flex items-center text-sm text-gray-500">
          <RefreshCw className="w-3.5 h-3.5 mr-2 animate-spin" />
          Loading listener status…
        </div>
      </section>
    );
  }
  if (!status) return null;

  const isWorker = status.mode === 'worker';
  const workers = status.workers ?? [];
  const aliveWorkers = workers.filter((w) => w.alive);
  const alive = isWorker ? aliveWorkers.length > 0 : true;
  const paused = status.worker_paused === true;

  let dotColor = 'bg-gray-400';
  let dotLabel: string;
  if (!alive) {
    dotColor = 'bg-rose-500';
    dotLabel = isWorker ? 'No workers alive' : 'Listener offline';
  } else if (paused) {
    dotColor = 'bg-amber-500';
    dotLabel = 'Paused';
  } else if (isWorker) {
    dotColor = 'bg-emerald-500';
    dotLabel =
      aliveWorkers.length === 1
        ? '1 worker running'
        : `${aliveWorkers.length} workers running`;
  } else {
    dotColor = 'bg-emerald-500';
    dotLabel = 'In-process listener running';
  }

  return (
    <section className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-gray-500" />
          <h2 className="auth-mono-label !mb-0">Listener pool</h2>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refresh(true)}
          disabled={loading}
          aria-label="Refresh"
        >
          <RefreshCw className={loading ? 'w-3.5 h-3.5 animate-spin' : 'w-3.5 h-3.5'} />
        </Button>
      </div>

      <div className="flex items-center flex-wrap gap-x-4 gap-y-2 text-sm mb-3">
        <span className="flex items-center gap-1.5">
          <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />
          <span className="font-medium">{dotLabel}</span>
        </span>
        <span className="font-mono text-[11px] text-gray-500">
          mode: {status.mode}
        </span>
        {status.worker_pid != null && (
          <span className="font-mono text-[11px] text-gray-500">
            pid: {status.worker_pid}
          </span>
        )}
        {status.worker_uptime_s != null && (
          <span className="font-mono text-[11px] text-gray-500">
            up: {formatDuration(status.worker_uptime_s)}
          </span>
        )}
        {status.worker_heartbeat_age_s != null && (
          <span className="font-mono text-[11px] text-gray-500">
            heartbeat: {status.worker_heartbeat_age_s.toFixed(1)}s ago
            {status.worker_heartbeat_source ? ` (${status.worker_heartbeat_source})` : ''}
          </span>
        )}
        <span className="font-mono text-[11px] text-gray-500">
          sessions: {status.sessions.length}
        </span>
        <RedisPill status={status.redis} />
      </div>

      <div className="flex items-center gap-2 mb-3">
        {paused ? (
          <Button
            size="sm"
            variant="primary"
            onClick={onResume}
            disabled={!alive || busy != null}
          >
            <Play className="w-3.5 h-3.5 mr-1" />
            Resume
          </Button>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            onClick={onPause}
            disabled={!alive || busy != null}
          >
            <Pause className="w-3.5 h-3.5 mr-1" />
            Pause
          </Button>
        )}
        <Button
          size="sm"
          variant="danger"
          onClick={onKill}
          disabled={!alive || busy != null || !isWorker}
          title={!isWorker ? 'Kill is disabled in in_process mode (would kill the API)' : undefined}
        >
          <Power className="w-3.5 h-3.5 mr-1" />
          Kill
        </Button>
      </div>

      {isWorker && workers.length > 0 && (
        <div className="mb-3 rounded border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-1.5 text-left auth-mono-label">Worker</th>
                <th className="px-3 py-1.5 text-left auth-mono-label">Status</th>
                <th className="px-3 py-1.5 text-right auth-mono-label">Sessions</th>
                <th className="px-3 py-1.5 text-right auth-mono-label">Heartbeat</th>
                <th className="px-3 py-1.5 text-right auth-mono-label">Started</th>
              </tr>
            </thead>
            <tbody>
              {workers.map((w) => (
                <tr key={w.id} className="border-t border-gray-100">
                  <td className="px-3 py-1.5">
                    <div className="font-medium text-gray-900">{w.worker_key}</div>
                    <div className="text-[10px] font-mono text-gray-500">
                      {w.host} · pid {w.pid}
                    </div>
                  </td>
                  <td className="px-3 py-1.5">
                    <WorkerStatusPill status={w.status} alive={w.alive} />
                  </td>
                  <td
                    className="px-3 py-1.5 text-right font-mono tabular-nums"
                    title={
                      w.connected_session_count != null
                        ? `${w.connected_session_count} actively connected (receiving events) of ${w.sessions_count} total claimed slots — capacity ${w.capacity}.`
                        : `${w.sessions_count} of ${w.capacity} slots claimed.`
                    }
                  >
                    {w.connected_session_count != null && (
                      <span className="text-emerald-600 dark:text-emerald-300 mr-1">
                        {w.connected_session_count} live
                      </span>
                    )}
                    <span className={w.connected_session_count != null ? 'text-gray-500' : ''}>
                      {w.sessions_count}
                    </span>
                    <span className="text-gray-400"> / {w.capacity}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-[11px] text-gray-500 tabular-nums">
                    {w.heartbeat_age_s == null
                      ? '—'
                      : `${formatAge(w.heartbeat_age_s)} ago`}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-[11px] text-gray-500">
                    {w.started_at ? formatStartedShort(w.started_at) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {status.sessions.length > 0 && (
        <div className="rounded border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-1.5 text-left auth-mono-label">Handle</th>
                <th className="px-3 py-1.5 text-left auth-mono-label">State</th>
                <th className="px-3 py-1.5 text-right auth-mono-label">Events</th>
                <th className="px-3 py-1.5 text-right auth-mono-label" title="Reconnects observed for this handle since worker started. Each disconnect → reconnect window represents events that were silently lost on TikTok's side.">
                  Reconnects
                </th>
                <th className="px-3 py-1.5 text-right auth-mono-label" title="Times we saw a non-contiguous offset jump within a single connection. Each gap indicates we missed N events between two received messages.">
                  Gaps
                </th>
                <th className="px-3 py-1.5 text-right auth-mono-label">Last event</th>
              </tr>
            </thead>
            <tbody>
              {status.sessions.map((s) => {
                const gaps = s.gaps_count ?? 0;
                const missed = s.gaps_total_missed ?? 0;
                const reconns = Math.max(0, (s.connect_count ?? 0) - 1);
                const hasGap = gaps > 0;
                const hasReconn = reconns > 0;
                return (
                  <tr key={s.handle} className="border-t border-gray-100">
                    <td className="px-3 py-1.5 font-mono text-[11px]">@{s.handle}</td>
                    <td className="px-3 py-1.5">
                      <StatePill state={s.state} />
                      {s.recycle_release_in_s != null && (
                        <span
                          className="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded font-mono text-[10px] bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                          title={
                            s.recycle_release_in_s <= 0
                              ? 'About to release this slot in the next reconcile tick.'
                              : 'This session has been confirmed offline. The worker will release its slot once the hysteresis window elapses.'
                          }
                        >
                          {s.recycle_release_in_s <= 0
                            ? 'releasing…'
                            : `release in ${formatCountdown(s.recycle_release_in_s)}`}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                      {s.events_total.toLocaleString()}
                    </td>
                    <td
                      className={
                        'px-3 py-1.5 text-right font-mono text-[11px] tabular-nums ' +
                        (hasReconn ? 'text-amber-700 dark:text-amber-300 font-semibold' : 'text-gray-500')
                      }
                      title={
                        hasReconn
                          ? `${reconns} reconnect(s) since worker start. Events between disconnect and reconnect were lost.`
                          : 'No reconnects since worker start.'
                      }
                    >
                      {hasReconn ? reconns : '—'}
                    </td>
                    <td
                      className={
                        'px-3 py-1.5 text-right font-mono text-[11px] tabular-nums ' +
                        (hasGap ? 'text-rose-700 dark:text-rose-300 font-semibold' : 'text-gray-500')
                      }
                      title={
                        hasGap
                          ? `${gaps} offset gap(s), ~${missed} missed message(s)` +
                            (s.last_gap_size != null
                              ? `. Last gap: ${s.last_gap_size} msg`
                              : '') +
                            (s.last_gap_age_s != null
                              ? ` (${formatAge(s.last_gap_age_s)} ago)`
                              : '')
                          : 'No gaps detected on this connection.'
                      }
                    >
                      {hasGap ? `${gaps} (~${missed})` : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-[11px] text-gray-500 tabular-nums">
                      {s.last_event_age_s == null ? '—' : `${formatAge(s.last_event_age_s)} ago`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RedisPill({ status }: { status: TikTokListenerStatus['redis'] }) {
  const { available, url, error, required_for_live_updates } = status;

  // Tone:
  //   ok     — green
  //   warn   — amber  (Redis down + we need it: real-time UI degraded)
  //   muted  — gray   (Redis down but not on critical path, e.g. in_process mode)
  let tone: string;
  let label: string;
  let title: string;
  if (available) {
    tone = 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300';
    label = 'Redis OK';
    title = url ? `Connected: ${url}` : 'Connected';
  } else if (required_for_live_updates) {
    tone = 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300';
    label = 'Redis down · live UI degraded';
    title =
      `${error || 'Unavailable'}. ` +
      'DB persistence still works; the live admin tail / WebSocket fan-out won\'t push real-time events. ' +
      'Set PHOVEU_BACKEND_REDIS_URL and start a Redis container to fix.';
  } else {
    tone = 'bg-gray-100 text-gray-600 dark:bg-gray-100/30';
    label = 'Redis off';
    title = `${error || 'Not configured'}. Not required in in-process mode.`;
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] ${tone}`}
      title={title}
    >
      <Database className="w-3 h-3" />
      {label}
    </span>
  );
}

function WorkerStatusPill({ status, alive }: { status: string; alive: boolean }) {
  // Render the *effective* state — a row marked "running" but with no
  // heartbeat in 30+ seconds is functionally stale. The backend's reaper
  // catches up within 30s; this gives correct UI in the meantime.
  const effective = !alive && (status === 'running' || status === 'paused')
    ? 'stale'
    : status;
  const tone = (() => {
    switch (effective) {
      case 'running':
        return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300';
      case 'paused':
        return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300';
      case 'stopped':
        return 'bg-gray-100 text-gray-600 dark:bg-gray-100/30';
      case 'stale':
        return 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300';
      default:
        return 'bg-gray-100 text-gray-600';
    }
  })();
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded font-mono text-[10px] uppercase ${tone}`}>
      {effective}
    </span>
  );
}

function formatStartedShort(iso: string): string {
  try {
    const d = new Date(iso);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  } catch {
    return '—';
  }
}

function StatePill({ state }: { state: string }) {
  const tone = (() => {
    switch (state) {
      case 'CONNECTED':
        return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300';
      case 'CONNECTING':
      case 'RECONNECTING':
        return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300';
      case 'DISCONNECTED':
      case 'DISABLED':
        return 'bg-gray-100 text-gray-600 dark:bg-gray-100/30';
      case 'ERROR':
        return 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300';
      default:
        return 'bg-gray-100 text-gray-600';
    }
  })();
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded font-mono text-[10px] ${tone}`}>
      {state}
    </span>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86_400)}d ${Math.floor((seconds % 86_400) / 3600)}h`;
}

function formatAge(seconds: number): string {
  if (seconds < 1) return '<1s';
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

/** "M:SS" countdown — used inline on the listener-status card to
 *  show how long until an offline session's slot is recycled. */
function formatCountdown(seconds: number): string {
  if (seconds < 0) return '0:00';
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}

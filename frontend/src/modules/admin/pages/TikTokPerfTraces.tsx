/**
 * /admin/tiktok/perf — list recent per-request performance traces.
 *
 * Each trace row carries the request's total duration, span tree,
 * query count, and handle (when the path was scoped). The table
 * collapses by default; expand a row to see the full span breakdown
 * as a left-anchored horizontal bar chart so eye-scanning "what's
 * the dominant cost?" is instant.
 *
 * Filters:
 *   - endpoint   (exact route template — `/admin/tiktok/...`)
 *   - handle     (host name when path-scoped)
 *   - min_total_ms (only show slow traces)
 *
 * No write surface. No realtime. Refresh button + 30 s auto-poll.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, ChevronDown, ChevronRight, Filter, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { tiktokApi } from '@admin/services/tiktok';
import type { TikTokPerfTrace } from '@admin/services/tiktok';

const POLL_MS = 30_000;
const DEFAULT_MIN_MS = 0;
const DEFAULT_LIMIT = 50;

export function TikTokPerfTraces() {
  const [traces, setTraces] = useState<TikTokPerfTrace[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [endpoint, setEndpoint] = useState('');
  const [handle, setHandle] = useState('');
  const [minTotalMs, setMinTotalMs] = useState(DEFAULT_MIN_MS);
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());

  const refresh = useCallback(async () => {
    setErr(null);
    try {
      const data = await tiktokApi.listPerfTraces({
        endpoint: endpoint || undefined,
        handle: handle || undefined,
        min_total_ms: minTotalMs || undefined,
        limit: DEFAULT_LIMIT,
      });
      setTraces(data.items || []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'failed to load traces');
    } finally {
      setLoading(false);
    }
  }, [endpoint, handle, minTotalMs]);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <PageShell>
      <PageHeader
        title="Perf Traces"
        icon={<Activity className="w-5 h-5" />}
        description="Per-request span breakdown for /admin/tiktok/* and /public/tiktok/* endpoints. Newest first. Click a row to expand the span tree."
        actions={
          <Button
            variant="secondary"
            onClick={refresh}
            disabled={loading}
            aria-label="Refresh traces"
          >
            <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        }
      />

      {/* Filters strip */}
      <div className="card p-3 flex flex-wrap items-end gap-3 text-xs">
        <div className="flex flex-col gap-1 min-w-0 flex-1">
          <label className="auth-mono-label">Endpoint (exact route template)</label>
          <Input
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder="/admin/tiktok/rooms/{room_id}/stats"
          />
        </div>
        <div className="flex flex-col gap-1 w-40">
          <label className="auth-mono-label">Handle</label>
          <Input
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder="luzy.pe"
          />
        </div>
        <div className="flex flex-col gap-1 w-32">
          <label className="auth-mono-label">Min total (ms)</label>
          <Input
            type="number"
            value={String(minTotalMs)}
            onChange={(e) => setMinTotalMs(Number(e.target.value) || 0)}
            min={0}
          />
        </div>
        <Button onClick={refresh} disabled={loading} aria-label="Apply filters">
          <Filter className="w-4 h-4 mr-1.5" />
          Apply
        </Button>
      </div>

      {err && (
        <div className="rounded-md border border-rose-200 bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-300 px-3 py-2 text-sm">
          {err}
        </div>
      )}

      {loading && traces.length === 0 ? (
        <div className="card p-8 text-center text-gray-500 text-sm">Loading…</div>
      ) : traces.length === 0 ? (
        <div className="card p-8 text-center text-gray-500 text-sm">
          No traces yet. Browse some `/admin/tiktok/...` pages and refresh.
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-xs font-mono">
            <thead className="bg-gray-50 dark:bg-white/[0.03] text-gray-500 uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2 text-left w-6" />
                <th className="px-3 py-2 text-left">When</th>
                <th className="px-3 py-2 text-left">Endpoint</th>
                <th className="px-3 py-2 text-left">Handle</th>
                <th className="px-3 py-2 text-right">Total</th>
                <th className="px-3 py-2 text-right">Spans</th>
                <th className="px-3 py-2 text-right">Queries</th>
                <th className="px-3 py-2 text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t) => {
                const isOpen = expanded.has(t.id);
                const totalCls = t.total_ms >= 500
                  ? 'text-rose-700 dark:text-rose-300'
                  : t.total_ms >= 200
                    ? 'text-amber-700 dark:text-amber-300'
                    : 'text-emerald-700 dark:text-emerald-300';
                return (
                  <TraceRow
                    key={t.id}
                    trace={t}
                    open={isOpen}
                    totalCls={totalCls}
                    onToggle={() => toggleExpand(t.id)}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}

interface TraceRowProps {
  trace: TikTokPerfTrace;
  open: boolean;
  totalCls: string;
  onToggle: () => void;
}

function TraceRow({ trace, open, totalCls, onToggle }: TraceRowProps) {
  return (
    <>
      <tr
        className="border-t border-gray-100 dark:border-white/[0.04] hover:bg-gray-50 dark:hover:bg-white/[0.02] cursor-pointer"
        onClick={onToggle}
      >
        <td className="px-3 py-2 text-gray-400">
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </td>
        <td className="px-3 py-2 text-gray-500 tabular-nums">
          {trace.ts ? new Date(trace.ts).toLocaleTimeString() : '—'}
        </td>
        <td className="px-3 py-2 truncate max-w-[420px]" title={trace.endpoint}>
          <span className="inline-block px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/5 mr-2 text-[10px]">
            {trace.method}
          </span>
          {trace.endpoint}
        </td>
        <td className="px-3 py-2 text-gray-500">{trace.handle ?? '—'}</td>
        <td className={`px-3 py-2 text-right tabular-nums font-bold ${totalCls}`}>
          {trace.total_ms} ms
        </td>
        <td className="px-3 py-2 text-right text-gray-500 tabular-nums">{trace.spans.length}</td>
        <td className="px-3 py-2 text-right text-gray-500 tabular-nums">
          {trace.query_count ?? '—'}
        </td>
        <td className="px-3 py-2 text-right text-gray-500 tabular-nums">
          {trace.status ?? '—'}
        </td>
      </tr>
      {open && (
        <tr className="bg-gray-50 dark:bg-white/[0.02]">
          <td colSpan={8} className="px-4 py-3">
            <SpanTree spans={trace.spans} total={trace.total_ms} traceId={trace.trace_id} meta={trace.meta} />
          </td>
        </tr>
      )}
    </>
  );
}

interface SpanTreeProps {
  spans: TikTokPerfTrace['spans'];
  total: number;
  traceId: string;
  meta: Record<string, unknown>;
}

function SpanTree({ spans, total, traceId, meta }: SpanTreeProps) {
  // Stable max so all bars use the same scale; cap to total_ms when
  // every span fits inside the request (the common case).
  const denom = useMemo(() => {
    const maxEnd = spans.reduce((m, s) => Math.max(m, s.start_ms + s.dur_ms), 0);
    return Math.max(total, maxEnd, 1);
  }, [spans, total]);

  return (
    <div className="space-y-2">
      <div className="text-[10px] text-gray-500 font-mono">
        trace_id: <span className="text-gray-700">{traceId}</span>
        {Object.keys(meta).length > 0 && (
          <span className="ml-3">
            meta: <span className="text-gray-700">{JSON.stringify(meta)}</span>
          </span>
        )}
      </div>
      <div className="relative">
        {/* Total bar — the request's own duration as the backdrop. */}
        <div className="h-4 bg-gray-200 dark:bg-white/10 rounded relative">
          <div
            className="h-4 rounded bg-gray-300 dark:bg-white/15"
            style={{ width: '100%' }}
          />
          <div className="absolute inset-0 flex items-center justify-end px-2 text-[10px] text-gray-600 font-mono">
            total {total} ms
          </div>
        </div>
      </div>
      <div className="space-y-1">
        {spans.length === 0 ? (
          <div className="text-[11px] text-gray-500 italic">
            No spans recorded (route not instrumented yet — the middleware
            still captured `total_ms`).
          </div>
        ) : (
          spans.map((s, i) => {
            const offsetPct = Math.min(100, (s.start_ms / denom) * 100);
            const widthPct = Math.max(
              0.25, // never invisible
              Math.min(100 - offsetPct, (s.dur_ms / denom) * 100),
            );
            // Color by depth-of-call as inferred from name prefix:
            // svc.* = primary, db.* = amber, cache.* = sky, other = gray.
            const tone = s.name.startsWith('db.')
              ? 'bg-amber-500/70 dark:bg-amber-400/60'
              : s.name.startsWith('svc.')
                ? 'bg-primary-500/70 dark:bg-primary-400/60'
                : s.name.startsWith('cache.')
                  ? 'bg-sky-500/70 dark:bg-sky-400/60'
                  : 'bg-gray-500/70 dark:bg-gray-400/60';
            return (
              <div key={i} className="flex items-center gap-2">
                <div
                  className="text-[10px] text-gray-700 font-mono truncate w-64"
                  title={`${s.name} — start ${s.start_ms.toFixed(2)}ms · dur ${s.dur_ms.toFixed(2)}ms`}
                >
                  {s.name}
                </div>
                <div className="relative flex-1 h-3 bg-gray-100 dark:bg-white/5 rounded">
                  <div
                    className={`absolute top-0 h-3 ${tone} rounded`}
                    style={{ left: `${offsetPct}%`, width: `${widthPct}%` }}
                  />
                </div>
                <div className="text-[10px] text-gray-600 font-mono tabular-nums w-16 text-right">
                  {s.dur_ms.toFixed(1)} ms
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export default TikTokPerfTraces;

/**
 * Worker telemetry — four chart cards on the Worker tab.
 *
 *  1. Sessions & connect-count over time   (line, dual axis)
 *  2. Worker process CPU% + memory (MB)    (line, dual axis)
 *  3. Event-type ingest rate                (stacked area)
 *  4. WAF pressure by handle (top 12)       (horizontal bar)
 *  5. Reconcile pass cadence + duration p95 (line)
 *
 * All four payloads come from a single `/worker/telemetry` round-trip.
 */

import { useEffect, useMemo, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactECharts from 'echarts-for-react/lib/core';
import toast from 'react-hot-toast';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import {
  tiktokApi,
  type TikTokWorkerTelemetry as Telemetry,
} from '@admin/services/tiktok';

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

// Stable colours per event type — same palette family used in the
// other tiktok charts so the colours feel consistent across pages.
const TYPE_COLOR: Record<string, string> = {
  gift:           '#f59e0b', // amber-500
  comment:        '#0ea5e9', // sky-500
  like:           '#ec4899', // pink-500
  join:           '#10b981', // emerald-500
  share:          '#a855f7', // violet-500
  follow:         '#14b8a6', // teal-500
  envelope:       '#f97316', // orange-500
  viewer_count:   '#6366f1', // indigo-500
  match_update:   '#dc2626', // red-600
  battle_begin:   '#7c3aed', // violet-600
  battle_end:     '#be123c', // rose-700
  live_pause:     '#94a3b8', // slate-400
};
const FALLBACK_COLORS = ['#0d9488', '#65a30d', '#b91c1c', '#7c2d12'];
function typeColor(t: string, i: number): string {
  return TYPE_COLOR[t] ?? FALLBACK_COLORS[i % FALLBACK_COLORS.length];
}

const WINDOW_CHOICES: { label: string; hours: number }[] = [
  { label: 'Last hour',     hours: 1   },
  { label: 'Last 6 hours',  hours: 6   },
  { label: 'Last 24 hours', hours: 24  },
  { label: 'Last 3 days',   hours: 72  },
  { label: 'Last 7 days',   hours: 168 },
];

export function TikTokWorkerTelemetry() {
  const [choiceIdx, setChoiceIdx] = useState(2); // default 24h
  const [data, setData] = useState<Telemetry | null>(null);
  const [loading, setLoading] = useState(false);
  const choice = WINDOW_CHOICES[choiceIdx];

  const load = async () => {
    setLoading(true);
    try {
      const out = await tiktokApi.getWorkerTelemetry({ hours: choice.hours });
      setData(out);
    } catch (e) {
      toast.error('Failed to load worker telemetry.');
      // eslint-disable-next-line no-console
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choiceIdx]);

  // Shared bin labels — same format logic as the API History card so
  // the two pages read consistently.
  const xLabels = useMemo(() => {
    if (!data) return [] as string[];
    const fmtDate = (d: Date) =>
      d.toLocaleDateString(undefined, { month: '2-digit', day: '2-digit' });
    const fmtHour = (d: Date) =>
      d.toLocaleTimeString(undefined, { hour: '2-digit' }).replace(':00', '');
    const fmtShort = (d: Date) =>
      d.toLocaleTimeString(undefined, {
        hour: '2-digit', minute: '2-digit',
      });
    return data.heartbeat.bins.map((iso) => {
      const d = new Date(iso);
      if (choice.hours >= 72) return fmtDate(d);
      if (choice.hours >= 24) return fmtHour(d);
      return fmtShort(d);
    });
  }, [data, choice.hours]);

  // ~7 visible ticks regardless of bin count.
  const labelInterval = useMemo(() => {
    const n = data?.heartbeat.bins.length ?? 0;
    if (n <= 8) return 0;
    return Math.max(1, Math.floor(n / 7) - 1);
  }, [data?.heartbeat.bins.length]);

  return (
    <section className="flex flex-col gap-4">
      <div className="card flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="auth-mono-label">Worker telemetry</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Sessions, CPU, memory, event-type ingest and reconcile cadence
            — sampled every 5s from the worker process itself.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={String(choiceIdx)}
            onChange={(e) => setChoiceIdx(Number(e.target.value))}
          >
            {WINDOW_CHOICES.map((c, i) => (
              <option key={c.label} value={String(i)}>{c.label}</option>
            ))}
          </Select>
          <Button variant="ghost" onClick={load} disabled={loading}>
            <RefreshCw className={loading ? 'animate-spin w-4 h-4' : 'w-4 h-4'} />
          </Button>
        </div>
      </div>

      {loading && !data && (
        <div className="card text-center text-sm text-gray-500 py-12">
          Loading…
        </div>
      )}

      {data && (
        <>
          <SessionsCard data={data} xLabels={xLabels} labelInterval={labelInterval} />
          <CpuMemCard   data={data} xLabels={xLabels} labelInterval={labelInterval} />
          <EventTypesCard data={data} xLabels={xLabels} labelInterval={labelInterval} />
          <WafCard      data={data} />
          <ReconcileCard data={data} xLabels={xLabels} labelInterval={labelInterval} />
        </>
      )}
    </section>
  );
}

interface CardProps {
  data: Telemetry;
  xLabels: string[];
  labelInterval: number;
}

function SessionsCard({ data, xLabels, labelInterval }: CardProps) {
  const opt = useMemo(() => {
    const hb = data.heartbeat;
    const hasData = hb.sessions.some((v) => v !== null);
    if (!hasData) return null;
    return {
      animation: false,
      tooltip: { trigger: 'axis' as const },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: 50, right: 16, top: 20, bottom: 36 },
      xAxis: {
        type: 'category' as const,
        data: xLabels,
        axisLabel: { fontSize: 10, interval: labelInterval, margin: 6 },
      },
      yAxis: { type: 'value' as const, axisLabel: { fontSize: 10 } },
      series: [
        {
          name: 'sessions held',
          type: 'line' as const,
          showSymbol: false,
          smooth: true,
          data: hb.sessions,
          itemStyle: { color: '#0ea5e9' },
          areaStyle: { opacity: 0.12 },
        },
        {
          name: 'CONNECTED',
          type: 'line' as const,
          showSymbol: false,
          smooth: true,
          data: hb.connected,
          itemStyle: { color: '#10b981' },
        },
      ],
    };
  }, [data, xLabels, labelInterval]);
  const lastSessions = lastNonNull(data.heartbeat.sessions);
  const lastConnected = lastNonNull(data.heartbeat.connected);
  return (
    <ChartCard
      title="Sessions held vs. CONNECTED"
      subtitle="Held = claimed by this worker. CONNECTED = WS actively streaming events."
      headlineChips={[
        ['now held',      lastSessions === null ? '—' : String(lastSessions)],
        ['now connected', lastConnected === null ? '—' : String(lastConnected)],
      ]}
      empty={!opt}
      emptyMsg="No heartbeat rows in this window yet."
    >
      {opt && (
        <ReactECharts echarts={echarts} option={opt}
                      style={{ height: 220, width: '100%' }}
                      notMerge lazyUpdate />
      )}
    </ChartCard>
  );
}

function CpuMemCard({ data, xLabels, labelInterval }: CardProps) {
  const opt = useMemo(() => {
    const hb = data.heartbeat;
    const hasData = hb.cpu_pct.some((v) => v !== null) || hb.memory_mb.some((v) => v !== null);
    if (!hasData) return null;
    return {
      animation: false,
      tooltip: { trigger: 'axis' as const },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: 50, right: 50, top: 20, bottom: 36 },
      xAxis: {
        type: 'category' as const,
        data: xLabels,
        axisLabel: { fontSize: 10, interval: labelInterval, margin: 6 },
      },
      yAxis: [
        {
          type: 'value' as const,
          name: 'CPU %',
          position: 'left',
          axisLabel: { fontSize: 10, formatter: '{value}%' },
          splitLine: { show: true },
        },
        {
          type: 'value' as const,
          name: 'MB',
          position: 'right',
          axisLabel: { fontSize: 10, formatter: '{value}' },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'CPU',
          type: 'line' as const,
          showSymbol: false,
          smooth: true,
          data: hb.cpu_pct,
          itemStyle: { color: '#dc2626' },
          areaStyle: { opacity: 0.10 },
          yAxisIndex: 0,
        },
        {
          name: 'RSS (MB)',
          type: 'line' as const,
          showSymbol: false,
          smooth: true,
          data: hb.memory_mb,
          itemStyle: { color: '#7c3aed' },
          yAxisIndex: 1,
        },
      ],
    };
  }, [data, xLabels, labelInterval]);
  const lastCpu = lastNonNull(data.heartbeat.cpu_pct);
  const lastMem = lastNonNull(data.heartbeat.memory_mb);
  return (
    <ChartCard
      title="Process CPU + memory"
      subtitle="Per-process CPU% (since previous sample) + RSS resident memory."
      headlineChips={[
        ['CPU now', lastCpu === null ? '—' : `${lastCpu.toFixed(1)}%`],
        ['RSS now', lastMem === null ? '—' : `${lastMem} MB`],
      ]}
      empty={!opt}
      emptyMsg="No CPU / memory samples in this window yet."
    >
      {opt && (
        <ReactECharts echarts={echarts} option={opt}
                      style={{ height: 220, width: '100%' }}
                      notMerge lazyUpdate />
      )}
    </ChartCard>
  );
}

function EventTypesCard({ data, xLabels, labelInterval }: CardProps) {
  const opt = useMemo(() => {
    const et = data.event_types;
    if (et.types.length === 0) return null;
    const series = et.series.map((s, i) => ({
      name: s.type,
      type: 'line' as const,
      stack: 'total',
      areaStyle: {},
      emphasis: { focus: 'series' as const },
      showSymbol: false,
      data: s.counts,
      itemStyle: { color: typeColor(s.type, i) },
      lineStyle: { width: 0 },
    }));
    return {
      animation: false,
      tooltip: { trigger: 'axis' as const },
      legend: { bottom: 0, textStyle: { fontSize: 11 }, type: 'scroll' as const },
      grid: { left: 50, right: 16, top: 20, bottom: 48 },
      xAxis: {
        type: 'category' as const,
        data: xLabels,
        axisLabel: { fontSize: 10, interval: labelInterval, margin: 6 },
      },
      yAxis: { type: 'value' as const, name: 'events / bin', axisLabel: { fontSize: 10 } },
      series,
    };
  }, [data, xLabels, labelInterval]);
  return (
    <ChartCard
      title="Event ingest by type"
      subtitle={`Top-${data.event_types.types.length} event types in this window, aggregated per hour bucket.`}
      headlineChips={data.event_types.types.slice(0, 4).map((t) => [
        t,
        data.event_types.totals[t].toLocaleString(),
      ])}
      empty={!opt}
      emptyMsg="No event-type counts in this window yet."
    >
      {opt && (
        <ReactECharts echarts={echarts} option={opt}
                      style={{ height: 240, width: '100%' }}
                      notMerge lazyUpdate />
      )}
    </ChartCard>
  );
}

function WafCard({ data }: { data: Telemetry }) {
  const entries = useMemo(() => {
    return Object.entries(data.waf.totals)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 12);
  }, [data.waf.totals]);
  const opt = useMemo(() => {
    if (entries.length === 0) return null;
    const handles = entries.map(([h]) => h);
    const counts = entries.map(([, n]) => n);
    return {
      animation: false,
      tooltip: { trigger: 'axis' as const },
      grid: { left: 110, right: 24, top: 8, bottom: 24 },
      xAxis: { type: 'value' as const, axisLabel: { fontSize: 10 } },
      yAxis: {
        type: 'category' as const,
        data: handles,
        inverse: true,
        axisLabel: { fontSize: 10 },
      },
      series: [
        {
          type: 'bar' as const,
          data: counts,
          itemStyle: { color: '#f59e0b' },
          barCategoryGap: '20%',
        },
      ],
    };
  }, [entries]);
  return (
    <ChartCard
      title="WAF pressure by handle"
      subtitle={
        'Counts a WAF challenge each time the profile scraper trips '
        + 'the public-site anti-bot gate (rate-limited to 1 row / handle / 10 min).'
      }
      headlineChips={[
        ['detections', data.waf.all.toLocaleString()],
        ['affected handles', String(Object.keys(data.waf.totals).length)],
      ]}
      empty={!opt}
      emptyMsg="No WAF detections in this window."
    >
      {opt && (
        <ReactECharts echarts={echarts} option={opt}
                      style={{ height: Math.max(160, entries.length * 22 + 50), width: '100%' }}
                      notMerge lazyUpdate />
      )}
    </ChartCard>
  );
}

function ReconcileCard({ data, xLabels, labelInterval }: CardProps) {
  const opt = useMemo(() => {
    const r = data.reconcile;
    const hasData = r.pass_count.some((v) => v > 0);
    if (!hasData) return null;
    return {
      animation: false,
      tooltip: { trigger: 'axis' as const },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: 50, right: 50, top: 20, bottom: 36 },
      xAxis: {
        type: 'category' as const,
        data: xLabels,
        axisLabel: { fontSize: 10, interval: labelInterval, margin: 6 },
      },
      yAxis: [
        {
          type: 'value' as const,
          name: 'passes',
          position: 'left',
          axisLabel: { fontSize: 10 },
        },
        {
          type: 'value' as const,
          name: 'ms',
          position: 'right',
          axisLabel: { fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: 'passes / bin',
          type: 'bar' as const,
          data: r.pass_count,
          itemStyle: { color: '#94a3b8' },
          yAxisIndex: 0,
          barCategoryGap: '20%',
        },
        {
          name: 'p50 duration',
          type: 'line' as const,
          showSymbol: false,
          smooth: true,
          data: r.duration_p50,
          itemStyle: { color: '#10b981' },
          yAxisIndex: 1,
        },
        {
          name: 'p95 duration',
          type: 'line' as const,
          showSymbol: false,
          smooth: true,
          data: r.duration_p95,
          itemStyle: { color: '#ef4444' },
          yAxisIndex: 1,
        },
      ],
    };
  }, [data, xLabels, labelInterval]);
  return (
    <ChartCard
      title="Reconcile pass cadence"
      subtitle="Bars = pass count per bin; lines = p50/p95 of the per-pass duration. Drift up = control-plane stress."
      headlineChips={[
        ['claimed (window)', data.reconcile.claimed_total.toLocaleString()],
        ['lost (window)',    data.reconcile.lost_total.toLocaleString()],
      ]}
      empty={!opt}
      emptyMsg="No reconcile passes recorded in this window yet."
    >
      {opt && (
        <ReactECharts echarts={echarts} option={opt}
                      style={{ height: 200, width: '100%' }}
                      notMerge lazyUpdate />
      )}
    </ChartCard>
  );
}

// ── small shared layout helpers ─────────────────────────────────────

interface ChartCardShellProps {
  title: string;
  subtitle: string;
  headlineChips: [string, string][];
  empty: boolean;
  emptyMsg: string;
  children?: React.ReactNode;
}

function ChartCard({
  title, subtitle, headlineChips, empty, emptyMsg, children,
}: ChartCardShellProps) {
  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h3 className="auth-mono-label">{title}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1 shrink-0">
          {headlineChips.map(([label, value]) => (
            <span
              key={label}
              className="px-2 py-0.5 rounded font-mono text-[10px] bg-gray-50 dark:bg-gray-100/30"
            >
              {label}: {value}
            </span>
          ))}
        </div>
      </div>
      {empty
        ? <div className="text-center text-xs text-gray-500 py-8">{emptyMsg}</div>
        : children}
    </div>
  );
}

/** Last non-null entry in an array — useful for "now" headline chips
 *  when the tail of the heartbeat series may be sparse during boot. */
function lastNonNull<T>(arr: (T | null)[]): T | null {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i] !== null) return arr[i];
  }
  return null;
}

export default TikTokWorkerTelemetry;

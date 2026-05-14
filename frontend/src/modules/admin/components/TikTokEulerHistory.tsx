/**
 * Euler API call history — stacked bar histogram for the
 * Sign Engine tab. Answers "what burned my quota?" with hard data
 * sliced by endpoint (and grouped by API key when more than one is
 * present in the window — i.e. across a key rotation).
 *
 *   <TikTokEulerHistory />
 *
 * Self-fetching; refreshes when the user picks a different look-back
 * window or bucket width.
 */

import { useEffect, useMemo, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactECharts from 'echarts-for-react/lib/core';
import toast from 'react-hot-toast';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { tiktokApi, type TikTokEulerHistory } from '@admin/services/tiktok';

echarts.use([
  BarChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

// Stable palette per endpoint so re-renders keep the same colour
// assignment — easier to spot trends visually. Sky / amber / rose /
// teal / violet etc. — accessible against both light and dark mode.
const ENDPOINT_PALETTE: Record<string, string> = {
  'webcast/fetch': '#0ea5e9',                 // sky-500
  'webcast/room/info': '#f59e0b',              // amber-500
  'webcast/room/check_alive': '#10b981',       // emerald-500
  'webcast/room/enter': '#a855f7',             // violet-500
};
const FALLBACK_PALETTE = [
  '#ec4899', '#6366f1', '#14b8a6', '#ef4444', '#0d9488', '#7c3aed',
];

function colorForEndpoint(ep: string, fallbackIdx: number): string {
  return ENDPOINT_PALETTE[ep] ?? FALLBACK_PALETTE[fallbackIdx % FALLBACK_PALETTE.length];
}

interface WindowChoice {
  label: string;
  hours: number;
  bucketMinutes: number;
}

const WINDOW_CHOICES: WindowChoice[] = [
  { label: 'Last hour (1 min bins)',    hours: 1,   bucketMinutes: 1 },
  { label: 'Last 6 hours (5 min bins)', hours: 6,   bucketMinutes: 5 },
  { label: 'Last 24 hours (15 min)',    hours: 24,  bucketMinutes: 15 },
  { label: 'Last 3 days (1 hour bins)', hours: 72,  bucketMinutes: 60 },
  { label: 'Last 7 days (1 hour bins)', hours: 168, bucketMinutes: 60 },
];

export function TikTokEulerHistory() {
  const [choiceIdx, setChoiceIdx] = useState(2); // default = 24h / 15-min
  const [data, setData] = useState<TikTokEulerHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const choice = WINDOW_CHOICES[choiceIdx];

  const load = async () => {
    setLoading(true);
    try {
      const out = await tiktokApi.getEulerHistory({
        hours: choice.hours,
        bucketMinutes: choice.bucketMinutes,
      });
      setData(out);
    } catch (e) {
      toast.error('Failed to load Euler call history.');
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

  // Build ECharts series. We stack endpoint slices vertically so the
  // bar height for each bin reads as the total quota use that bin.
  // When multiple API keys exist in the window (a key was rotated),
  // we emit one series PER (endpoint, key) so the user can see which
  // key absorbed each slice — the key is appended to the series name
  // and surfaced in the tooltip + legend.
  const option = useMemo(() => {
    if (!data) return null;
    const hasMultipleKeys = data.api_keys.length > 1;
    const epsSorted = [...data.endpoints].sort();
    const epIndex = new Map<string, number>(
      epsSorted.map((ep, i) => [ep, i] as const),
    );

    type SeriesItem = {
      name: string;
      type: 'bar';
      stack: string;
      data: number[];
      itemStyle: { color: string };
      emphasis: { focus: 'series' };
    };
    const series: SeriesItem[] = data.series.map((s) => ({
      name: hasMultipleKeys
        ? `${s.endpoint} · ${s.api_key_fp}`
        : s.endpoint,
      type: 'bar' as const,
      stack: hasMultipleKeys ? s.api_key_fp : 'total',
      data: s.counts,
      itemStyle: {
        color: colorForEndpoint(s.endpoint, epIndex.get(s.endpoint) ?? 0),
      },
      emphasis: { focus: 'series' as const },
    }));

    const xLabels = data.bins.map((iso) => {
      const d = new Date(iso);
      // Compact label: HH:MM for short windows, MM-DD HH:MM for ≥24h
      if (choice.hours >= 24) {
        return d.toLocaleString(undefined, {
          month: '2-digit', day: '2-digit',
          hour: '2-digit', minute: '2-digit',
        });
      }
      return d.toLocaleTimeString(undefined, {
        hour: '2-digit', minute: '2-digit',
      });
    });

    return {
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      legend: {
        type: 'scroll',
        bottom: 0,
        textStyle: { fontSize: 11 },
      },
      grid: { left: 50, right: 16, top: 20, bottom: hasMultipleKeys ? 56 : 40 },
      xAxis: {
        type: 'category',
        data: xLabels,
        axisLabel: { fontSize: 10, rotate: choice.hours >= 24 ? 35 : 0 },
      },
      yAxis: {
        type: 'value',
        name: 'calls',
        axisLabel: { fontSize: 10 },
      },
      series,
    };
  }, [data, choice.hours]);

  const totalCalls = data?.totals.all ?? 0;
  const epTotals = data?.totals.by_endpoint ?? {};
  const keyTotals = data?.totals.by_key ?? {};

  return (
    <section className="card">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div>
          <h3 className="auth-mono-label">API History</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Euler-signed HTTP calls — every probe, every reconnect.
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

      {/* Headline stats. The "by endpoint" + "by key" breakdowns help
          spot the top quota burner at a glance without reading the
          chart's stacked colours. */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-sm">
        <div className="px-3 py-2 rounded border border-gray-200">
          <div className="auth-mono-label text-[10px]">Total in window</div>
          <div className="font-mono text-lg">{totalCalls.toLocaleString()}</div>
        </div>
        {Object.entries(epTotals)
          .sort(([, a], [, b]) => b - a)
          .slice(0, 3)
          .map(([ep, n]) => (
            <div key={ep} className="px-3 py-2 rounded border border-gray-200">
              <div className="auth-mono-label text-[10px] truncate" title={ep}>
                {ep.replace('webcast/', '')}
              </div>
              <div className="font-mono text-lg">{n.toLocaleString()}</div>
            </div>
          ))}
      </div>

      {/* Per-API-key breakdown when ≥1 key appeared in the window —
          useful right after a key rotation: lets you see the old key
          still being called by stale processes. Collapsed to a single
          line when only one key exists. */}
      {data && data.api_keys.length > 0 && (
        <div className="mb-4 text-xs flex flex-wrap gap-2">
          {Object.entries(keyTotals)
            .sort(([, a], [, b]) => b - a)
            .map(([fp, n]) => (
              <span
                key={fp}
                className="px-2 py-0.5 rounded font-mono bg-gray-50 text-gray-700 dark:bg-gray-100/30"
                title={fp}
              >
                {fp} → {n.toLocaleString()}
              </span>
            ))}
        </div>
      )}

      {/* The chart. ECharts collapses gracefully on 0 series — but
          we still hide it when there's truly no data so the empty-state
          message reads as the primary content. */}
      {loading && !data && (
        <div className="text-center text-sm text-gray-500 py-12">Loading…</div>
      )}
      {!loading && totalCalls === 0 && (
        <div className="text-center text-sm text-gray-500 py-12">
          No Euler calls captured in this window yet. Logging starts when
          the listener pool connects — boot the worker and check back in
          a minute.
        </div>
      )}
      {option && totalCalls > 0 && (
        <ReactECharts
          echarts={echarts}
          option={option}
          style={{ height: 320, width: '100%' }}
          notMerge
          lazyUpdate
        />
      )}
    </section>
  );
}

export default TikTokEulerHistory;

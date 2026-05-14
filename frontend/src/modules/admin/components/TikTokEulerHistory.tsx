/**
 * Euler / TikTok HTTP call history — Admin → TikTok → Settings →
 * API History tab.
 *
 * Two stacked-bar histograms side by side:
 *   1. Euler-billing (sign API + signed `webcast/*` endpoints). Each
 *      bar segment = one slot of quota burned.
 *   2. Direct TikTok scrapes (profile / live HTML). No quota cost
 *      but they hit the public-site WAF, so worth tracking separately.
 *
 * A thin "outcomes" strip below each chart shows status-code class
 * counts per bin (2xx / 3xx / 4xx / 5xx / network err). Lets you
 * spot 429-rate-limit storms next to the endpoint stack.
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
import {
  tiktokApi,
  type TikTokEulerHistory,
  type TikTokEulerHistoryBucket,
} from '@admin/services/tiktok';

echarts.use([
  BarChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

// Palette — one stable colour per endpoint label. ECharts won't
// reshuffle on every re-render because we set itemStyle.color
// explicitly per series. Falls back to a rotation for any endpoint
// we haven't seen before.
const ENDPOINT_COLOR: Record<string, string> = {
  // Euler-billing
  'webcast/fetch':                  '#0ea5e9', // sky-500
  'webcast/room/info':               '#f59e0b', // amber-500
  'webcast/room/info_by_user':       '#f97316', // orange-500
  'webcast/room/check_alive':        '#10b981', // emerald-500
  'webcast/room/enter':              '#a855f7', // violet-500
  'eulerstream':                     '#6366f1', // indigo-500
  // Direct TikTok
  'tiktok/profile':                  '#14b8a6', // teal-500
  'tiktok/live':                     '#ec4899', // pink-500
  'tiktok/video':                    '#d97706', // amber-600
};
const FALLBACK = ['#ef4444', '#7c3aed', '#0d9488', '#65a30d', '#b91c1c'];
function colorFor(ep: string, i: number): string {
  return ENDPOINT_COLOR[ep] ?? FALLBACK[i % FALLBACK.length];
}

// Outcome class colours — green = 2xx, blue = 3xx, amber = 4xx,
// red = 5xx, gray = network/timeout. Stays subdued on the strip
// chart so it doesn't fight the main bar chart above it.
const OUTCOME_COLOR: Record<string, string> = {
  '2xx': '#10b981',
  '3xx': '#0ea5e9',
  '4xx': '#f59e0b',
  '5xx': '#ef4444',
  'err': '#94a3b8',
};

interface WindowChoice {
  label: string;
  hours: number;
  bucketMinutes: number;
}

const WINDOW_CHOICES: WindowChoice[] = [
  { label: 'Last hour (1 min bins)',     hours: 1,   bucketMinutes: 1 },
  { label: 'Last 6 hours (5 min bins)',  hours: 6,   bucketMinutes: 5 },
  { label: 'Last 24 hours (15 min)',     hours: 24,  bucketMinutes: 15 },
  { label: 'Last 3 days (1 hour bins)',  hours: 72,  bucketMinutes: 60 },
  { label: 'Last 7 days (1 hour bins)',  hours: 168, bucketMinutes: 60 },
];

export function TikTokEulerHistory() {
  const [choiceIdx, setChoiceIdx] = useState(2);
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
      toast.error('Failed to load API call history.');
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

  // X-axis labels — same length as the data, but the chart's
  // `axisLabel.interval` filter only renders ~6–10 of them so they
  // never crowd. Three formats based on window:
  //   ≥72h : "MM-DD"  (date only — each tick is a day boundary)
  //   ≥24h : "HH:00"  (date implied by the run; hour is the unit)
  //   <24h : "HH:MM"  (within-day resolution)
  const xLabels = useMemo(() => {
    if (!data) return [] as string[];
    const fmtShort = (d: Date) =>
      d.toLocaleTimeString(undefined, {
        hour: '2-digit', minute: '2-digit',
      });
    const fmtHour = (d: Date) =>
      d.toLocaleTimeString(undefined, { hour: '2-digit' }).replace(':00', '');
    const fmtDate = (d: Date) =>
      d.toLocaleDateString(undefined, { month: '2-digit', day: '2-digit' });
    return data.bins.map((iso) => {
      const d = new Date(iso);
      if (choice.hours >= 72) return fmtDate(d);
      if (choice.hours >= 24) return fmtHour(d);
      return fmtShort(d);
    });
  }, [data, choice.hours]);

  // Tick interval — pick a step that yields ~7 visible labels.
  // ECharts' `axisLabel.interval` is the gap BETWEEN shown ticks
  // (0 = every tick). We compute it from total bin count.
  const labelInterval = useMemo(() => {
    const n = data?.bins.length ?? 0;
    if (n <= 8) return 0;
    return Math.max(1, Math.floor(n / 7) - 1);
  }, [data?.bins.length]);

  return (
    <section className="flex flex-col gap-4">
      {/* Controls strip. Window picker + refresh, plus the headline
          "total in window" badge for quick comparison across windows. */}
      <div className="card flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="auth-mono-label">API call history</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Every HTTP call we make to TikTok / EulerStream. Top = quota
            cost; bottom = direct scrapes (no quota, WAF-bait).
          </p>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <span className="px-2 py-0.5 rounded font-mono text-xs bg-gray-50 dark:bg-gray-100/30">
              room-info {data.room_info.totals.all.toLocaleString()}
              {' · '}
              euler {data.euler.totals.all.toLocaleString()}
              {' · '}
              direct {data.direct.totals.all.toLocaleString()}
            </span>
          )}
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

      {/* Empty state. Logs only start once the worker boots and makes
          its first call — boot lag is friendlier than an awkward
          empty chart. */}
      {loading && !data && (
        <div className="card text-center text-sm text-gray-500 py-12">
          Loading…
        </div>
      )}
      {!loading && data
        && data.room_info.totals.all === 0
        && data.euler.totals.all === 0
        && data.direct.totals.all === 0 && (
        <div className="card text-center text-sm text-gray-500 py-12">
          No calls captured in this window yet. Logging starts when the
          listener pool connects — boot the worker and check back in a
          minute.
        </div>
      )}

      {data && (
        data.room_info.totals.all > 0
        || data.euler.totals.all > 0
        || data.direct.totals.all > 0
      ) && (
        <>
          <ChartCard
            title="Room discovery probes"
            subtitle={
              'webcast/room/info + webcast/room/info_by_user — handle → '
              + 'room_id lookups. Biggest quota burners in practice.'
            }
            bucket={data.room_info}
            apiKeys={data.api_keys}
            xLabels={xLabels}
            labelInterval={labelInterval}
            outcomes={data.outcomes.counts.room_info}
            outcomeLabels={data.outcomes.labels}
            countTotal={data.room_info.totals.all}
          />
          <ChartCard
            title="Other Euler-billing calls"
            subtitle={
              'Every bar segment = 1 sign-quota slot. '
              + 'fetch (signed WSS URL), check_alive, enter, etc.'
            }
            bucket={data.euler}
            apiKeys={data.api_keys}
            xLabels={xLabels}
            labelInterval={labelInterval}
            outcomes={data.outcomes.counts.euler}
            outcomeLabels={data.outcomes.labels}
            countTotal={data.euler.totals.all}
          />
          <ChartCard
            title="Direct TikTok scrapes"
            subtitle={
              'Anonymous HTML fetches (profile + live page). '
              + 'No Euler quota, but every call hits the public-site WAF.'
            }
            bucket={data.direct}
            apiKeys={data.api_keys}
            xLabels={xLabels}
            labelInterval={labelInterval}
            outcomes={data.outcomes.counts.direct}
            outcomeLabels={data.outcomes.labels}
            countTotal={data.direct.totals.all}
            muted
          />
        </>
      )}
    </section>
  );
}

interface ChartCardProps {
  title: string;
  subtitle: string;
  bucket: TikTokEulerHistoryBucket;
  apiKeys: string[];
  xLabels: string[];
  /** ECharts `axisLabel.interval`. 0 = show every tick. Higher means
   *  show every Nth tick (gap between visible labels = N). */
  labelInterval: number;
  outcomes: number[][];               // [N bins][5]
  outcomeLabels: string[];
  countTotal: number;
  /** Renders with slightly subdued chrome for the secondary chart. */
  muted?: boolean;
}

/** A single endpoint-stacked histogram with headline cards above and
 *  an outcome-class strip below. Memoised by data identity so a
 *  re-render of the parent doesn't reflow the chart instance. */
function ChartCard({
  title, subtitle, bucket, apiKeys, xLabels, labelInterval,
  outcomes, outcomeLabels, countTotal, muted,
}: ChartCardProps) {
  const hasMultipleKeys = apiKeys.length > 1;

  const stackOption = useMemo(() => {
    if (countTotal === 0) return null;
    const series = bucket.series.map((s, i) => ({
      name: hasMultipleKeys ? `${s.endpoint} · ${s.api_key_fp}` : s.endpoint,
      type: 'bar' as const,
      stack: hasMultipleKeys ? s.api_key_fp : 'total',
      data: s.counts,
      itemStyle: { color: colorFor(s.endpoint, i) },
      emphasis: { focus: 'series' as const },
      barCategoryGap: '15%',
    }));
    return {
      animation: false,
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: {
        type: 'scroll' as const,
        bottom: 0,
        textStyle: { fontSize: 11 },
      },
      grid: {
        left: 50, right: 16, top: 12,
        bottom: hasMultipleKeys ? 50 : 36,
      },
      xAxis: {
        type: 'category' as const,
        data: xLabels,
        axisLabel: {
          fontSize: 10,
          // Always horizontal — rotation reads worse than a sparser
          // straight line even when bin count is high. The interval
          // computed upstream caps visible labels at ~7.
          rotate: 0,
          interval: labelInterval,
          // Subtle: shrink the gap-to-axis so labels feel attached to
          // ticks rather than floating below the chart.
          margin: 6,
        },
      },
      yAxis: {
        type: 'value' as const,
        name: 'calls',
        axisLabel: { fontSize: 10 },
      },
      series,
    };
  }, [bucket.series, xLabels, hasMultipleKeys, countTotal]);

  const outcomeOption = useMemo(() => {
    if (countTotal === 0) return null;
    // Transform [N][5] → 5 series of length N.
    const classes = outcomeLabels;
    const series = classes.map((label, ci) => ({
      name: label,
      type: 'bar' as const,
      stack: 'outcome',
      data: outcomes.map((row) => row[ci] ?? 0),
      itemStyle: { color: OUTCOME_COLOR[label] ?? '#9ca3af' },
      emphasis: { focus: 'series' as const },
      barCategoryGap: '15%',
    }));
    return {
      animation: false,
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { bottom: 0, textStyle: { fontSize: 10 } },
      grid: { left: 50, right: 16, top: 8, bottom: 26 },
      xAxis: {
        type: 'category' as const,
        data: xLabels,
        show: false,
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { fontSize: 10 },
        splitNumber: 2,
      },
      series,
    };
  }, [outcomes, xLabels, outcomeLabels, countTotal]);

  return (
    <div className={'card ' + (muted ? 'bg-gray-50/40 dark:bg-gray-100/10' : '')}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="auth-mono-label">{title}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>
        </div>
        <span className="px-2 py-0.5 rounded font-mono text-xs whitespace-nowrap bg-gray-50 dark:bg-gray-100/30">
          {countTotal.toLocaleString()} in window
        </span>
      </div>

      {/* Top-3 endpoint totals — instant "where did it go" answer
          without parsing colour blocks. */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 mb-3 text-xs">
        {Object.entries(bucket.totals.by_endpoint)
          .sort(([, a], [, b]) => b - a)
          .slice(0, 5)
          .map(([ep, n]) => (
            <div
              key={ep}
              className="px-2 py-1 rounded border border-gray-200 flex items-center justify-between gap-2 min-w-0"
            >
              <span
                className="inline-block w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: ENDPOINT_COLOR[ep] ?? '#9ca3af' }}
              />
              <span className="truncate font-mono text-[10px] flex-1" title={ep}>
                {ep.replace(/^webcast\//, '').replace(/^tiktok\//, '')}
              </span>
              <span className="font-mono">{n.toLocaleString()}</span>
            </div>
          ))}
      </div>

      {/* Main stacked chart. */}
      {stackOption && (
        <ReactECharts
          echarts={echarts}
          option={stackOption}
          style={{ height: 240, width: '100%' }}
          notMerge
          lazyUpdate
        />
      )}

      {/* Outcome strip — only worth showing when there's at least one
          non-2xx call in the window (otherwise it's a flat green bar
          that wastes vertical space). */}
      {outcomeOption && outcomes.some((row) => (row[1] + row[2] + row[3] + row[4]) > 0) && (
        <div className="mt-2 pt-2 border-t border-gray-200">
          <div className="text-[10px] font-mono text-gray-500 mb-1">
            Outcomes (2xx / 3xx / 4xx / 5xx / err)
          </div>
          <ReactECharts
            echarts={echarts}
            option={outcomeOption}
            style={{ height: 100, width: '100%' }}
            notMerge
            lazyUpdate
          />
        </div>
      )}
    </div>
  );
}

export default TikTokEulerHistory;

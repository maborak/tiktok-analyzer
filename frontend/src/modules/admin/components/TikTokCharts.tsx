import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

/**
 * Recharts-backed chart components for the TikTok module.
 *
 * Public API (kept stable so consumer pages don't need updates):
 *   <MiniLineChart points labels label color height showAxis format /> — single
 *     time-series area chart with smooth curve, gradient fill, axis ticks
 *     visible when showAxis, hover tooltip, max-value Y axis.
 *   <MultiLineChart series labels height showLegend format /> — multiple
 *     non-stacked lines sharing an X axis, with combined tooltip.
 *   <StackedAreaChart series labels height showLegend /> — stacked areas
 *     for the cross-creator dashboard.
 *
 * All charts use ResponsiveContainer so they fill their parent width and
 * scale on resize.
 */

// Common palette for event types — kept here so pages can color-code.
export const EVENT_TYPE_COLORS: Record<string, string> = {
  comment:   '#0ea5e9', // sky-500
  gift:      '#f59e0b', // amber-500
  like:      '#ef4444', // red-500
  join:      '#10b981', // emerald-500
  follow:    '#8b5cf6', // violet-500
  share:     '#ec4899', // pink-500
  subscribe: '#f43f5e', // rose-500
  connected: '#14b8a6', // teal-500
};

export const eventColor = (type: string): string =>
  EVENT_TYPE_COLORS[type] ?? '#6b7280';

// ──────────────────────────── shared utils ──────────────────────────────

const GRID = '#9ca3af'; // neutral grey; opacity is set on the element.

function formatDefault(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toString();
}

function tickEvery<T>(arr: T[], maxTicks = 6): T[] {
  if (arr.length <= maxTicks) return Array.from(new Set(arr));
  const step = Math.ceil(arr.length / maxTicks);
  const picked = arr.filter((_, i) => i % step === 0);
  // Dedupe: upstream data sometimes carries two rows for the same
  // bucket boundary (e.g. the per-broadcast stats endpoint can emit
  // overlapping minute buckets when a session straddles the boundary).
  // Two ticks with the same `t` produce two Recharts <ForwardRef>
  // children with identical React keys (`tick-{label}-{x}-{x}`),
  // which React DEV mode flags as a duplicate-key error. Set dedupe
  // works because `t` is always a primitive (number / formatted-time
  // string) here.
  return Array.from(new Set(picked));
}

// Custom tooltip styling — matches the framework's mono treatment.
// Recharts 3.x removed the public TooltipProps export; we type the
// payload loosely (the shape is documented + stable).
interface TooltipPayloadItem {
  name?: string;
  value?: number | string;
  color?: string;
}
interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string | number;
  format?: (n: number) => string;
}

function ChartTooltip({ active, payload, label, format }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const fmt = format ?? formatDefault;
  return (
    <div className="rounded-md border border-gray-200 bg-white/95 backdrop-blur px-2.5 py-1.5 shadow-md text-[11px]">
      {label != null && (
        <div className="font-mono text-gray-500 mb-0.5">{String(label)}</div>
      )}
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block w-2 h-2 rounded-sm"
            style={{ backgroundColor: p.color ?? '#6b7280' }}
          />
          <span className="text-gray-700">{p.name}</span>
          <span className="ml-auto tabular-nums font-mono">{fmt(Number(p.value ?? 0))}</span>
        </div>
      ))}
    </div>
  );
}

// ────────────────────────────── MiniLineChart ───────────────────────────

interface MiniLineChartProps {
  points: number[];
  labels?: string[];
  label?: string;
  color?: string;
  height?: number;
  format?: (n: number) => string;
  /** Render x-axis tick labels under the chart. */
  showAxis?: boolean;
  /** Enable click-and-drag range selection inside the chart area. The
   *  chart shows a translucent overlay while dragging and commits the
   *  selection on mouse-up. */
  selectable?: boolean;
  /** Currently committed selection in *inclusive bucket indices*, or
   *  null when nothing is selected (full-range view). The chart paints
   *  the selected region with an accent overlay. */
  selectedRange?: { startIndex: number; endIndex: number } | null;
  /** Fired when the user releases the mouse after a drag, with inclusive
   *  start/end indices. Same shape as the old brush callback. */
  onRangeSelect?: (range: { startIndex: number; endIndex: number }) => void;
}

// Margins used by AreaChart's plotting area inside the ResponsiveContainer.
// Must match the values passed to <AreaChart margin={...}>. We also add
// the YAxis's reserved width (36 below) so we can translate a clientX
// inside our outer wrapper div into a bucket index for drag-to-select.
const CHART_LEFT_OFFSET = 36; // YAxis width
const CHART_RIGHT_OFFSET = 8; // AreaChart margin.right

export function MiniLineChart({
  points,
  labels,
  color = '#0ea5e9',
  height = 80,
  format = formatDefault,
  showAxis = false,
  selectable = false,
  selectedRange = null,
  onRangeSelect,
}: MiniLineChartProps) {
  // In-progress drag state, in BUCKET INDICES. We compute these from the
  // mouse's clientX relative to our wrapping div — independent of
  // Recharts' internal event plumbing (which has been unreliable for
  // chart-area mouse capture across versions).
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragEnd, setDragEnd] = useState<number | null>(null);

  const data = useMemo(
    () =>
      points.map((v, i) => ({
        t: labels?.[i] ?? String(i),
        v,
      })),
    [points, labels]
  );

  const gradId = useMemo(
    () => `mini-grad-${color.replace('#', '')}-${Math.random().toString(36).slice(2, 7)}`,
    [color]
  );

  const xTicks = useMemo(() => tickEvery(data.map((d) => d.t), 6), [data]);

  // Translate a screen clientX into a bucket index on the chart's plotting
  // area. Clamped to [0, n-1]. Returns null when the wrapper isn't laid
  // out yet or when the chart has too few points to drag-select on.
  const xToBucket = useCallback(
    (clientX: number): number | null => {
      const el = wrapperRef.current;
      const n = data.length;
      if (!el || n < 2) return null;
      const rect = el.getBoundingClientRect();
      const plotLeft = rect.left + CHART_LEFT_OFFSET;
      const plotWidth = rect.width - CHART_LEFT_OFFSET - CHART_RIGHT_OFFSET;
      if (plotWidth <= 0) return null;
      const ratio = (clientX - plotLeft) / plotWidth;
      const idx = Math.round(ratio * (n - 1));
      return Math.max(0, Math.min(n - 1, idx));
    },
    [data.length],
  );

  const onWrapperMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!selectable) return;
    const idx = xToBucket(e.clientX);
    if (idx == null) return;
    e.preventDefault(); // suppress text selection
    setDragStart(idx);
    setDragEnd(idx);
  };

  // We attach mousemove/mouseup to the WINDOW while a drag is in progress
  // so the drag works even if the cursor leaves the chart bounds.
  useEffect(() => {
    if (!selectable || dragStart == null) return;
    const handleMove = (e: MouseEvent) => {
      const idx = xToBucket(e.clientX);
      if (idx != null) setDragEnd(idx);
    };
    const handleUp = (e: MouseEvent) => {
      const finalEnd = xToBucket(e.clientX);
      const a = dragStart;
      const b = finalEnd ?? dragEnd ?? dragStart;
      setDragStart(null);
      setDragEnd(null);
      if (a == null || b == null) return;
      // Tiny drag = misclick. Don't commit a 0-width selection.
      if (Math.abs(b - a) < 1) return;
      onRangeSelect?.({
        startIndex: Math.min(a, b),
        endIndex: Math.max(a, b),
      });
    };
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [selectable, dragStart, dragEnd, xToBucket, onRangeSelect]);

  // Visual range = either the in-progress drag or the committed selection.
  const overlay = (() => {
    if (dragStart != null && dragEnd != null && dragStart !== dragEnd) {
      const a = Math.min(dragStart, dragEnd);
      const b = Math.max(dragStart, dragEnd);
      return { x1: data[a]?.t, x2: data[b]?.t };
    }
    if (selectedRange) {
      return {
        x1: data[selectedRange.startIndex]?.t,
        x2: data[selectedRange.endIndex]?.t,
      };
    }
    return null;
  })();

  return (
    <div
      ref={wrapperRef}
      onMouseDown={selectable ? onWrapperMouseDown : undefined}
      style={
        selectable
          ? { cursor: 'crosshair', userSelect: 'none', width: '100%', height }
          : { width: '100%', height }
      }
    >
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart
        data={data}
        margin={{ top: 6, right: CHART_RIGHT_OFFSET, bottom: showAxis ? 0 : 0, left: 0 }}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.45} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="t"
          ticks={xTicks}
          tick={{ fontSize: 10, fill: 'currentColor', fillOpacity: 0.55, fontFamily: 'ui-monospace, monospace' }}
          tickLine={false}
          axisLine={{ stroke: GRID, strokeOpacity: 0.25 }}
          minTickGap={20}
          hide={!showAxis}
          interval="preserveStartEnd"
        />
        <YAxis
          width={36}
          tick={{ fontSize: 10, fill: 'currentColor', fillOpacity: 0.55, fontFamily: 'ui-monospace, monospace' }}
          tickLine={false}
          axisLine={false}
          tickFormatter={format}
          allowDecimals={false}
          domain={[0, 'auto']}
        />
        <Tooltip
          content={<ChartTooltip format={format} />}
          cursor={{ stroke: color, strokeOpacity: 0.4, strokeWidth: 1 }}
        />
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={2}
          fill={`url(#${gradId})`}
          isAnimationActive={false}
          activeDot={{ r: 4, strokeWidth: 1.5, stroke: '#fff' }}
        />
        {selectable && overlay && overlay.x1 != null && overlay.x2 != null && (
          <ReferenceArea
            x1={overlay.x1}
            x2={overlay.x2}
            strokeOpacity={0.3}
            stroke={color}
            fill={color}
            fillOpacity={0.15}
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
    </div>
  );
}

// ───────────────────────────── MultiLineChart ───────────────────────────

interface SeriesEntry {
  key: string;
  label: string;
  values: number[];
  color: string;
}

interface MultiLineChartProps {
  series: SeriesEntry[];
  labels?: string[];
  height?: number;
  showLegend?: boolean;
  format?: (n: number) => string;
}

export function MultiLineChart({
  series,
  labels,
  height = 220,
  showLegend = true,
  format = formatDefault,
}: MultiLineChartProps) {
  const len = useMemo(
    () => Math.max(0, ...series.map((s) => s.values.length)),
    [series]
  );

  const data = useMemo(() => {
    const rows: Record<string, number | string>[] = [];
    for (let i = 0; i < len; i++) {
      const row: Record<string, number | string> = { t: labels?.[i] ?? String(i) };
      for (const s of series) row[s.key] = s.values[i] ?? 0;
      rows.push(row);
    }
    return rows;
  }, [series, labels, len]);

  const xTicks = useMemo(() => tickEvery(data.map((d) => d.t as string), 6), [data]);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="t"
          ticks={xTicks}
          tick={{ fontSize: 10, fill: 'currentColor', fillOpacity: 0.55, fontFamily: 'ui-monospace, monospace' }}
          tickLine={false}
          axisLine={{ stroke: GRID, strokeOpacity: 0.25 }}
          minTickGap={20}
          interval="preserveStartEnd"
        />
        <YAxis
          width={36}
          tick={{ fontSize: 10, fill: 'currentColor', fillOpacity: 0.55, fontFamily: 'ui-monospace, monospace' }}
          tickLine={false}
          axisLine={false}
          tickFormatter={format}
          allowDecimals={false}
          domain={[0, 'auto']}
        />
        <Tooltip
          content={<ChartTooltip format={format} />}
          cursor={{ stroke: GRID, strokeOpacity: 0.5, strokeDasharray: '3 3' }}
        />
        {showLegend && (
          <Legend
            wrapperStyle={{ fontSize: 11, paddingTop: 6 }}
            iconType="plainline"
            iconSize={12}
          />
        )}
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 1.5, stroke: '#fff' }}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

// ──────────────────────────── StackedAreaChart ──────────────────────────

interface StackedAreaChartProps {
  series: SeriesEntry[];
  labels?: string[];
  height?: number;
  showLegend?: boolean;
}

export function StackedAreaChart({
  series,
  labels,
  height = 220,
  showLegend = true,
}: StackedAreaChartProps) {
  const len = useMemo(
    () => Math.max(0, ...series.map((s) => s.values.length)),
    [series]
  );

  const data = useMemo(() => {
    const rows: Record<string, number | string>[] = [];
    for (let i = 0; i < len; i++) {
      const row: Record<string, number | string> = { t: labels?.[i] ?? String(i) };
      for (const s of series) row[s.key] = s.values[i] ?? 0;
      rows.push(row);
    }
    return rows;
  }, [series, labels, len]);

  const xTicks = useMemo(() => tickEvery(data.map((d) => d.t as string), 6), [data]);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <defs>
          {series.map((s) => (
            <linearGradient id={`stack-${s.key}`} key={s.key} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.7} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0.15} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke={GRID} strokeOpacity={0.15} vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="t"
          ticks={xTicks}
          tick={{ fontSize: 10, fill: 'currentColor', fillOpacity: 0.55, fontFamily: 'ui-monospace, monospace' }}
          tickLine={false}
          axisLine={{ stroke: GRID, strokeOpacity: 0.25 }}
          minTickGap={20}
          interval="preserveStartEnd"
        />
        <YAxis
          width={36}
          tick={{ fontSize: 10, fill: 'currentColor', fillOpacity: 0.55, fontFamily: 'ui-monospace, monospace' }}
          tickLine={false}
          axisLine={false}
          tickFormatter={formatDefault}
          allowDecimals={false}
        />
        <Tooltip
          content={<ChartTooltip format={formatDefault} />}
          cursor={{ stroke: GRID, strokeOpacity: 0.5, strokeDasharray: '3 3' }}
        />
        {showLegend && (
          <Legend
            wrapperStyle={{ fontSize: 11, paddingTop: 6 }}
            iconType="square"
            iconSize={10}
          />
        )}
        {series.map((s) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            strokeWidth={1.4}
            fill={`url(#stack-${s.key})`}
            stackId="1"
            isAnimationActive={false}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

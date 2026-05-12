/**
 * Area chart with click-and-drag range selection inside the chart area.
 *
 * Uses ECharts' `brush` component with `lineX` (vertical band).
 * `takeGlobalCursor` is dispatched on chart-ready and after every data
 * tick so dragging keeps working across live refreshes.
 *
 *   <EChartsRangeArea points labels color height
 *                     selectedRange onRangeSelect />
 */

import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  BrushComponent,
  GridComponent,
  MarkLineComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactECharts from 'echarts-for-react/lib/core';

// ECharts tree-shaken build: every component referenced from `option`
// MUST be registered here. The chart uses `brush.toolbox: [...]` to
// expose the lineX brush + clear buttons, which is technically the
// toolbox component (the brush component owns the brushing behaviour
// but the toolbox component owns the button strip that selects the
// brush mode). Without ToolboxComponent the chart still renders but
// emits a console warning on every mount: "[ECharts] Component
// toolbox is used but not imported."
echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  BrushComponent,
  ToolboxComponent,
  VisualMapComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

interface Props {
  points: number[];
  labels?: string[];
  color?: string;
  height?: number;
  /** Inclusive bucket-index range currently selected, or null for full range. */
  selectedRange?: { startIndex: number; endIndex: number } | null;
  /** Fired after a brush gesture commits. */
  onRangeSelect?: (range: { startIndex: number; endIndex: number }) => void;
  /** Transient visual highlight overlay — paints a markArea band at
   *  the given index range with the given colour. Used by the
   *  per-broadcast contribution strip to blink "this is the slice
   *  that broadcast covered" without changing chart state. The parent
   *  is responsible for clearing it after the blink timeout. */
   highlightRange?: {
    startIndex: number;
    endIndex: number;
    color?: string;
  } | null;
  /** Persistent coloured bands on the chart — used by day-aggregate
   *  view to visually segment each broadcast's slice with its strip-
   *  pill colour. Drawn UNDER the line/area so the trend stays
   *  readable; opacity is intentionally low. */
  bands?: Array<{
    startIndex: number;
    endIndex: number;
    color: string;
    label?: string;
  }>;
}

interface BrushArea {
  brushType?: string;
  coordRange?: number[];
  coordRanges?: number[][];
  range?: number[];
}
interface BrushEndParams {
  type?: string;
  areas?: BrushArea[];
}

export function EChartsRangeArea({
  points,
  labels,
  color = '#f59e0b',
  height = 180,
  selectedRange = null,
  onRangeSelect,
  highlightRange = null,
  bands,
}: Props) {
  // ECharts-for-react handles the async init lifecycle for us when we
  // pass events via `onEvents`. We still keep a ref so we can call
  // dispatchAction (cursor activation, programmatic brush set/clear).
  const ref = useRef<{ getEchartsInstance?: () => echarts.ECharts } | null>(null);

  // Latest callback / data length in refs so the brushEnd handler
  // (rebound by `onEvents` on every render) always sees fresh values.
  const onRangeSelectRef = useRef(onRangeSelect);
  const pointsLenRef = useRef(points.length);
  useEffect(() => {
    onRangeSelectRef.current = onRangeSelect;
    pointsLenRef.current = points.length;
  });

  // markArea now carries ONLY the transient blink highlight. The
  // persistent per-broadcast colours are driven by visualMap below
  // (which actually colours the line + area, not just a backdrop).
  const markAreaData = useMemo(() => {
    if (!highlightRange) return undefined;
    const lbls = labels ?? points.map((_, i) => String(i));
    if (lbls.length === 0) return undefined;
    const clamp = (n: number) =>
      Math.max(0, Math.min(lbls.length - 1, n));
    const a = clamp(highlightRange.startIndex);
    const b = clamp(highlightRange.endIndex);
    if (b < a) return undefined;
    const tone = highlightRange.color ?? '#0ea5e9';
    return {
      silent: true,
      data: [
        [
          {
            xAxis: lbls[a] ?? String(a),
            itemStyle: {
              color: tone + '55',
              borderColor: tone,
              borderWidth: 1,
            },
          },
          { xAxis: lbls[b] ?? String(b) },
        ],
      ],
    };
  }, [highlightRange, labels, points]);

  const hasBands = !!(bands && bands.length > 0);

  // Dashed vertical boundary markers at each broadcast's start and
  // end indices. Used in day-aggregate mode so the colour transitions
  // are visually anchored — without these, the visualMap can blend
  // adjacent pieces if they touch and the eye loses where one ends
  // and the next begins.
  const markLineData = useMemo(() => {
    if (!hasBands || !bands) return undefined;
    const lbls = labels ?? points.map((_, i) => String(i));
    if (lbls.length === 0) return undefined;
    const clamp = (n: number) =>
      Math.max(0, Math.min(lbls.length - 1, n));
    const items: Array<Record<string, unknown>> = [];
    for (const band of bands) {
      const a = clamp(band.startIndex);
      const b = clamp(band.endIndex);
      if (b < a) continue;
      const lineStyle = {
        color: band.color,
        type: 'dotted' as const,
        width: 1.5,
        opacity: 0.85,
      };
      items.push({ xAxis: lbls[a] ?? String(a), lineStyle });
      items.push({ xAxis: lbls[b] ?? String(b), lineStyle });
    }
    return {
      symbol: 'none' as const,
      silent: true,
      label: { show: false },
      data: items,
    };
  }, [bands, hasBands, labels, points]);

  // Per-broadcast colour pieces for visualMap. `dimension: 0` means
  // ECharts uses each datum's x-index to pick a piece; line + area
  // colour switch on every transition. When no bands are supplied
  // we still emit a single piece covering the entire range in the
  // default colour — that way ECharts always has a valid visualMap
  // and toggling between modes doesn't get stuck on a stale config.
  const visualMapConfig = useMemo(() => {
    const lastIdx = Math.max(0, points.length - 1);
    const pieces =
      hasBands && bands
        ? bands.map((band) => ({
            gte: Math.max(0, band.startIndex),
            lte: Math.min(lastIdx, band.endIndex),
            color: band.color,
          }))
        : [{ gte: 0, lte: lastIdx, color }];
    return {
      type: 'piecewise' as const,
      show: false,
      dimension: 0,
      seriesIndex: 0,
      pieces,
      // Anything not covered by a piece (gaps between broadcasts in
      // band mode) falls back to a neutral grey so it doesn't
      // randomly use the last piece's colour.
      outOfRange: { color: '#9ca3af' },
    };
  }, [bands, hasBands, points.length, color]);

  const option = useMemo(
    () => ({
      grid: { top: 12, right: 12, bottom: 28, left: 50 },
      xAxis: {
        type: 'category',
        data: labels ?? points.map((_, i) => String(i)),
        axisLine: { lineStyle: { color: '#9ca3af', opacity: 0.4 } },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, color: '#6b7280', fontFamily: 'ui-monospace, monospace' },
        boundaryGap: false,
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, color: '#6b7280', fontFamily: 'ui-monospace, monospace' },
        splitLine: { lineStyle: { color: '#9ca3af', opacity: 0.15, type: 'dashed' } },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(255,255,255,0.95)',
        borderColor: '#e5e7eb',
        textStyle: { fontSize: 11, color: '#374151' },
      },
      visualMap: visualMapConfig,
      brush: {
        toolbox: ['lineX', 'clear'],
        xAxisIndex: 0,
        brushType: 'lineX',
        brushMode: 'single',
        brushStyle: {
          color: color + '26',
          borderColor: color,
          borderWidth: 1,
        },
        throttleType: 'debounce',
        throttleDelay: 300,
        outOfBrush: { colorAlpha: 0.55 },
        // `transformable: true` would make clicking inside an existing
        // band MOVE it instead of starting a new selection — unwanted.
        transformable: false,
        removeOnClick: false,
      },
      series: [
        {
          type: 'line',
          data: points,
          smooth: true,
          showSymbol: false,
          symbol: 'circle',
          symbolSize: 6,
          // No explicit lineStyle.color — visualMap drives it per
          // piece. Width set here so visualMap doesn't reset it.
          lineStyle: { width: 2 },
          // areaStyle uses opacity only; visualMap fills the colour
          // per piece so the area beneath the line matches the
          // broadcast it belongs to.
          areaStyle: { opacity: hasBands ? 0.25 : 0.45 },
          ...(markAreaData ? { markArea: markAreaData } : {}),
          ...(markLineData ? { markLine: markLineData } : {}),
          emphasis: { focus: 'series' },
          animation: false,
        },
      ],
    }),
    [points, labels, color, markAreaData, markLineData, hasBands, visualMapConfig],
  );

  // Whenever ECharts merges in a new option (data tick, bands change,
  // visualMap update, etc.), the brush "active cursor" mode silently
  // drops back to none and the user can no longer click-and-drag. Re-
  // arm it on every option change so dragging always works. We also
  // wipe any previous brush band because its pixel coords no longer
  // correspond to the same time labels after a data refresh.
  useEffect(() => {
    const inst = ref.current?.getEchartsInstance?.();
    if (!inst) return;
    inst.dispatchAction({ type: 'brush', areas: [] });
    inst.dispatchAction({
      type: 'takeGlobalCursor',
      key: 'brush',
      brushOption: { brushType: 'lineX', brushMode: 'single' },
    });
  }, [option]);

  // Clear the chart's brush only when external state explicitly resets
  // it. We DO NOT mirror an active selectedRange back into the chart —
  // that caused brushes drawn by the user to be reset/overwritten while
  // the round-trip happened (parent re-renders with the same indices,
  // we redispatch, ECharts re-renders, sometimes losing the selection).
  // The chart already shows the band from the user's own drag; trust it.
  useEffect(() => {
    if (selectedRange !== null) return;
    const inst = ref.current?.getEchartsInstance?.();
    if (!inst) return;
    inst.dispatchAction({ type: 'brush', areas: [] });
    inst.dispatchAction({
      type: 'takeGlobalCursor',
      key: 'brush',
      brushOption: { brushType: 'lineX', brushMode: 'single' },
    });
  }, [selectedRange]);

  // First-mount activation. `onChartReady` fires AFTER the (async) init
  // completes, so this is the earliest we can dispatch actions safely.
  const onChartReady = (raw: unknown) => {
    const inst = raw as echarts.ECharts;
    inst.dispatchAction({
      type: 'takeGlobalCursor',
      key: 'brush',
      brushOption: { brushType: 'lineX', brushMode: 'single' },
    });
  };

  // Use the wrapper's `onEvents` prop instead of inst.on() inside an
  // effect — the wrapper handles the async chart-init lifecycle and
  // re-binds on every prop change.
  // NOTE: ECharts on a `category` xAxis runs `coordRange` through
  // `OrdinalScale.scale` which **rounds to the nearest integer index**
  // before we even see it. So the values in `coordRange` are already
  // integers (no fractional positions). Math.round is a safety net.
  // For finer-grained control we fall back to converting `area.range`
  // (pixel coords) via `convertFromPixel`, which the OrdinalScale's
  // round trip can otherwise hide one full bucket from us at the edges.
  const onEvents = useMemo(
    () => ({
      brushEnd: (params: unknown, instance?: unknown) => {
        const p = params as BrushEndParams;
        const area = p.areas?.[0];
        if (!area) return;

        // Strategy 1: prefer coordRange (already mapped to data indices).
        let a: number | null = null;
        let b: number | null = null;
        const cr = area.coordRange ?? area.coordRanges?.[0];
        if (cr && cr.length >= 2) {
          a = Math.round(Number(cr[0]));
          b = Math.round(Number(cr[1]));
        }

        // Strategy 2: pixel range → indices via the chart instance.
        // Used when coordRange is missing OR when we want unrounded
        // fractional indices (more accurate at small zoom).
        if (
          (a === null || b === null || !Number.isFinite(a) || !Number.isFinite(b)) &&
          instance &&
          area.range &&
          area.range.length >= 2
        ) {
          const inst = instance as echarts.ECharts;
          try {
            const da = inst.convertFromPixel({ xAxisIndex: 0 }, [
              area.range[0],
              0,
            ]);
            const db = inst.convertFromPixel({ xAxisIndex: 0 }, [
              area.range[1],
              0,
            ]);
            if (Array.isArray(da) && Array.isArray(db)) {
              a = Math.round(Number(da[0]));
              b = Math.round(Number(db[0]));
            }
          } catch {
            /* fall through */
          }
        }

        if (
          a === null ||
          b === null ||
          !Number.isFinite(a) ||
          !Number.isFinite(b)
        ) {
          // eslint-disable-next-line no-console
          console.warn('[brushEnd] unable to derive indices from', area);
          return;
        }
        if (Math.abs(b - a) < 1) return; // misclick

        const n = pointsLenRef.current || 1;
        const startIndex = Math.max(0, Math.min(n - 1, Math.min(a, b)));
        const endIndex = Math.max(0, Math.min(n - 1, Math.max(a, b)));
        // eslint-disable-next-line no-console
        console.log('[brushEnd]', {
          rawCoordRange: cr,
          rawPixelRange: area.range,
          computed: { a, b },
          committed: { startIndex, endIndex },
          n,
        });
        onRangeSelectRef.current?.({ startIndex, endIndex });
      },
    }),
    [],
  );

  return (
    <ReactECharts
      ref={ref as never}
      echarts={echarts}
      option={option}
      style={{ height, width: '100%' }}
      notMerge={false}
      lazyUpdate={false}
      onChartReady={onChartReady}
      onEvents={onEvents}
    />
  );
}

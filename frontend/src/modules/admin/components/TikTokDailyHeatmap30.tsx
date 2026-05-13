import { Fragment, useMemo } from 'react';

/** Compact-number formatter used inside each cell. Inlined because
 *  no shared util exists yet; the other consumers in this module
 *  each carry their own copy. */
function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}

/** Shared 30-day calendar heatmap, calendar orientation.
 *
 *  7 columns (Sun → Sat) × ~5 week rows. Visual treatment mirrors the
 *  live-page `TikTokLiveCalendar` ("Live activity — last 30 days"):
 *  sky-blue ramp, dashed-border placeholders for out-of-window slots
 *  at the top-left and bottom-right corners, and a left-gutter month
 *  label per row when the month changes. Pure CSS — no chart library.
 *
 *  Used by:
 *   - `TikTokCommonGifterDetailModal` (Profile tab): rolls up the
 *     viewer's cross-host daily series.
 *   - `TikTokGifterModal` (Current tab → Timeline): scoped to the
 *     current host's per-day series.
 *
 *  Input is intentionally the smallest possible shape — just
 *  `{day: 'YYYY-MM-DD', diamonds: number}` rows. Sparse OK; days
 *  outside the array render as zero-intensity cells. */
export function TikTokDailyHeatmap30({
  points,
}: {
  points: Array<{ day: string; diamonds: number }>;
}) {
  const WINDOW_DAYS = 30;

  const { weekRows, rowLabels, maxDayTotal } = useMemo(() => {
    const totalByDay = new Map<string, number>();
    for (const p of points) {
      const day = p.day?.slice(0, 10);
      if (!day) continue;
      totalByDay.set(day, (totalByDay.get(day) ?? 0) + (p.diamonds || 0));
    }
    // Anchor: midnight of "today" in browser-local zone, then step
    // through calendar dates as a fake-UTC Date (just a date bag —
    // we never call toISOString on it).
    const now = new Date();
    const todayAnchor = new Date(Date.UTC(
      now.getFullYear(), now.getMonth(), now.getDate(),
    ));
    const windowStart = new Date(todayAnchor);
    windowStart.setUTCDate(todayAnchor.getUTCDate() - (WINDOW_DAYS - 1));
    const gridStart = new Date(windowStart);
    gridStart.setUTCDate(windowStart.getUTCDate() - windowStart.getUTCDay());
    const gridEnd = new Date(todayAnchor);
    gridEnd.setUTCDate(todayAnchor.getUTCDate() + (6 - todayAnchor.getUTCDay()));
    const totalCells =
      Math.round((gridEnd.getTime() - gridStart.getTime()) / 86_400_000) + 1;
    const totalRows = Math.ceil(totalCells / 7);
    type Cell = { key: string; total: number; date: Date } | null;
    const rows: Cell[][] = [];
    let max = 0;
    for (let r = 0; r < totalRows; r++) {
      const row: Cell[] = [];
      for (let c = 0; c < 7; c++) {
        const d = new Date(gridStart);
        d.setUTCDate(gridStart.getUTCDate() + r * 7 + c);
        if (d < windowStart || d > todayAnchor) {
          row.push(null);
          continue;
        }
        const y = d.getUTCFullYear();
        const m = String(d.getUTCMonth() + 1).padStart(2, '0');
        const dd = String(d.getUTCDate()).padStart(2, '0');
        const key = `${y}-${m}-${dd}`;
        const total = totalByDay.get(key) ?? 0;
        if (total > max) max = total;
        row.push({ key, total, date: new Date(d) });
      }
      rows.push(row);
    }
    const fmtMonth = new Intl.DateTimeFormat(undefined, { month: 'long' });
    const labels: string[] = [];
    let prevMonth = -1;
    for (const row of rows) {
      const firstReal = row.find((x): x is NonNullable<typeof x> => x !== null);
      const monthIdx = firstReal ? firstReal.date.getUTCMonth() : -1;
      if (firstReal && monthIdx !== prevMonth) {
        labels.push(fmtMonth.format(firstReal.date));
        prevMonth = monthIdx;
      } else {
        labels.push('');
      }
    }
    return { weekRows: rows, rowLabels: labels, maxDayTotal: max };
  }, [points]);

  if (maxDayTotal === 0) {
    return (
      <div className="text-[11px] font-mono text-gray-500 py-6 text-center">
        No gifting activity in the last 30 days.
      </div>
    );
  }

  // Sky-blue ramp, matching the live-page calendar.
  const LEVEL_COLOR = [
    'bg-gray-100 dark:bg-white/[0.04]',
    'bg-sky-100 dark:bg-sky-500/[0.20]',
    'bg-sky-300 dark:bg-sky-500/[0.45]',
    'bg-sky-500 dark:bg-sky-500/[0.75]',
    'bg-sky-700 dark:bg-sky-400',
  ];
  const levelFor = (d: number): number => {
    if (d <= 0) return 0;
    const ratio = Math.sqrt(d / maxDayTotal);
    if (ratio >= 0.8) return 4;
    if (ratio >= 0.55) return 3;
    if (ratio >= 0.3) return 2;
    return 1;
  };

  const WEEKDAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  return (
    <div>
      {/* Calendar layout: 7 weekday columns × N week rows. Fixed cell
          height (not 1fr) because this component is dropped into
          modal panels with no bounded vertical slot — letting cells
          stretch ballooned the heatmap downstream of every other
          panel. Keeping a compact band reads naturally in both modal
          and panel contexts. */}
      <div
        className="grid gap-[2px] w-full"
        style={{ gridTemplateColumns: `auto repeat(7, minmax(0, 1fr))` }}
      >
        <div />
        {WEEKDAY_SHORT.map((dayName) => (
          <div
            key={dayName}
            className="text-[9px] font-mono text-gray-500 tabular-nums text-center leading-none"
          >
            {dayName}
          </div>
        ))}
        {weekRows.map((row, ri) => (
          <Fragment key={ri}>
            <div className="text-[10px] font-mono text-gray-600 self-center pr-2 text-right leading-none whitespace-nowrap">
              {rowLabels[ri]}
            </div>
            {row.map((cell, ci) => {
              if (!cell) {
                return (
                  <div
                    key={ci}
                    className="h-7 rounded-[2px] border border-dashed border-gray-300/70 dark:border-white/15"
                    aria-hidden
                  />
                );
              }
              const lvl = levelFor(cell.total);
              const textTone = lvl >= 3
                ? 'text-sky-50 dark:text-sky-50'
                : 'text-gray-700';
              return (
                <div
                  key={ci}
                  className={
                    `h-7 min-w-0 rounded-[2px] border border-gray-200/60 dark:border-white/10 ${LEVEL_COLOR[lvl]} ` +
                    `flex items-center justify-center text-[10px] font-mono tabular-nums leading-none overflow-hidden ${textTone}`
                  }
                  title={`${cell.key} · ${cell.total.toLocaleString()} 💎`}
                >
                  {cell.total > 0 ? compactCount(cell.total) : ''}
                </div>
              );
            })}
          </Fragment>
        ))}
      </div>
      <div className="flex items-center gap-1.5 text-[10px] font-mono text-gray-500 mt-2 select-none">
        <span>less</span>
        {LEVEL_COLOR.map((c, i) => (
          <span
            key={i}
            className={`w-3 h-3 rounded-[2px] ${c} border border-gray-200/60 dark:border-white/10`}
          />
        ))}
        <span>more</span>
      </div>
    </div>
  );
}

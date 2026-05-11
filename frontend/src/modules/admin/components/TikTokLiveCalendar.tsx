import { useEffect, useMemo, useState } from 'react';
import { Calendar as CalendarIcon } from 'lucide-react';

import { tiktokApi, type TikTokRoom } from '@admin/services/tiktok';
import {
  useTikTokTimezone,
  dateKeyInZone,
} from '@admin/contexts/TikTokTimezoneContext';

interface Props {
  handle: string;
  /** Default 26 weeks ≈ ~6 months. The backend snaps the start to the
   *  previous Monday so the grid is rectangular (7 × N). */
  weeks?: number;
  /** Same room list the parent page already loaded for the broadcast
   *  selector dropdown — passed in so we can map a clicked calendar
   *  day to the actual room_id without a second backend call. */
  rooms?: TikTokRoom[];
  /** Fires when a day with broadcasts is clicked. The full list of
   *  rooms for that day is passed up (sorted newest → oldest). The
   *  parent decides:
   *    - 1 room  → switch directly to it
   *    - N rooms → present a picker so the user explicitly chooses
   *  This avoids silently aggregating multiple rooms into a single-
   *  room view (which made the chart look truncated to one of N
   *  broadcasts, exactly the bug you noticed on `electra504de_yady`). */
  onSelectDay?: (rooms: TikTokRoom[], date: string) => void;
}

interface CalendarData {
  start_date: string;
  end_date: string;
  weeks: number;
  byDate: Map<
    string,
    {
      rooms: number;
      duration_minutes: number;
      diamonds: number;
      matches: number;
    }
  >;
}

/** GitHub-style heatmap of the days a creator went live.
 *
 * Columns = weeks (oldest → newest, left → right).
 * Rows    = day-of-week (Mon top → Sun bottom).
 *
 * Cell colour = number of distinct broadcasts on that day. Hover shows
 * the date, broadcast count, and total observed duration.
 */
export function TikTokLiveCalendar({
  handle,
  weeks = 26,
  rooms,
  onSelectDay,
}: Props) {
  const { tz } = useTikTokTimezone();
  const [data, setData] = useState<CalendarData | null>(null);
  const [loading, setLoading] = useState(false);
  // Currently-hovered cell. Stores the cell's bounding rect so the
  // popover can anchor next to the cell rather than chase the mouse.
  // Replaces the native `title` (laggy, no visual hover, single-line)
  // with a real positioned tooltip.
  const [hovered, setHovered] = useState<{
    key: string;
    label: string;
    rooms: number;
    duration_minutes: number;
    diamonds: number;
    matches: number;
    isFuture: boolean;
    rect: { top: number; left: number; bottom: number; right: number };
  } | null>(null);

  useEffect(() => {
    if (!handle) return;
    let cancelled = false;
    setLoading(true);
    tiktokApi
      .getHostCalendar(handle, weeks, tz)
      .then((res) => {
        if (cancelled) return;
        const map = new Map<
          string,
          {
            rooms: number;
            duration_minutes: number;
            diamonds: number;
            matches: number;
          }
        >();
        for (const c of res.cells) {
          map.set(c.date, {
            rooms: c.rooms,
            duration_minutes: c.duration_minutes,
            diamonds: c.diamonds,
            matches: c.matches,
          });
        }
        setData({
          start_date: res.start_date,
          end_date: res.end_date,
          weeks: res.weeks,
          byDate: map,
        });
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [handle, weeks, tz]);

  // Map: local-date YYYY-MM-DD → all rooms started on that day
  // (sorted newest → oldest). Click handler emits the full list so
  // the parent can present a picker when N>1 — the previous
  // "silently jump to the most active" picked one room out of N
  // and made the chart look truncated.
  const roomsByDate = useMemo(() => {
    const map = new Map<string, TikTokRoom[]>();
    if (!rooms || rooms.length === 0) return map;
    for (const r of rooms) {
      if (!r.first_seen_at) continue;
      // Bucket by overlap: a broadcast that ran from 23:55 May 6
      // to 02:00 May 7 (in zone) appears in BOTH May 6 and May 7
      // cells, so the day-aggregate view of either day surfaces
      // it. Walk from the start-day key through the end-day key
      // and add the room to each.
      const startKey = dateKeyInZone(r.first_seen_at, tz);
      const endIso = r.ended_at ?? r.last_seen_at ?? r.first_seen_at;
      const endKey = dateKeyInZone(endIso ?? r.first_seen_at, tz);
      // Iterate calendar dates inclusively. Walking by 24h on a UTC
      // base and re-keying with the zone gives the right sequence
      // even across DST transitions.
      const startMs = Date.parse(`${startKey}T00:00:00Z`);
      const endMs = Date.parse(`${endKey}T00:00:00Z`);
      let cursor = startMs;
      let safety = 0;
      while (cursor <= endMs && safety < 32) {
        const cursorKey = new Date(cursor).toISOString().slice(0, 10);
        const arr = map.get(cursorKey) ?? [];
        // Avoid double-pushing the same room into the same key.
        if (arr[arr.length - 1] !== r) arr.push(r);
        map.set(cursorKey, arr);
        cursor += 86_400_000;
        safety += 1;
      }
    }
    map.forEach((arr) => {
      arr.sort((a, b) => {
        const ta = a.first_seen_at ? new Date(a.first_seen_at).getTime() : 0;
        const tb = b.first_seen_at ? new Date(b.first_seen_at).getTime() : 0;
        return tb - ta;
      });
    });
    return map;
  }, [rooms, tz]);

  // Pre-compute the (week, day) grid the chart will render.
  // Walk from the snapped start (Monday `weeks*7` ago) UP TO end_date
  // (today) — `data.weeks` is just the requested window length, not
  // the column count. Today usually lands mid-week, so the actual
  // grid often needs `weeks + 1` columns to keep today visible.
  const grid = useMemo(() => {
    if (!data) return null;
    const start = parseDate(data.start_date);
    const end = parseDate(data.end_date);
    const days: Date[][] = [];
    let cursor = new Date(start);
    while (cursor <= end) {
      const col: Date[] = [];
      for (let d = 0; d < 7; d += 1) {
        col.push(new Date(cursor));
        cursor.setDate(cursor.getDate() + 1);
      }
      days.push(col);
    }
    return days;
  }, [data]);

  // Active days + window-wide totals for the header strap.
  const summary = useMemo(() => {
    if (!data) {
      return {
        activeDays: 0,
        totalBroadcasts: 0,
        totalMinutes: 0,
        totalDiamonds: 0,
        totalMatches: 0,
      };
    }
    let activeDays = 0;
    let totalBroadcasts = 0;
    let totalMinutes = 0;
    let totalDiamonds = 0;
    let totalMatches = 0;
    data.byDate.forEach((v) => {
      activeDays += 1;
      totalBroadcasts += v.rooms;
      totalMinutes += v.duration_minutes;
      totalDiamonds += v.diamonds;
      totalMatches += v.matches;
    });
    return { activeDays, totalBroadcasts, totalMinutes, totalDiamonds, totalMatches };
  }, [data]);

  return (
    <section className="card flex flex-col gap-3 min-w-0">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="auth-mono-label flex items-center gap-1.5">
          <CalendarIcon className="w-3.5 h-3.5 text-emerald-500" />
          Live activity — last {weeks}w
        </h2>
        {data && (
          <span className="text-[11px] font-mono text-gray-500 tabular-nums">
            {summary.activeDays} day{summary.activeDays === 1 ? '' : 's'} ·{' '}
            {summary.totalBroadcasts} broadcast{summary.totalBroadcasts === 1 ? '' : 's'}
            {summary.totalMinutes > 0 && ` · ${formatDuration(summary.totalMinutes)}`}
            {summary.totalDiamonds > 0 && ` · ${formatCount(summary.totalDiamonds)} 💎`}
            {summary.totalMatches > 0 && ` · ${summary.totalMatches} match${summary.totalMatches === 1 ? '' : 'es'}`}
          </span>
        )}
      </div>

      {loading && !data ? (
        <div className="text-xs text-gray-400 font-mono">Loading…</div>
      ) : !grid || !data ? (
        <div className="text-xs text-gray-400 font-mono">No activity recorded.</div>
      ) : (
        <div>
          {/* Month labels — one per column-group where the month changes.
              `weeks={13}` (default below) gives ~3 months at a glance,
              with 7-day rows and no horizontal scroll inside the
              360-px card. Each label sits above its first column. */}
          <div className="flex gap-0.5 mb-1 text-[9px] font-mono text-gray-400 select-none">
            <div className="w-7 shrink-0" aria-hidden />
            {grid.map((week, wi) => {
              const firstOfMonth = week.find((d) => d.getDate() <= 7);
              const showLabel =
                firstOfMonth &&
                (wi === 0 || firstOfMonth.getDate() <= 7);
              const prevWeekHasSameMonth =
                wi > 0 &&
                grid[wi - 1].some(
                  (d) =>
                    firstOfMonth && d.getMonth() === firstOfMonth.getMonth(),
                );
              return (
                <div key={wi} className="w-3.5 shrink-0">
                  {showLabel && !prevWeekHasSameMonth && firstOfMonth
                    ? MONTH_LABELS[firstOfMonth.getMonth()]
                    : ''}
                </div>
              );
            })}
          </div>

          {/* Day-of-week labels + 7×N grid. All seven labels visible
              now (we have the horizontal room since the grid was
              shrunk to 13 weeks). Cells are 14px so the column fits
              the page card without scrolling. */}
          <div className="flex gap-0.5">
            <div className="flex flex-col gap-0.5 mr-1 text-[9px] font-mono text-gray-400 select-none w-6 shrink-0">
              {DOW_LABELS.map((lbl, i) => (
                <div key={i} className="h-3.5 leading-[14px]">
                  {lbl}
                </div>
              ))}
            </div>
            <div className="flex gap-0.5">
              {grid.map((week, wi) => (
                <div key={wi} className="flex flex-col gap-0.5">
                  {week.map((d) => {
                    const key = isoDate(d);
                    const cell = data.byDate.get(key);
                    const count = cell?.rooms ?? 0;
                    const isFuture = d > new Date();
                    const bg = isFuture ? 'transparent' : countColor(count);
                    const isHovered = hovered?.key === key;
                    const open = (
                      target: HTMLElement,
                    ) => {
                      const r = target.getBoundingClientRect();
                      setHovered({
                        key,
                        label: formatLongDate(d),
                        rooms: cell?.rooms ?? 0,
                        duration_minutes: cell?.duration_minutes ?? 0,
                        diamonds: cell?.diamonds ?? 0,
                        matches: cell?.matches ?? 0,
                        isFuture,
                        rect: {
                          top: r.top, left: r.left,
                          bottom: r.bottom, right: r.right,
                        },
                      });
                    };
                    // Hover ring rendered as inline box-shadow so the
                    // contrast can't be diluted by Tailwind opacity
                    // helpers and the colour is consistent across
                    // emerald shades. Inner 1.5-px white halo +
                    // outer 2-px near-black ring → cell visibly
                    // "lifts" above its neighbours. `z-10` keeps the
                    // shadow from being clipped by the next cell's
                    // gap on either side.
                    const hoverShadow =
                      isHovered && !isFuture
                        ? '0 0 0 1.5px #ffffff, 0 0 0 3.5px rgba(15, 23, 42, 0.95)'
                        : 'none';
                    // Click only fires for days that have broadcasts
                    // we know about — gray (no-live) and future cells
                    // are click-inert.
                    const dayRooms = roomsByDate.get(key) ?? [];
                    const isClickable =
                      !isFuture && dayRooms.length > 0 && Boolean(onSelectDay);
                    return (
                      <div
                        key={key}
                        role={isClickable ? 'button' : undefined}
                        tabIndex={isClickable ? 0 : -1}
                        onMouseEnter={(e) => open(e.currentTarget)}
                        onMouseLeave={() => setHovered(null)}
                        onFocus={(e) => open(e.currentTarget)}
                        onBlur={() => setHovered(null)}
                        onClick={() => {
                          if (isClickable) onSelectDay?.(dayRooms, key);
                        }}
                        onKeyDown={(e) => {
                          if (
                            isClickable &&
                            (e.key === 'Enter' || e.key === ' ')
                          ) {
                            e.preventDefault();
                            onSelectDay?.(dayRooms, key);
                          }
                        }}
                        className={
                          'w-3.5 h-3.5 rounded-sm transition-shadow ' +
                          (isFuture
                            ? 'cursor-default'
                            : isClickable
                              ? 'cursor-pointer '
                              : 'cursor-default ') +
                          (isHovered ? 'relative z-10' : '')
                        }
                        style={{
                          backgroundColor: bg,
                          boxShadow: hoverShadow,
                        }}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* Legend — inline-styled so it stays in sync with the grid
              and isn't subject to Tailwind class-purge surprises. */}
          <div className="flex items-center gap-1.5 mt-2 text-[10px] font-mono text-gray-500 select-none">
            <span>less</span>
            {[0, 1, 2, 3, 4].map((n) => (
              <span
                key={n}
                className="w-3 h-3 rounded-sm"
                style={{ backgroundColor: countColor(n) }}
              />
            ))}
            <span>more</span>
          </div>
        </div>
      )}

      {/* Popover anchored to the hovered cell. `position: fixed` lets
          it escape the card's clipping; clamped against the viewport
          so it never falls off the right or bottom edge. The popover
          is `pointer-events-none` so a tooltip that happens to appear
          under the cursor doesn't trap mouseleave. */}
      {hovered && (
        <CellPopover hovered={hovered} />
      )}
    </section>
  );
}

function CellPopover({
  hovered,
}: {
  hovered: NonNullable<
    Parameters<typeof setCellPopoverPlaceholder>[0]
  >;
}) {
  // Default position: just below the cell, aligned to its left.
  // Fudge factors keep it visually close without overlapping the ring.
  const POP_W = 220;
  const POP_H = 64;
  const GAP = 8;
  let top = hovered.rect.bottom + GAP;
  let left = hovered.rect.left;
  if (typeof window !== 'undefined') {
    if (left + POP_W > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - POP_W - 8);
    }
    if (top + POP_H > window.innerHeight - 8) {
      top = hovered.rect.top - POP_H - GAP;
    }
  }
  return (
    <div
      role="tooltip"
      className="fixed z-[100] pointer-events-none rounded-md border border-gray-200 dark:border-gray-100/40 bg-white dark:bg-gray-100/15 shadow-lg px-2.5 py-1.5 text-[11px] font-mono leading-tight"
      style={{ top, left, minWidth: POP_W, maxWidth: 280 }}
    >
      <div className="text-gray-900 dark:text-gray-100 font-semibold">
        {hovered.label}
      </div>
      {hovered.isFuture ? (
        <div className="text-gray-400 mt-0.5">future date</div>
      ) : hovered.rooms === 0 ? (
        <div className="text-gray-400 mt-0.5">no live</div>
      ) : (
        <div className="mt-1 grid grid-cols-1 gap-0.5 text-gray-600 dark:text-gray-300 tabular-nums">
          <div>
            <span className="text-gray-400">broadcasts:</span>{' '}
            <span className="text-gray-900 dark:text-gray-100">
              {hovered.rooms}
            </span>
          </div>
          {hovered.duration_minutes > 0 && (
            <div>
              <span className="text-gray-400">⏱ time:</span>{' '}
              <span className="text-gray-900 dark:text-gray-100">
                {formatDuration(hovered.duration_minutes)}
              </span>
            </div>
          )}
          {hovered.diamonds > 0 && (
            <div>
              <span className="text-gray-400">💎 diamonds:</span>{' '}
              <span className="text-amber-700 dark:text-amber-300">
                {hovered.diamonds.toLocaleString()}
              </span>
            </div>
          )}
          {hovered.matches > 0 && (
            <div>
              <span className="text-gray-400">⚔ matches:</span>{' '}
              <span className="text-gray-900 dark:text-gray-100">
                {hovered.matches}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// TS helper that lets `CellPopover`'s prop type match the component's
// internal `hovered` shape without exporting a separate type.
function setCellPopoverPlaceholder(
  _v: {
    key: string;
    label: string;
    rooms: number;
    duration_minutes: number;
    diamonds: number;
    matches: number;
    isFuture: boolean;
    rect: { top: number; left: number; bottom: number; right: number };
  },
) {
  /* unused — typeof reference for the popover prop */
}

const DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH_LABELS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** GitHub-Contributions-style five-stop color ramp.
 *  Inline `style={{backgroundColor}}` is used in the markup rather
 *  than Tailwind utility classes so the values can't be silently
 *  dropped by the JIT purger when builds bundle the component. The
 *  tradeoff is no automatic dark-mode inversion — but the emerald
 *  ramp reads fine on both light and dark surfaces. */
function countColor(n: number): string {
  if (n <= 0) return 'rgb(229 231 235 / 0.7)'; // gray-200 @ 70%
  if (n === 1) return '#a7f3d0';               // emerald-200
  if (n === 2) return '#34d399';               // emerald-400
  if (n === 3) return '#10b981';               // emerald-500
  return '#047857';                            // emerald-700
}

function parseDate(s: string): Date {
  // The backend returns YYYY-MM-DD without timezone — interpret as local
  // midnight so the grid lines up with the viewer's calendar.
  const [y, m, d] = s.split('-').map((x) => Number(x));
  return new Date(y, (m || 1) - 1, d || 1);
}

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

/** Friendly long-form date, e.g. "Wednesday, May 7, 2026". */
function formatLongDate(d: Date): string {
  return d.toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

/** Compact count: 12,345 → 12.3k, 1,234,567 → 1.2M. Used for diamond
 *  totals where the raw number is too long for the tooltip line. */
function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h < 24) return m === 0 ? `${h}h` : `${h}h ${m}m`;
  const d = Math.floor(h / 24);
  const hh = h % 24;
  return hh === 0 ? `${d}d` : `${d}d ${hh}h`;
}

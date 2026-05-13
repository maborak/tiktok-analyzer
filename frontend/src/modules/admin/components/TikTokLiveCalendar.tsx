import { Fragment, useEffect, useMemo, useState } from 'react';
import { Calendar as CalendarIcon } from 'lucide-react';

import { type TikTokRoom } from '@admin/services/tiktok';
import { useTikTokApi } from '@admin/contexts/TikTokApiContext';
import {
  useTikTokTimezone,
  dateKeyInZone,
  partsInZone,
} from '@admin/contexts/TikTokTimezoneContext';

interface Props {
  handle: string;
  /** Default 5 weeks (~30 days, "last month") to match the rest of
   *  the modal's 30-day heatmap conventions. The backend snaps the
   *  start to the previous Monday so the grid is rectangular (7 × N);
   *  the frontend then renders a GitHub-style 7-row layout windowed
   *  to the trailing 30 calendar days (out-of-window cells stay
   *  blank). Callers wanting a longer span can override (e.g. for
   *  the host detail page). */
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
  /** Fires when the calendar data resolves (or is reset). The parent
   *  uses this to render the activity summary chip ("6 days · 10
   *  broadcasts · 1d 5h · 1.5M 💎 · 124 matches") inside the
   *  ProfileHeaderCard alongside the avatar — keeping the heatmap
   *  itself a clean grid without a header strap of stats. */
  onSummary?: (summary: TikTokLiveActivitySummary | null) => void;
}

export interface TikTokLiveActivitySummary {
  activeDays: number;
  totalBroadcasts: number;
  totalMinutes: number;
  totalDiamonds: number;
  totalMatches: number;
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
  weeks = 5,
  rooms,
  onSelectDay,
  onSummary,
}: Props) {
  const tiktokApi = useTikTokApi();
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

  // Window-wide totals derived from the same `byDate` map the grid
  // uses. The chip itself no longer renders here — it's emitted up
  // via `onSummary` so the parent can render it inside the
  // ProfileHeaderCard alongside the avatar (keeps this panel as a
  // pure heatmap, no header strap clutter).
  useEffect(() => {
    if (!onSummary) return;
    if (!data) {
      onSummary(null);
      return;
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
    onSummary({
      activeDays,
      totalBroadcasts,
      totalMinutes,
      totalDiamonds,
      totalMatches,
    });
  }, [data, onSummary]);

  return (
    <section className="card flex flex-col gap-3 min-w-0 h-full">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="auth-mono-label flex items-center gap-1.5">
          <CalendarIcon className="w-3.5 h-3.5 text-sky-500" />
          Live activity — last 30 days
        </h2>
      </div>

      {loading && !data ? (
        <div className="text-xs text-gray-400 font-mono">Loading…</div>
      ) : !data ? (
        <div className="text-xs text-gray-400 font-mono">No activity recorded.</div>
      ) : (
        <div className="flex-1 flex flex-col min-h-0">
          <RecentMonthGrid
            data={data}
            roomsByDate={roomsByDate}
            hovered={hovered}
            setHovered={setHovered}
            onSelectDay={onSelectDay}
            tz={tz}
          />
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

// ── GitHub-style 30-day grid ────────────────────────────────────────
//
// 7 rows (Sun → Sat) × ~5 week columns, anchored to today. Out-of-
// window cells (top-left + bottom-right) stay blank so the layout
// snaps to whole weeks. Color ramp matches the gifter-modal
// Timeline heatmap (`TikTokDailyHeatmap30`): gray for zero, then a
// 5-step amber ramp keyed off broadcast count. The cell shows the
// broadcast count when ≥ 1; tooltip + click behaviour preserved
// from the previous emerald 13-week grid.
type HoveredCell = NonNullable<
  Parameters<typeof setCellPopoverPlaceholder>[0]
>;

function RecentMonthGrid({
  data,
  roomsByDate,
  hovered,
  setHovered,
  onSelectDay,
  tz,
}: {
  data: CalendarData;
  roomsByDate: Map<string, TikTokRoom[]>;
  hovered: HoveredCell | null;
  setHovered: (h: HoveredCell | null) => void;
  onSelectDay?: (rooms: TikTokRoom[], date: string) => void;
  /** Active page timezone. The grid is built in this zone so cells
   *  line up with the backend's `cells[].date` keys (which the
   *  service buckets by `AT TIME ZONE :tz`). Without this the grid
   *  uses the browser's local zone, and a user whose local zone
   *  differs from the page zone sees cell highlights drifting by a
   *  day — and clicking a cell hands the parent a local-zone YMD
   *  that doesn't match what the rest of the page is filtering on. */
  tz: string;
}) {
  const WINDOW_DAYS = 30;
  const { weekRows, maxDayDiamonds } = useMemo(() => {
    // Calendar-style layout: 7 columns = days of week (Sun → Sat),
    // 4–5 rows = weeks. The grid is built in the ACTIVE page tz —
    // we anchor "today" via `partsInZone(now, tz)`, then walk
    // calendar dates in a fake-UTC Date (so .getUTCDay /
    // .setUTCDate operate on the tz's wall-clock calendar without
    // DST traps). The resulting YMD keys match the backend's
    // `cells[].date` bucketing, and the click handler hands the
    // parent a date string interpreted in the same zone the rest
    // of the page filters by.
    const todayParts = partsInZone(new Date(), tz);
    // Anchor: midnight of "today in tz", represented as a UTC Date
    // whose Y-M-D triplet matches the tz's wall-clock calendar.
    // We never call `toISOString()` on these — they're just date
    // bags for stepping through the calendar.
    const todayAnchor = new Date(Date.UTC(
      todayParts.year, todayParts.month - 1, todayParts.day,
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
    type Cell = { key: string; date: Date } | null;
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
        const entry = data.byDate.get(key);
        if (entry && entry.diamonds > max) max = entry.diamonds;
        row.push({ key, date: new Date(d) });
      }
      rows.push(row);
    }
    return { weekRows: rows, maxDayDiamonds: max };
  }, [data, tz]);

  // Row labels — show the month for the row's first in-window day,
  // and only when the month differs from the row above. Other rows
  // get blank labels so the column stays narrow.
  const rowLabels = useMemo(() => {
    const fmtMonth = new Intl.DateTimeFormat(undefined, {
      month: 'short', year: '2-digit',
    });
    const labels: string[] = [];
    let prevMonth = -1;
    for (const row of weekRows) {
      const firstReal = row.find((x): x is NonNullable<typeof x> => x !== null);
      const m = firstReal ? firstReal.date.getMonth() : -1;
      if (firstReal && m !== prevMonth) {
        labels.push(fmtMonth.format(firstReal.date));
        prevMonth = m;
      } else {
        labels.push('');
      }
    }
    return labels;
  }, [weekRows]);

  // Sky-blue ramp — cooler, more neutral than emerald, and reads
  // calmly against the warm amber of the gifter-modal Profile
  // heatmap so the two surfaces stay distinct.
  const LEVEL_COLOR = [
    'bg-gray-100 dark:bg-white/[0.04]',
    'bg-sky-100 dark:bg-sky-500/[0.20]',
    'bg-sky-300 dark:bg-sky-500/[0.45]',
    'bg-sky-500 dark:bg-sky-500/[0.75]',
    'bg-sky-700 dark:bg-sky-400',
  ];
  const levelFor = (d: number): number => {
    if (d <= 0) return 0;
    if (maxDayDiamonds <= 0) return 0;
    const ratio = Math.sqrt(d / maxDayDiamonds);
    if (ratio >= 0.8) return 4;
    if (ratio >= 0.55) return 3;
    if (ratio >= 0.3) return 2;
    return 1;
  };

  const WEEKDAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Calendar layout: 7 weekday columns × N week rows. Rows
          stretch to share the available card height via
          `gridTemplateRows: auto repeat(N, 1fr)`, so the band fills
          its sidebar slot end-to-end and visually matches the
          ProfileHeaderCard height beside it. */}
      <div
        className="grid gap-[2px] w-full flex-1 min-h-0"
        style={{
          gridTemplateColumns: `auto repeat(7, minmax(0, 1fr))`,
          gridTemplateRows: `auto repeat(${weekRows.length}, minmax(0, 1fr))`,
        }}
      >
        {/* Header row: weekday labels. */}
        <div />
        {WEEKDAY_SHORT.map((dayName) => (
          <div
            key={dayName}
            className="text-[9px] font-mono text-gray-500 tabular-nums text-center leading-none"
          >
            {dayName}
          </div>
        ))}
        {/* One row per week. */}
        {weekRows.map((row, ri) => (
          <Fragment key={ri}>
            <div className="text-[10px] font-mono text-gray-600 self-center pr-2 text-right leading-none">
              {rowLabels[ri]}
            </div>
            {row.map((cell, ci) => {
              if (!cell) {
                // Out-of-window slot: top-left corners before the
                // 30-day window starts, OR bottom-right corners
                // after today. Either way render a dashed-border
                // placeholder so the calendar grid stays visually
                // square even at the edges, distinct from in-window
                // zero-activity cells which carry a solid border.
                return (
                  <div
                    key={ci}
                    className="min-h-0 rounded-[2px] border border-dashed border-gray-300/70 dark:border-white/15"
                    aria-hidden
                  />
                );
              }
              const entry = data.byDate.get(cell.key);
              const diamonds = entry?.diamonds ?? 0;
              const lvl = levelFor(diamonds);
              const textTone = lvl >= 3
                ? 'text-sky-50 dark:text-sky-50'
                : 'text-gray-700';
              const dayRooms = roomsByDate.get(cell.key) ?? [];
              const isClickable = dayRooms.length > 0 && Boolean(onSelectDay);
              const isHovered = hovered?.key === cell.key;
              const open = (target: HTMLElement) => {
                const r = target.getBoundingClientRect();
                setHovered({
                  key: cell.key,
                  label: formatLongDate(cell.date),
                  rooms: entry?.rooms ?? 0,
                  duration_minutes: entry?.duration_minutes ?? 0,
                  diamonds: entry?.diamonds ?? 0,
                  matches: entry?.matches ?? 0,
                  isFuture: false,
                  rect: {
                    top: r.top, left: r.left,
                    bottom: r.bottom, right: r.right,
                  },
                });
              };
              return (
                <div
                  key={ci}
                  role={isClickable ? 'button' : undefined}
                  tabIndex={isClickable ? 0 : -1}
                  onMouseEnter={(e) => open(e.currentTarget)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={(e) => open(e.currentTarget)}
                  onBlur={() => setHovered(null)}
                  onClick={() => {
                    if (isClickable) onSelectDay?.(dayRooms, cell.key);
                  }}
                  onKeyDown={(e) => {
                    if (isClickable && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault();
                      onSelectDay?.(dayRooms, cell.key);
                    }
                  }}
                  className={
                    `min-h-0 min-w-0 rounded-[2px] border border-gray-200/60 dark:border-white/10 ${LEVEL_COLOR[lvl]} ` +
                    `flex items-center justify-center text-[10px] font-mono tabular-nums leading-none overflow-hidden ${textTone} ` +
                    (isClickable ? 'cursor-pointer' : 'cursor-default') +
                    (isHovered ? ' relative z-10' : '')
                  }
                  style={
                    isHovered
                      ? {
                          boxShadow:
                            '0 0 0 1.5px #ffffff, 0 0 0 3.5px rgba(15, 23, 42, 0.95)',
                        }
                      : undefined
                  }
                  aria-label={`${cell.key} · ${diamonds.toLocaleString()} 💎`}
                >
                  {diamonds > 0 ? formatCount(diamonds) : ''}
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

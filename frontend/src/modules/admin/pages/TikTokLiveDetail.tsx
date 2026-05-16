import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import {
  ArrowLeft,
  Bug,
  Clock,
  Crown,
  Gem,
  Heart,
  History,
  Loader2,
  Lock,
  MessageSquare,
  Radio,
  RefreshCw,
  Swords,
  User,
  X,
} from 'lucide-react'; // Crown is used below in LiveMatchTopDonors
import { Modal } from '@/components/ui/Modal';
import toast from 'react-hot-toast';
import * as echarts from 'echarts/core';
import { PieChart } from 'echarts/charts';
import { TooltipComponent as PieTooltipComponent } from 'echarts/components';
import { CanvasRenderer as PieCanvasRenderer } from 'echarts/renderers';
import ReactECharts from 'echarts-for-react/lib/core';

// Tree-shaken ECharts setup for the Top Gifters tab pie charts. The
// other modules (Worker Telemetry, Match Modal) register their own
// charts; ECharts dedupes registrations so multiple call sites are
// safe.
echarts.use([PieChart, PieTooltipComponent, PieCanvasRenderer]);

import { Button } from '@/components/ui/Button';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import {
  type TikTokGifter,
  type TikTokMatch,
  type TikTokMatchGiftersBySide,
  type TikTokMatchOpponent,
  type TikTokMatchSideGifter,
  type TikTokRoom,
  type TikTokRoomStats,
  type TikTokSubscription,
  type TikTokWsEvent,
  openTikTokWebSocket,
} from '@admin/services/tiktok';
import { MultiLineChart, eventColor } from '@admin/components/TikTokCharts';
import { EChartsRangeArea } from '@admin/components/EChartsRangeArea';
import { AnimatedScore } from '@admin/components/AnimatedScore';
import { SafeAvatar } from '@admin/components/SafeAvatar';
import { TikTokAddLiveModal } from '@admin/components/TikTokAddLiveModal';
import { TikTokGifterDetailModal } from '@admin/components/TikTokGifterDetailModal';
import { TikTokBroadcastSelector } from '@admin/components/TikTokBroadcastSelector';
import { TikTokRealtimeIndicator } from '@admin/components/TikTokRealtimeIndicator';
import { TikTokTimezonePill } from '@admin/components/TikTokTimezonePill';
import { TikTokMatchEventsModal } from '@admin/components/TikTokMatchEventsModal';
import { TikTokRoomCommentsTimeline } from '@admin/components/TikTokRoomCommentsTimeline';
import { TikTokRoomGiftersTable } from '@admin/components/TikTokRoomGiftersTable';
import { TikTokRoomCrossLiveGiftersTable } from '@admin/components/TikTokRoomCrossLiveGiftersTable';
import { TikTokRoomRecipientsCard } from '@admin/components/TikTokRoomRecipientsCard';
import { TikTokLiveCalendar } from '@admin/components/TikTokLiveCalendar';
import {
  TikTokTimezoneProvider,
  useTikTokTimezone,
  fmtHM,
  fmtShortDate,
  fmtMonthDayTime,
  fmtFull,
  partsInZone,
  zoneDayBoundsUtc,
} from '@admin/contexts/TikTokTimezoneContext';
import { useTikTokApi } from '@admin/contexts/TikTokApiContext';
import {
  TikTokRuntimeConfigProvider,
  useTikTokRuntimeConfig,
} from '@admin/contexts/TikTokRuntimeConfigContext';
import { TIMEZONE_OPTIONS } from '@admin/contexts/timezoneOptions';

/**
 * Window options. Two flavours:
 *   - kind: "rolling" — a sliding window ending at now (e.g. last 30 min).
 *   - kind: "broadcast" — full span of the selected room (start → end-or-now).
 *   - kind: "all" — no window filter; entire room history.
 *
 * Default: "broadcast" when the selected room has ended, "rolling 30 min"
 * when the room is still live (or its end is unknown).
 */
/** Time window applied to room stats. Default is the entire selected
 *  broadcast (since=room.first_seen_at, until=room.ended_at|last_seen_at).
 *  A "custom" window comes exclusively from a chart-brush range select —
 *  there is no preset dropdown anymore. */
type WindowOption =
  | { kind: 'broadcast'; label: string }
  | { kind: 'custom'; label: string; since: string; until: string };

const BROADCAST_WINDOW: WindowOption = {
  kind: 'broadcast',
  label: 'Entire broadcast',
};

/** Props for the live-detail page.
 *
 *  `readOnly` is set to `true` when this component is rendered behind
 *  the unauthenticated `/lives/$handle` public route — the same React
 *  tree as `/admin/tiktok/$handle`, minus every admin-only affordance
 *  (Add-Rival monitor pills, write actions, listener-status debug,
 *  etc.). The default `false` preserves every admin call site untouched.
 *
 *  The API namespace itself swaps via `TikTokApiContext` — there is no
 *  `api` prop here. Public usage wraps the component in
 *  `<TikTokApiProvider value={publicTiktokApi}>` so every `useTikTokApi`
 *  consumer in the subtree hits `/public/tiktok/*` instead of
 *  `/admin/tiktok/*`. */
interface TikTokLiveDetailProps {
  /** When true, hide every admin-write affordance — rival add-to-monitor
   *  pills + their confirmation modal, the probe-debug button (which
   *  reads worker_log), and any future delete/pause/reconnect buttons.
   *  Data-read panels (chart, calendar, broadcasts, top gifters,
   *  comments timeline, past battles) stay fully interactive. */
  readOnly?: boolean;
}

export function TikTokLiveDetail({ readOnly = false }: TikTokLiveDetailProps = {}) {
  // Two providers wrap the body: timezone (per-page tz preference)
  // and runtime-config (TikTok poll cadence + WS-vs-poll modes from
  // typed admin config).
  //
  // The runtime-config audience is `admin` for admin mounts (full
  // set of keys from `/admin/tiktok/runtime-config` behind auth) and
  // `public` for the readOnly mount used by `/lives/<handle>` (sees
  // only the public-safe slice from `/public/tiktok/runtime-config`).
  // Both audiences end up driving the same body component — the
  // audience prop just decides which endpoint feeds the values.
  return (
    <TikTokTimezoneProvider>
      <TikTokRuntimeConfigProvider audience={readOnly ? 'public' : 'admin'}>
        <TikTokLiveDetailBody readOnly={readOnly} />
      </TikTokRuntimeConfigProvider>
    </TikTokTimezoneProvider>
  );
}

function TikTokLiveDetailBody({ readOnly = false }: { readOnly?: boolean }) {
  const tiktokApi = useTikTokApi();
  // Runtime knobs from typed admin config (poll cadence + WS mode).
  // `pollIntervalMs` drives the host-profile refresh below; the WS
  // open later in this body is gated by mode + readOnly. Public WS
  // is not yet implemented, so for `readOnly` mounts we always
  // skip the WS regardless of `publicRealtime`.
  const { pollIntervalMs, adminRealtime, publicRealtime } = useTikTokRuntimeConfig();
  // Route param: handle (without @).
  const { handle: rawHandle } = useParams({ strict: false }) as { handle?: string };
  const handle = (rawHandle || '').replace(/^@/, '');
  // Active timezone, plus formatters bound to it. Consumed everywhere
  // a date or time renders below.
  const { tz } = useTikTokTimezone();

  const [stats, setStats] = useState<TikTokRoomStats | null>(null);
  const [rooms, setRooms] = useState<TikTokRoom[]>([]);
  const [roomId, setRoomId] = useState<string | null>(null);
  // Tracks whether the user has explicitly chosen a broadcast (via the
  // dropdown or the calendar heatmap). Once true, the rooms-list
  // poller no longer auto-jumps to a newer broadcast — same pattern
  // as suppressing chart-stats refetches while a chart-brush range
  // is pinned. Reset only on a full page reload.
  const userPinnedRoomRef = useRef<boolean>(false);
  const pinRoom = (rid: string | null) => {
    userPinnedRoomRef.current = rid != null;
    setRoomId(rid);
  };
  // Custom range derived from a chart-brush selection. When set, it
  // overrides the default "entire broadcast" view. Cleared by clicking
  // the "Reset range" pill or by switching rooms.
  const [customRange, setCustomRange] = useState<
    { since: string; until: string; label: string } | null
  >(null);
  // Brush position (in bucket indices). Resets to "full range" each time
  // stats reload, so the brush handles snap to the visible chart edges.
  const [brushIndices, setBrushIndices] = useState<
    { startIndex: number; endIndex: number } | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [recent, setRecent] = useState<TikTokWsEvent[]>([]);
  const [matches, setMatches] = useState<TikTokMatch[]>([]);
  // Full host subscription record — drives the rich profile header
  // (avatar, follower count, bio, is_live, current room) and the
  // Past-battles host chip. Re-fetched on a 30s cadence so the live
  // status stays fresh without WS dependency.
  const [hostProfile, setHostProfile] = useState<TikTokSubscription | null>(null);
  // 30-day activity summary lifted out of TikTokLiveCalendar so the
  // ProfileHeaderCard can render the chip alongside the avatar (vs
  // the calendar's own header strap). Set via the calendar's
  // `onSummary` callback when its data resolves.
  const [activitySummary, setActivitySummary] = useState<
    import('@admin/components/TikTokLiveCalendar').TikTokLiveActivitySummary | null
  >(null);
  // When a Top Gifter row is clicked, this stores enough context to
  // populate the gift-history modal without a second round-trip.
  const [selectedGifter, setSelectedGifter] = useState<{
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
    /** Counters are optional. Click paths that already know the
     *  totals (leaderboard chips, gifters table) pass them through.
     *  Paths that don't (the comments timeline only knows identity)
     *  leave them undefined — the gifter modal then renders `(·)` on
     *  the tab badges instead of a misleading `(0)`. */
    diamonds?: number;
    gifts?: number;
    comments?: number;
    /** Tab to open by default — defaults to "gifts" but the user can
     *  open directly into "comments" by clicking the comments chip. */
    tab?: 'gifts' | 'comments' | 'relationships';
    /** When opened from a past-match modal, bound the gift/comment
     *  history to the match window. Drop these to fall back to the
     *  whole-room scope. */
    since?: string | null;
    until?: string | null;
    /** Human label for the third scope chip (e.g. "This battle"). */
    windowLabel?: string;
    /** Extra room IDs to add to the gifter modal's `extraRoomIds`.
     *  Used when the click came from the match modal's donor panel
     *  for an opponent-side gifter — their gift events sit in the
     *  rival's room, which isn't in `effectiveExtraRoomIds`. Merging
     *  these in lets the per-room searchEvents query see them too. */
    extraRoomIds?: string[];
    /** When set to 'profile-only', the modal opens with NO room/range
     *  scope — the "Current" tab is suppressed and only the Profile
     *  (cross-host overview) renders. Used by the host's own
     *  "Gifter Profile" button on the header card, where "what this
     *  user gifted in this room" is the wrong framing (the host
     *  RECEIVES gifts here; their gifter activity lives in OTHER
     *  monitored lives). */
    scope?: 'profile-only';
  } | null>(null);
  // Selected past match for the events-modal drill-in.
  const [selectedMatch, setSelectedMatch] = useState<TikTokMatch | null>(null);
  // When the user clicks a calendar day that has >1 broadcast, we
  // open this picker so they explicitly choose which to drill into
  // (one OR multiple). A single-broadcast day skips the picker.
  const [dayPicker, setDayPicker] = useState<{
    date: string;
    rooms: TikTokRoom[];
    selected: Set<string>;     // room_ids the user has checked
  } | null>(null);
  // Carrier for the calendar day's zone-aware UTC bounds while the
  // picker is open. Promoted onto `dayWindow` on confirm; dropped on
  // cancel.
  const [dayPickerBounds, setDayPickerBounds] = useState<{
    since: string;
    until: string;
  } | null>(null);
  // When the user picks 2+ broadcasts, the chart aggregates their
  // buckets client-side. Room-scoped panels (gifters, comments, etc.)
  // stay tied to the first room of the set so the rest of the page
  // doesn't have to learn a multi-room mode.
  const [aggregatedRooms, setAggregatedRooms] = useState<TikTokRoom[] | null>(null);
  // Zone-aware UTC bounds of the calendar day the user picked. Set
  // alongside aggregatedRooms when the user clicks a calendar cell;
  // cleared on "Return to current broadcast" or single-room pin. The
  // day-aggregate fetch and the tabs use these as `since`/`until`
  // instead of the rooms' own min/max — that way "May 7 in Lima"
  // queries [2026-05-07T05:00:00Z, 2026-05-08T05:00:00Z) and includes
  // the tail of any cross-midnight broadcast that contributed events
  // to that Lima-day window.
  const [dayWindow, setDayWindow] = useState<{
    dateYmd: string;
    since: string;
    until: string;
  } | null>(null);
  // Transient highlight band drawn over the diamond chart when the
  // user clicks a per-broadcast pill. Cleared automatically after a
  // short timer so the chart returns to its normal state.
  const [chartHighlight, setChartHighlight] = useState<{
    startIndex: number;
    endIndex: number;
    color: string;
  } | null>(null);

  // Briefly flash the slice of the chart that corresponds to a
  // broadcast's [start, end] window. Two on/off pulses ≈ 1.4s total
  // so the user can see "where on this chart did this broadcast
  // contribute". Doesn't switch rooms — purely visual.
  const blinkBroadcast = (room: TikTokRoom, color: string) => {
    if (!stats?.buckets?.starts?.length) return;
    const starts = stats.buckets.starts;
    const bucketSeconds =
      stats.bucket_seconds && stats.bucket_seconds > 0
        ? stats.bucket_seconds
        : starts.length >= 2
          ? Math.max(
              1,
              Math.round(
                (new Date(starts[1]).getTime() -
                  new Date(starts[0]).getTime()) /
                  1000,
              ),
            )
          : 60;
    const startMs = room.first_seen_at
      ? new Date(room.first_seen_at).getTime()
      : null;
    const endMs = room.ended_at
      ? new Date(room.ended_at).getTime()
      : room.last_seen_at
        ? new Date(room.last_seen_at).getTime()
        : Date.now();
    if (startMs === null) return;
    const baseMs = new Date(starts[0]).getTime();
    const startIdx = Math.max(
      0,
      Math.floor((startMs - baseMs) / 1000 / bucketSeconds),
    );
    const endIdx = Math.min(
      starts.length - 1,
      Math.ceil((endMs - baseMs) / 1000 / bucketSeconds),
    );
    if (endIdx < startIdx) return;
    // Two-pulse blink: on → off → on → off. Each phase 350ms.
    const sched: Array<[number, typeof chartHighlight]> = [
      [0,    { startIndex: startIdx, endIndex: endIdx, color }],
      [350,  null],
      [700,  { startIndex: startIdx, endIndex: endIdx, color }],
      [1400, null],
    ];
    sched.forEach(([ms, val]) => setTimeout(() => setChartHighlight(val), ms));
  };

  // Chronologically-sorted broadcasts. Used by BOTH the strip pills
  // and the chart bands so the colour palette assigns the same colour
  // to the same broadcast in both views, and reading left→right in the
  // strip matches left→right on the chart's x-axis (which is always
  // time-ordered).
  const aggregatedRoomsChrono = useMemo(() => {
    if (!aggregatedRooms) return null;
    return [...aggregatedRooms].sort((a, b) => {
      const ta = a.first_seen_at ? new Date(a.first_seen_at).getTime() : 0;
      const tb = b.first_seen_at ? new Date(b.first_seen_at).getTime() : 0;
      return ta - tb;
    });
  }, [aggregatedRooms]);

  // Persistent coloured bands behind the diamond chart — one per
  // broadcast, palette-matched to the contribution-strip pills below
  // the chart. Only built in day-aggregate mode (multiple broadcasts);
  // in single-room mode the line speaks for itself and a single band
  // would just be visual noise.
  const chartBands = useMemo(() => {
    if (!aggregatedRoomsChrono || aggregatedRoomsChrono.length < 2) return undefined;
    // When a brushed range is active the chart only shows that slice
    // — broadcasts that span hours of the full day collapse to single
    // points at the chart edges and the visual breaks. Drop the
    // bands so the brushed view is a clean single-colour line.
    if (customRange) return undefined;
    const starts = stats?.buckets?.starts;
    if (!starts || starts.length === 0) return undefined;
    // Prefer the response's bucket_seconds; fall back to deriving it
    // from consecutive starts (the only authoritative signal when the
    // field is missing). 60s default is wrong for day-aggregate.
    const bucketSeconds =
      (stats?.bucket_seconds && stats.bucket_seconds > 0
        ? stats.bucket_seconds
        : starts.length >= 2
          ? Math.max(
              1,
              Math.round(
                (new Date(starts[1]).getTime() -
                  new Date(starts[0]).getTime()) /
                  1000,
              ),
            )
          : 60);
    const baseMs = new Date(starts[0]).getTime();
    const out: Array<{ startIndex: number; endIndex: number; color: string }> = [];
    aggregatedRoomsChrono.forEach((r, idx) => {
      if (!r.first_seen_at) return;
      const startMs = new Date(r.first_seen_at).getTime();
      const endMs = r.ended_at
        ? new Date(r.ended_at).getTime()
        : r.last_seen_at
          ? new Date(r.last_seen_at).getTime()
          : Date.now();
      const startIdx = Math.max(
        0,
        Math.floor((startMs - baseMs) / 1000 / bucketSeconds),
      );
      const endIdx = Math.min(
        starts.length - 1,
        Math.ceil((endMs - baseMs) / 1000 / bucketSeconds),
      );
      if (endIdx < startIdx) return;
      out.push({
        startIndex: startIdx,
        endIndex: endIdx,
        color: BROADCAST_PALETTE[idx % BROADCAST_PALETTE.length],
      });
    });
    return out;
  }, [aggregatedRoomsChrono, stats?.buckets?.starts, stats?.bucket_seconds, customRange]);
  // Top Gifters card tab.
  const [giftersTab, setGiftersTab] = useState<'gifters' | 'comments' | 'crosslive'>('gifters');
  // Scope for the gifters/comments tables. 'live' = whatever room or
  // window the chart is currently focused on (default behaviour);
  // 'alltime' = sum across every recorded room for this host. The
  // alltime fetch is lazy and cached for the page session so flipping
  // back and forth doesn't re-hit /lives/{handle}/rooms.
  const [tabsScope, setTabsScope] = useState<'live' | 'alltime'>('live');
  const [allHostRoomIds, setAllHostRoomIds] = useState<string[] | null>(null);
  const [allHostRoomsLoading, setAllHostRoomsLoading] = useState(false);
  // Totals bubbled up by each tab's component so the labels can read
  // `Top gifters (N)` / `Comments (N)` without a duplicate query here.
  // Pre-populated by the effect below so BOTH counts are visible
  // before the user clicks into a tab — without it, the inactive tab's
  // component never mounts → its `onTotalChange` never fires →
  // "Comments" stays uncounted until clicked.
  const [topGiftersTotal, setTopGiftersTotal] = useState<number | null>(null);
  // Current page of the gifters table — bubbled up via the table's
  // `onItemsChange` callback so the Top Gifter donut on the right can
  // render the same rows without a duplicate `getRoomGifters` fetch.
  const [topGiftersItems, setTopGiftersItems] = useState<TikTokGifter[]>([]);
  const [topGiftersLoading, setTopGiftersLoading] = useState(false);
  const [commentsTotal, setCommentsTotal] = useState<number | null>(null);
  const [crossLiveTotal, setCrossLiveTotal] = useState<number | null>(null);
  // Clicking a cross-live gifter opens the shared cross-host detail
  // modal (already used by /admin/tiktok/lives' Common Gifters table).
  // The string user_id is the only piece of identity the cross-live
  // endpoint reliably returns; the modal fetches the rest itself.
  const [selectedCrossUserId, setSelectedCrossUserId] = useState<string | null>(null);
  // Bumped by the card-header refresh button — forwards the click into the
  // gifters table and the events timeline to force a refetch.
  const [eventsRefreshKey, setEventsRefreshKey] = useState(0);
  // Which event-type series the user has toggled OFF in the All-events
  // overlay. Empty set = all visible (default). Survives renders but
  // resets on full page reload — intentional, this is a presentation
  // preference, not a saved view.
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set());
  const wsRef = useRef<WebSocket | null>(null);

  const selectedRoom = useMemo(
    () => rooms.find((r) => r.room_id === roomId) ?? null,
    [rooms, roomId]
  );

  // Default view = entire selected broadcast. A chart-brush range select
  // (customRange) overrides the default; every consumer (top gifters,
  // comments, charts) follows the same effective window.
  const effectiveWindow: WindowOption = useMemo(() => {
    if (customRange) {
      return {
        kind: 'custom',
        label: customRange.label,
        since: customRange.since,
        until: customRange.until,
      };
    }
    // Single-broadcast calendar pick: dayWindow is set but
    // aggregatedRooms is null. Surface the dayWindow as a custom
    // range so the chart + tabs filter to the picked tz-day and the
    // numbers match the calendar's per-day bucket. Without this
    // branch, fetchStats falls back to BROADCAST_WINDOW and pulls
    // the entire pinned broadcast's diamonds — a cross-midnight
    // broadcast or a multi-hour stream that mostly ran on a
    // different day would show a total wildly larger than the
    // calendar cell promised.
    if (dayWindow && !aggregatedRooms) {
      return {
        kind: 'custom',
        label: `Day · ${dayWindow.dateYmd}`,
        since: dayWindow.since,
        until: dayWindow.until,
      };
    }
    return BROADCAST_WINDOW;
  }, [customRange, dayWindow, aggregatedRooms]);

  /** Resolve a WindowOption to concrete since/until ISO strings.
   *  Centralized so the Top Gifters comments-tab and the stats fetcher
   *  agree on what "the current window" means. */
  const resolveRange = (
    w: WindowOption,
    room: TikTokRoom | null
  ): { since?: string; until?: string; window_minutes?: number } => {
    if (w.kind === 'broadcast' && room) {
      const r: { since?: string; until?: string } = {};
      if (room.first_seen_at) r.since = room.first_seen_at;
      if (room.ended_at) r.until = room.ended_at;
      else if (room.last_seen_at) r.until = room.last_seen_at;
      return r;
    }
    if (w.kind === 'custom') {
      return { since: w.since, until: w.until };
    }
    return {};
  };

  // Range + extra room ids passed to the Top Gifters / Comments tabs.
  // In day-aggregate mode WITHOUT a brushed range we span the union of
  // every selected broadcast (instead of just `selectedRoom`'s window),
  // and pass the other broadcasts as `extraRoomIds` so the SQL hits
  // every room. A brushed range still wins — it scopes both axis and
  // room set the same way the chart does.
  const tabsExtraRoomIds = useMemo<string[] | undefined>(() => {
    if (!aggregatedRooms || aggregatedRooms.length < 2) return undefined;
    return aggregatedRooms
      .map((r) => r.room_id)
      .filter((rid) => rid !== roomId);
  }, [aggregatedRooms, roomId]);

  // Lazy fetch — only hit /lives/{handle}/rooms the first time the
  // operator flips to "All time". Once loaded, kept for the page
  // session so subsequent toggles are instant.
  useEffect(() => {
    if (tabsScope !== 'alltime' || allHostRoomIds !== null || !handle) return;
    let cancelled = false;
    setAllHostRoomsLoading(true);
    tiktokApi
      .listHostRooms(handle, 200)
      .then((rows) => {
        if (cancelled) return;
        setAllHostRoomIds(rows.map((r) => r.room_id));
      })
      .catch(() => {
        if (cancelled) return;
        setAllHostRoomIds([]); // mark loaded so we don't retry on every toggle
      })
      .finally(() => {
        if (!cancelled) setAllHostRoomsLoading(false);
      });
    return () => { cancelled = true; };
  }, [tabsScope, allHostRoomIds, handle]);

  // Human-readable description of what the diamond chart is showing,
  // rendered under the section heading. Helps the user keep their
  // bearings as they pop between live, day-aggregate and brushed-range
  // modes — otherwise the chart silently changes scope and the totals
  // drift with no on-screen explanation of why.
  const chartViewLabel = useMemo(() => {
    const fmtTime = (iso: string) => fmtHM(iso, tz);
    const fmtDate = (iso: string) => fmtShortDate(iso, tz);
    if (customRange) {
      return `Selected range · ${fmtDate(customRange.since)} ${fmtTime(customRange.since)} → ${fmtTime(customRange.until)}`;
    }
    if (aggregatedRoomsChrono && aggregatedRoomsChrono.length > 1) {
      // Prefer the zone-aware day window if we got here via a calendar
      // pick — that's the canonical "May 7 in Lima" framing.
      if (dayWindow) {
        return `Day view · ${fmtDate(dayWindow.since)} · ${fmtTime(dayWindow.since)} → ${fmtTime(dayWindow.until)} · summing ${aggregatedRoomsChrono.length} broadcasts`;
      }
      const first = aggregatedRoomsChrono[0]?.first_seen_at;
      const last =
        aggregatedRoomsChrono[aggregatedRoomsChrono.length - 1]?.ended_at ??
        aggregatedRoomsChrono[aggregatedRoomsChrono.length - 1]?.last_seen_at;
      const dateLabel = first ? fmtDate(first) : '';
      const span =
        first && last ? `${fmtTime(first)} → ${fmtTime(last)}` : '';
      return `Day view · ${dateLabel}${span ? ` · ${span}` : ''} · summing ${aggregatedRoomsChrono.length} broadcasts`;
    }
    // Single-broadcast calendar pick: dayWindow is set, aggregated
    // mode is off. Frame as the zone-day rather than the broadcast's
    // own bounds so the heading matches the calendar cell the user
    // just clicked.
    if (dayWindow && !aggregatedRoomsChrono) {
      return `Day view · ${fmtDate(dayWindow.since)} · ${fmtTime(dayWindow.since)} → ${fmtTime(dayWindow.until)}`;
    }
    if (selectedRoom?.first_seen_at) {
      const start = selectedRoom.first_seen_at;
      const end =
        selectedRoom.ended_at ?? selectedRoom.last_seen_at ?? null;
      const live =
        !selectedRoom.ended_at && !roomEndedHeuristic(selectedRoom);
      if (live) {
        return `Live broadcast · ${fmtDate(start)} · started ${fmtTime(start)}`;
      }
      return `Broadcast · ${fmtDate(start)} · ${fmtTime(start)}${end ? ` → ${fmtTime(end)}` : ''}`;
    }
    return 'All-time totals';
  }, [customRange, aggregatedRoomsChrono, selectedRoom, tz, dayWindow]);

  const tabsRange = useMemo<{ since?: string; until?: string; window_minutes?: number }>(() => {
    if (effectiveWindow.kind === 'custom') {
      return { since: effectiveWindow.since, until: effectiveWindow.until };
    }
    // Day-aggregate from a calendar pick: zone-day bounds win, so the
    // tabs see the same `[since, until)` as the chart fetch.
    if (aggregatedRooms && aggregatedRooms.length > 1 && dayWindow) {
      return { since: dayWindow.since, until: dayWindow.until };
    }
    if (aggregatedRooms && aggregatedRooms.length > 1) {
      const firsts = aggregatedRooms
        .map((r) => r.first_seen_at)
        .filter(Boolean) as string[];
      const lasts = aggregatedRooms
        .map((r) => r.ended_at ?? r.last_seen_at)
        .filter(Boolean) as string[];
      return {
        since: firsts.length ? firsts.reduce((a, b) => (a < b ? a : b)) : undefined,
        until: lasts.length ? lasts.reduce((a, b) => (a > b ? a : b)) : undefined,
      };
    }
    return resolveRange(effectiveWindow, selectedRoom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveWindow, aggregatedRooms, selectedRoom, dayWindow]);

  // Scope-aware overrides applied at the table props. In alltime mode
  // we feed every recorded room as the union (path roomId + all
  // others as `extraRoomIds`) and drop the time bounds so the backend
  // doesn't filter by ts.
  const effectiveExtraRoomIds = useMemo<string[] | undefined>(() => {
    if (tabsScope !== 'alltime') return tabsExtraRoomIds;
    if (!allHostRoomIds) return undefined;
    return allHostRoomIds.filter((rid) => rid !== roomId);
  }, [tabsScope, allHostRoomIds, tabsExtraRoomIds, roomId]);

  const effectiveRange = useMemo<{ since?: string; until?: string; window_minutes?: number }>(() => {
    if (tabsScope === 'alltime') return {}; // unbounded
    return tabsRange;
  }, [tabsScope, tabsRange]);

  const fetchStats = async (rid: string, w: WindowOption, room: TikTokRoom | null) => {
    try {
      const s = await tiktokApi.getRoomStats(rid, resolveRange(w, room));
      setStats(s);
    } catch (e) {
      console.error(e);
      toast.error('Failed to load stats');
    }
  };

  const refresh = async () => {
    setLoading(true);
    try {
      const list = await tiktokApi.listHostRooms(handle, 50);
      setRooms(list);
      // Stick with the user's current selection if it's still in the list,
      // otherwise default to the most recent room.
      const targetRid =
        (roomId && list.find((r) => r.room_id === roomId)?.room_id) ||
        list[0]?.room_id ||
        null;
      setRoomId(targetRid);
      if (targetRid) {
        const room = list.find((r) => r.room_id === targetRid) ?? null;
        await fetchStats(targetRid, effectiveWindow, room);
        // Match history is now scoped to the selected broadcast — no
        // mixing PK history across separate lives.
        const ms = await tiktokApi.listMatches({
          handle,
          room_id: targetRid,
          limit: 50,
        });
        setMatches(ms);
      } else {
        setStats(null);
        setMatches([]);
      }
    } catch (e) {
      console.error(e);
      toast.error('Failed to load room');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle]);

  // Host profile for the matchup chip (avatar + nickname). One-shot lookup
  // from the subscriptions list — cheap, cached server-side. Refreshed
  // every 30s so the profile card's live indicator + follower count
  // stay current without any WebSocket dependency.
  useEffect(() => {
    let cancelled = false;
    const fetchHost = () => {
      tiktokApi
        .getLiveByHandle(handle)
        .then((me) => {
          if (cancelled) return;
          if (me) setHostProfile(me);
        })
        .catch(() => { /* fallback to whatever we had */ });
    };
    fetchHost();
    const t = setInterval(fetchHost, pollIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [handle, pollIntervalMs]);

  // Periodic rooms-list refresh — picks up a fresh broadcast that started
  // after the page loaded (the creator went LIVE during the session).
  // The user wouldn't otherwise see the new room in the dropdown until
  // they manually clicked refresh.
  useEffect(() => {
    let cancelled = false;
    const t = setInterval(() => {
      if (cancelled) return;
      tiktokApi
        .listHostRooms(handle, 50)
        .then((list) => {
          if (cancelled) return;
          setRooms(list);
          // Auto-advance to the newest broadcast ONLY when the user
          // hasn't explicitly chosen a room. The previous "if you
          // were on the previously-newest, follow the new newest"
          // heuristic silently overrode an explicit calendar/dropdown
          // pick the moment a new broadcast started — same shape as
          // the chart-brush issue earlier.
          if (userPinnedRoomRef.current) return;
          const currentTop = list[0]?.room_id;
          if (currentTop && roomId !== currentTop) {
            setRoomId(currentTop);
          }
        })
        .catch(() => {
          /* transient — try again on the next tick */
        });
    }, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle]);

  // Re-fetch stats on room change, brushed-range change, OR
  // calendar-day pick. `dayWindow` is in the deps because it now
  // feeds into `effectiveWindow` (single-broadcast calendar picks
  // route through it); without it, clicking a different day on the
  // calendar wouldn't re-fire the fetch and the chart kept showing
  // whatever was loaded previously.
  useEffect(() => {
    if (aggregatedRooms && aggregatedRooms.length > 1) return; // handled below
    if (roomId) fetchStats(roomId, effectiveWindow, selectedRoom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, customRange, dayWindow, aggregatedRooms]);

  // Day-aggregate fetch path. When 2+ rooms are selected we hit a
  // single backend endpoint that does the room_id IN (...) GROUP BY
  // bucket on the SQL side. Replaces the previous "fan out N parallel
  // getRoomStats and sum the bucket arrays in JS" — same answer, ~1
  // round-trip instead of N.
  //
  // counts_window / counts_total are derived from the aggregated
  // `by_type` (sum-per-type across buckets) so the All-events
  // overlay's per-type pill counts reflect the full day, not just
  // whatever room was selected first.
  useEffect(() => {
    if (!aggregatedRooms || aggregatedRooms.length < 2) return;
    let since: string;
    let until: string;
    if (customRange) {
      // Brushed range overrides the day window — the page should
      // filter to exactly what the user dragged across the chart.
      since = customRange.since;
      until = customRange.until;
    } else if (dayWindow) {
      // Zone-aware day window from the calendar pick. This is the
      // canonical "May 7 in Lima" view — every event with ts in
      // [05:00 UTC May 7, 05:00 UTC May 8) (or whatever the offset
      // resolves to) belongs here, including tails of broadcasts
      // that crossed midnight in zone.
      since = dayWindow.since;
      until = dayWindow.until;
    } else {
      const firsts = aggregatedRooms
        .map((r) => r.first_seen_at)
        .filter(Boolean) as string[];
      const lasts = aggregatedRooms
        .map((r) => r.ended_at ?? r.last_seen_at)
        .filter(Boolean) as string[];
      if (firsts.length === 0 || lasts.length === 0) return;
      since = firsts.reduce((a, b) => (a < b ? a : b));
      until = lasts.reduce((a, b) => (a > b ? a : b));
      // Lag fix for the writer-snapshot behind real-time on a TRULY
      // active room (events arrive after `last_seen_at` was last
      // updated). Earlier this was "extend to now()" — but rooms whose
      // `ended_at` was never written by the worker still look live by
      // that test, so the chart's X axis was stretching from the day
      // start all the way to the present (sometimes 24h+ of flat
      // zeros, see the 21:28→23:15 + 04:37→05:37 + 01:03→02:03 case
      // the user reported). The cap below extends `until` only when
      // the latest sample is genuinely recent, and only by a small
      // window — enough to catch in-flight events, not enough to
      // distort the X axis.
      const RECENCY_CUTOFF_MS = 90_000;   // last_seen_at within 90s = live
      const TAIL_EXTEND_MS    = 5 * 60_000; // pad at most 5min past last_seen
      const untilMs = new Date(until).getTime();
      const anyFreshLive = aggregatedRooms.some(
        (r) =>
          !r.ended_at &&
          r.last_seen_at &&
          Date.now() - new Date(r.last_seen_at).getTime() < RECENCY_CUTOFF_MS,
      );
      if (anyFreshLive) {
        const padded = Math.min(Date.now(), untilMs + TAIL_EXTEND_MS);
        if (padded > untilMs) until = new Date(padded).toISOString();
      }
    }
    let cancelled = false;
    tiktokApi
      .getAggregatedBuckets({
        room_ids: aggregatedRooms.map((r) => r.room_id),
        since,
        until,
      })
      .then((agg) => {
        if (cancelled) return;
        // Derive per-type window counts from the aggregated buckets so
        // downstream code (All-events overlay pill counts, etc.) sees
        // the full day's totals rather than whatever the first room
        // got bound to.
        const counts_from_buckets: Record<string, number> = {};
        for (const [t, arr] of Object.entries(agg.by_type ?? {})) {
          counts_from_buckets[t] = arr.reduce((a, b) => a + b, 0);
        }
        setStats((prev) => {
          // Fall back to a synthetic shell if no first-room stats
          // arrived yet — better than blanking the chart while the
          // primary fetch is still in flight.
          const base: TikTokRoomStats =
            prev ?? ({
              room: null,
              window_minutes: 0,
              bucket_seconds: 0,
              since: '',
              now: '',
              counts_window: {},
              counts_total: {},
              top_gifters: [],
              diamonds_total: 0,
              active_match: null,
              buckets: { starts: [], by_type: {}, diamonds: [] },
            } as unknown as TikTokRoomStats);
          // Authoritative bucket size from the response, with a
          // derived fallback from consecutive `starts` for older
          // responses that don't include it. Without this the band
          // index math defaults to 60s and shifts every coloured
          // segment far to the left of where it should be.
          const derivedBs =
            agg.starts.length >= 2
              ? Math.max(
                  1,
                  Math.round(
                    (new Date(agg.starts[1]).getTime() -
                      new Date(agg.starts[0]).getTime()) /
                      1000,
                  ),
                )
              : 0;
          const bs =
            typeof agg.bucket_seconds === 'number' && agg.bucket_seconds > 0
              ? agg.bucket_seconds
              : derivedBs;
          return {
            ...base,
            bucket_seconds: bs,
            diamonds_total: agg.diamonds_total,
            counts_window: counts_from_buckets,
            counts_total: counts_from_buckets,
            buckets: {
              starts: agg.starts,
              by_type: agg.by_type,
              diamonds: agg.diamonds,
            },
          };
        });
      })
      .catch(() => {
        /* keep previous stats on transient error */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aggregatedRooms, customRange, dayWindow]);

  // Clear any chart-brush selection when the user switches room — old
  // since/until belongs to the previous broadcast.
  useEffect(() => {
    setCustomRange(null);
    setBrushIndices(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId]);

  // When new buckets arrive, snap the brush to the visible range so the
  // handles match the chart edges (instead of being stuck at the prior
  // dataset's index extent).
  useEffect(() => {
    const n = stats?.buckets?.starts?.length ?? 0;
    if (n === 0) {
      setBrushIndices(null);
      return;
    }
    if (!brushIndices) {
      setBrushIndices({ startIndex: 0, endIndex: n - 1 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stats]);

  // Pre-populate the Top gifters / Comments tab counters so both
  // badges show numbers before the user clicks. Each tab's component
  // also bubbles its own freshest total via `onTotalChange`, which
  // overwrites these — so the in-tab fetch wins on the active tab and
  // the prefetch covers the inactive one.
  useEffect(() => {
    if (!roomId) {
      setTopGiftersTotal(null);
      setCommentsTotal(null);
      return;
    }
    let cancelled = false;
    // Day-aggregate view: also pull events/gifters from every other
    // broadcast of the day so the (N) badges reflect the same data
    // set the chart is summing. effectiveWindow.kind === 'broadcast'
    // would otherwise scope the range to one broadcast — in
    // day-aggregate mode we want the union of every selected room's
    // first_seen_at..last_seen_at.
    const aggMode = !!(aggregatedRooms && aggregatedRooms.length > 1);
    let range: { since?: string; until?: string };
    if (aggMode && effectiveWindow.kind !== 'custom') {
      const firsts = aggregatedRooms!
        .map((r) => r.first_seen_at)
        .filter(Boolean) as string[];
      const lasts = aggregatedRooms!
        .map((r) => r.ended_at ?? r.last_seen_at)
        .filter(Boolean) as string[];
      range = {
        since: firsts.length ? firsts.reduce((a, b) => (a < b ? a : b)) : undefined,
        until: lasts.length ? lasts.reduce((a, b) => (a > b ? a : b)) : undefined,
      };
    } else {
      range = resolveRange(effectiveWindow, selectedRoom);
    }
    const extraRoomIds =
      aggMode
        ? aggregatedRooms!
            .map((r) => r.room_id)
            .filter((rid) => rid !== roomId)
        : undefined;
    Promise.all([
      // limit=1 — we only care about the `total` field, the row itself is throwaway.
      tiktokApi.getRoomGifters(roomId, {
        since: range.since,
        until: range.until,
        limit: 1,
        offset: 0,
        extra_room_ids: extraRoomIds,
      }),
      tiktokApi.countEvents({
        room_id: roomId,
        room_ids: extraRoomIds
          ? Array.from(new Set([roomId, ...extraRoomIds]))
          : undefined,
        type: 'comment',
        since: range.since,
        until: range.until,
      }),
    ])
      .then(([gifters, comments]) => {
        if (cancelled) return;
        setTopGiftersTotal(gifters.total);
        setCommentsTotal(comments.total);
      })
      .catch(() => {
        /* keep stale counters — transient errors shouldn't blank the badges */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, effectiveWindow, selectedRoom, eventsRefreshKey, aggregatedRooms]);

  // Re-fetch the match list whenever the selected broadcast changes —
  // Past Battles and the active-match panel are scoped to one room.
  useEffect(() => {
    if (!roomId) {
      setMatches([]);
      return;
    }
    const aggMode = !!(aggregatedRooms && aggregatedRooms.length > 1);
    const ranged = effectiveWindow.kind === 'custom';
    let cancelled = false;
    // Day-aggregate or brushed-range view: fetch host-wide and filter
    // by the active range so the "Past battles (N)" count reflects
    // EVERY broadcast in scope, not just the pinned one. Single-room
    // view stays scoped to that room (cheap, single SQL).
    const fetcher =
      aggMode || ranged
        ? tiktokApi.listMatches({ handle, limit: 200 }).then((all) => {
            const since = tabsRange.since ? new Date(tabsRange.since).getTime() : null;
            const until = tabsRange.until ? new Date(tabsRange.until).getTime() : null;
            if (since == null && until == null) return all;
            return all.filter((m) => {
              const t = m.started_at ? new Date(m.started_at).getTime() : null;
              if (t == null) return false;
              if (since != null && t < since) return false;
              if (until != null && t > until) return false;
              return true;
            });
          })
        // Use `listMatches({ handle, room_id })` instead of the
        // legacy `listMatchesForRoom` so the call works on both
        // namespaces — the public endpoint requires `handle`, the
        // admin endpoint accepts and ignores it.
        : tiktokApi.listMatches({ handle, room_id: roomId, limit: 50 });
    fetcher
      .then((ms) => {
        if (!cancelled) setMatches(ms);
      })
      .catch(() => {
        /* keep previous list on error */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    roomId,
    handle,
    aggregatedRooms,
    effectiveWindow,
    tabsRange.since,
    tabsRange.until,
  ]);

  // Live updates: only meaningful when the selected room is still live.
  // For closed rooms, polling refresh is wasteful — but cheap, so keep it.
  // Throttle stats refetches triggered by WS match events. match_update
  // can fire every ~1s; we don't need a network roundtrip per event.
  const matchRefreshThrottleRef = useRef<number>(0);

  // Refs that always point at the LATEST `effectiveWindow` /
  // `selectedRoom`. The WS + polling effect below is kept stable
  // (deps: only `handle` / `roomId` / `selectedRoom?.ended_at`) so we
  // don't churn the websocket on every brush, but the callbacks need
  // the most recent window — without these refs the interval would
  // capture the initial broadcast-wide window and overwrite the user's
  // brushed range ~10s later, leaving the reset pill but reverting
  // the chart to the full broadcast.
  const effectiveWindowRef = useRef(effectiveWindow);
  const selectedRoomRef = useRef(selectedRoom);
  // Long-lived callbacks (WS match-update handler, the polling
  // setInterval) need to know when day-aggregate mode is active so
  // they DON'T overwrite the aggregated stats with a single-room
  // refetch. Without this, the polling tick 10s after a day-pick
  // silently replaces the day-spanning chart with the picked room's
  // narrower window — same shape as the brush-overwrite bug fixed
  // earlier with `effectiveWindowRef`.
  const aggregatedRoomsRef = useRef(aggregatedRooms);
  useEffect(() => {
    effectiveWindowRef.current = effectiveWindow;
  }, [effectiveWindow]);
  useEffect(() => {
    selectedRoomRef.current = selectedRoom;
  }, [selectedRoom]);
  useEffect(() => {
    aggregatedRoomsRef.current = aggregatedRooms;
  }, [aggregatedRooms]);

  useEffect(() => {
    // Pick which WS audience to open based on render mode + config:
    //
    //   - Admin mount (`readOnly=false`): connect to `/admin/tiktok/ws`
    //     (auth, sees every tracked handle). Operator can disable
    //     via TIKTOK_ADMIN_REALTIME_MODE=poll — useful when debugging
    //     WS issues or running on a constrained network.
    //
    //   - Public mount (`readOnly=true`): connect to `/public/tiktok/ws`
    //     (no auth, server-side filtered to `is_public=True` handles).
    //     Operator can disable via TIKTOK_PUBLIC_REALTIME_MODE=poll;
    //     default IS `poll` so flipping public WS on is a deliberate
    //     opt-in (a private→public toggle on a host is the surface
    //     that controls per-host exposure; the WS toggle is the
    //     fleet-wide kill switch).
    //
    // The branch below ALSO scopes the WS subscription to just this
    // page's handle so the server only forwards relevant events; the
    // admin-side `*` subscription would deliver every host's stream
    // which the page doesn't render anyway.
    const realtimeMode = readOnly ? publicRealtime : adminRealtime;
    if (realtimeMode === 'poll') return;
    const audience = readOnly ? 'public' : 'admin';
    const ws = openTikTokWebSocket(
      (msg) => {
        // Belt-and-braces: server already filters by handle, but keep
        // the client-side check for correctness during reconnect races.
        if (msg.unique_id !== handle) return;
        setRecent((prev) => [msg, ...prev].slice(0, 60));
        // ── Client-side chart delta on every counted event ─────────
        // When WS is on, merge each event's contribution into the
        // chart's current bucket so the line redraws ~immediately
        // instead of waiting for the next 10s poll. No extra backend
        // round-trip — the chart reconciles to authoritative server
        // state on the next `fetchStats` regardless. Covered types:
        // gift / comment / join / like / follow / share (see
        // MERGEABLE_WS_TYPES). Gift is the only type that also moves
        // the diamond column. Gating: this whole effect early-returns
        // when `realtimeMode === 'poll'`, so reaching here means
        // operator config allows WS-driven UI updates.
        if (
          msg.room_id &&
          roomId &&
          String(msg.room_id) === String(roomId)
        ) {
          // Skip merges while the user has a brushed range pinned
          // (we shouldn't mutate frozen data) or in day-aggregate
          // mode (that view owns `stats` from a different pipeline).
          if (effectiveWindowRef.current.kind === 'custom') {
            /* skip */
          } else {
            const agg = aggregatedRoomsRef.current;
            if (!(agg && agg.length > 1)) {
              setStats((prev) => (prev ? applyEventDeltaToStats(prev, msg) : prev));
            }
          }
        }
        // A WS event for a room we don't have in `rooms` means a new
        // broadcast started since we last fetched — refresh immediately
        // so the dropdown picks it up.
        if (msg.room_id && !rooms.some((r) => r.room_id === msg.room_id)) {
          tiktokApi
            .listHostRooms(handle, 50)
            .then((list) => setRooms(list))
            .catch(() => { /* periodic poller will retry */ });
        }
        // Match lifecycle events drive the live PK panel. Pull fresh stats
        // when one fires so scores don't lag the 10s polling cadence.
        // Throttle to one refetch every 2s — match_update fires every ~1s
        // and we don't need a round-trip per event.
        if (
          (msg.type === 'match_start' ||
            msg.type === 'match_update' ||
            msg.type === 'match_end') &&
          roomId &&
          msg.room_id === roomId
        ) {
          // Don't auto-refresh stats while the user has a range
          // pinned via the chart brush — they'd see the chart flicker
          // around their selection. The reset pill triggers a fresh
          // fetch on click, so they're always one tap from current.
          if (effectiveWindowRef.current.kind === 'custom') return;
          // Day-aggregate mode owns `stats` — a single-room refetch
          // here would clobber it with the picked room's narrower
          // window. The day-aggregate effect re-runs on its own deps.
          const agg = aggregatedRoomsRef.current;
          if (agg && agg.length > 1) return;
          const now = Date.now();
          if (now - matchRefreshThrottleRef.current >= 2000) {
            matchRefreshThrottleRef.current = now;
            fetchStats(roomId, effectiveWindowRef.current, selectedRoomRef.current);
          }
        }
      },
      undefined,
      { handles: [handle], audience }
    );
    wsRef.current = ws;
    const isLive = selectedRoom && !selectedRoom.ended_at && !roomEndedHeuristic(selectedRoom);
    const t = setInterval(
      () => {
        // Skip the auto-poll entirely while the user has a brushed
        // range pinned. The chart should stay frozen on their
        // selection — clicking reset clears `customRange`, the
        // customRange-change effect refetches fresh broadcast-wide
        // stats, so the user is always one click from current.
        if (effectiveWindowRef.current.kind === 'custom') return;
        // Same guard for day-aggregate mode: the day-aggregate effect
        // owns `stats`; a single-room poll would clobber the chart
        // with the picked room's narrow window 10s later.
        const agg = aggregatedRoomsRef.current;
        if (agg && agg.length > 1) return;
        if (roomId) {
          fetchStats(
            roomId,
            effectiveWindowRef.current,
            selectedRoomRef.current,
          );
        }
      },
      isLive ? 10000 : 60000
    );
    return () => {
      ws.close();
      clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle, roomId, selectedRoom?.ended_at, adminRealtime, publicRealtime, readOnly]);

  // ── derived ───────────────────────────────────────────────────────

  const totals = stats?.counts_total ?? {};

  // One series per event type (non-stacked). Sorted by total desc so the
  // most active types appear first in legend + grid.
  // Filtered: PK / battle metadata (`match_*`) and ranking-text events
  // are noisy machine-generated streams that crowd the chart without
  // adding viewer-facing signal — battle progress is already shown in
  // the dedicated PK panel, and rank_text is one-line UI gloss the
  // dashboard doesn't need to chart. The events themselves still
  // ingest into tiktok_events; we just hide them from the live-stats
  // overlay + per-type cards.
  const HIDDEN_STATS_TYPES = useMemo(
    () => new Set([
      'rank_text', 'match_start', 'match_update', 'match_end',
      // `caption` (live auto-subtitles) fires every few seconds while
      // the creator talks — 58k+ in 24h on chatty streams. Dominates
      // the chart without adding leaderboard signal. Persisted as
      // usual in tiktok_events; just hidden from the stats overlay.
      'caption',
    ]),
    []
  );
  const seriesByType = useMemo(() => {
    if (!stats) return [];
    return Object.entries(stats.buckets.by_type)
      .filter(([type]) => !HIDDEN_STATS_TYPES.has(type))
      .map(([type, values]) => ({
        key: type,
        label: type,
        values,
        color: eventColor(type),
        total: values.reduce((a, b) => a + b, 0),
      }))
      .sort((a, b) => b.total - a.total);
  }, [stats, HIDDEN_STATS_TYPES]);

  // Series the chart actually plots — driven by the toggle pills row.
  const visibleSeries = useMemo(
    () => seriesByType.filter((s) => !hiddenSeries.has(s.key)),
    [seriesByType, hiddenSeries]
  );

  const diamondSeries = useMemo(() => {
    if (!stats) return [] as number[];
    return stats.buckets.diamonds ?? [];
  }, [stats]);

  const xLabels = useMemo(
    () => (stats?.buckets.starts ?? []).map((iso) => fmtHM(iso, tz)),
    [stats, tz]
  );

  // Brush callback: convert bucket indices → ISO since/until and commit
  // them as a custom range. Debounced 350ms so dragging doesn't spam the
  // backend with one fetch per pixel.
  const brushDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onBrushChange = (range: { startIndex: number; endIndex: number }) => {
    setBrushIndices(range);
    if (!stats || !stats.buckets?.starts?.length) return;
    const starts = stats.buckets.starts;
    const bucketSeconds = stats.bucket_seconds || 60;
    const fullRange =
      range.startIndex === 0 && range.endIndex === starts.length - 1;

    if (brushDebounceRef.current) clearTimeout(brushDebounceRef.current);
    brushDebounceRef.current = setTimeout(() => {
      if (fullRange) {
        // Drag back to full chart = clear the custom selection.
        setCustomRange(null);
        return;
      }
      const a = Math.max(0, range.startIndex);
      const b = Math.min(starts.length - 1, range.endIndex);
      // Normalize BOTH endpoints through Date round-trip so they share
      // the same wire format. The backend's `bucket_starts` are emitted
      // as naive local-time ISO strings (no Z); the inclusive-end calc
      // produces a UTC string with Z. Sending one of each made FastAPI
      // parse them with different tz semantics (one naive, one aware)
      // and the resulting filter window was bogus.
      const sinceDate = new Date(starts[a]);
      const untilDate = new Date(
        new Date(starts[b]).getTime() + bucketSeconds * 1000,
      );
      const since = sinceDate.toISOString();
      const until = untilDate.toISOString();
      setCustomRange({
        since,
        until,
        label: `${fmtHM(sinceDate, tz)} → ${fmtHM(untilDate, tz)}`,
      });
    }, 350);
  };

  return (
    <PageShell>
      <PageHeader
        title={`@${handle}`}
        icon={<Radio className="w-5 h-5" />}
        description={
          // Show the broadcast title when we have a room; the profile
          // box below already carries the "real-time stats" framing so
          // a generic subtitle is redundant. Only the "no rooms" empty
          // state remains.
          roomId == null
            ? 'No active or recent rooms found.'
            : (stats?.room?.title || null)
        }
        actions={
          <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
            {/* Back link — admin routes back to /admin/tiktok (the
                admin lives index); public routes back to /lives (the
                public lives index that was moved out of `/` when the
                landing page was added). Same affordance, different
                target depending on which surface the user is
                browsing. */}
            <Link to={readOnly ? '/lives' : '/admin/tiktok'}>
              <Button variant="ghost" size="sm">
                <ArrowLeft className="w-4 h-4 mr-1" />
                Lives
              </Button>
            </Link>
            {rooms.length > 0 && (
              // Wrap the selector so it can take the full row on mobile.
              // The selector itself is `w-full sm:w-auto`, but without a
              // dedicated flex item that's `min-w-0 flex-1 sm:flex-initial`
              // the parent flex squeezes it next to the back button.
              <div className="min-w-0 flex-1 sm:flex-initial w-full sm:w-auto">
                <TikTokBroadcastSelector
                  rooms={rooms}
                  selectedRoomId={roomId}
                  onChange={(rid) => {
                    // pinRoom (not setRoomId) → freezes the rooms-poller's
                    // auto-advance so a new broadcast starting won't yank
                    // the user off their explicit selection.
                    pinRoom(rid);
                    // Different broadcast → drop any brush-selected range
                    // AND any calendar-picked day window. Without
                    // clearing dayWindow, the new broadcast would still
                    // be filtered to the OLD day's tz-bounds, hiding
                    // most of its events.
                    setCustomRange(null);
                    setBrushIndices(null);
                    setDayWindow(null);
                    setAggregatedRooms(null);
                  }}
                  isLiveRoom={(r) =>
                    !r.ended_at && !roomEndedHeuristic(r)
                  }
                />
              </div>
            )}
            {customRange && (
              <button
                type="button"
                onClick={() => {
                  setCustomRange(null);
                  setBrushIndices(null);
                }}
                className="inline-flex items-center gap-1 px-2 py-1 rounded font-mono text-[11px] bg-amber-50 text-amber-800 border border-amber-200 hover:bg-amber-100 dark:bg-amber-500/10 dark:border-amber-500/30"
                title="Clear chart range — return to entire broadcast"
              >
                <span className="truncate max-w-[18ch]">
                  Range: {customRange.label}
                </span>
                <span aria-hidden>×</span>
              </button>
            )}
            <Button variant="ghost" onClick={refresh} disabled={loading}>
              <RefreshCw className={loading ? 'animate-spin w-4 h-4' : 'w-4 h-4'} />
            </Button>
          </div>
        }
      />

      {/* TZ pill + WS indicator row — pulled out of the PageHeader actions
          slot so the action area stays focused on per-page controls
          (back, broadcast picker, range chip, refresh). Full-width with
          wrap so the two pills sit on their own line on mobile rather
          than competing with Refresh/Lives for header real-estate. */}
      <div className="flex flex-wrap items-center gap-2 mb-3 -mt-1">
        <TikTokTimezonePill compact />
        <TikTokRealtimeIndicator audience={readOnly ? 'public' : 'admin'} />
      </div>

      {/* Rich profile header + live-activity heatmap.
          Side-by-side on lg+, stacked on mobile. The heatmap uses
          `h-8` (rectangular) cells instead of `aspect-square` so the
          panel matches the profile card's height envelope on desktop
          — square cells would balloon vertically and dwarf the
          profile beside them. The lg:w-[420px] sidebar gives the
          heatmap room for ~5 columns × ~70px each with inline
          diamond counts readable at a glance. */}
      <div className="flex flex-col lg:flex-row gap-4 items-stretch">
        <div className="flex-1 min-w-0">
          <ProfileHeaderCard
            handle={handle}
            profile={hostProfile}
            recent={recent}
            selectedRoom={selectedRoom}
            readOnly={readOnly}
            activitySummary={activitySummary}
            onOpenHostProfile={
              hostProfile?.profile_user_id
                ? () =>
                    setSelectedGifter({
                      userId: String(hostProfile.profile_user_id),
                      uniqueId: hostProfile.unique_id ?? handle,
                      nickname: hostProfile.nickname ?? null,
                      // Lifetime counters aren't on the subscription row;
                      // modal renders "(·)" badges + populates totals
                      // from its own per-tab queries.
                      diamonds: undefined,
                      gifts: undefined,
                      comments: undefined,
                      // `scope: 'profile-only'` tells the modal-render
                      // block below to suppress the room/range props so
                      // the "Current" tab hides itself. The host's own
                      // profile is a general (cross-host) view; "what
                      // this user gifted in this room" makes no sense
                      // for the room's own host.
                      scope: 'profile-only',
                    })
                : undefined
            }
          />
        </div>
        <div className="lg:w-[420px] lg:shrink-0">
          <TikTokLiveCalendar
            handle={handle}
            weeks={5}
            rooms={rooms}
            onSummary={setActivitySummary}
            onSelectDay={(dayRooms, date) => {
              if (dayRooms.length === 0) return;
              // Resolve the day to UTC bounds in the user's zone now
              // so the picker, the day-aggregate fetch, and the tabs
              // all share the same `[since, until)` window — anything
              // that overlaps it (including tails of cross-midnight
              // broadcasts) is in scope.
              const bounds = zoneDayBoundsUtc(date, tz);
              if (dayRooms.length === 1) {
                pinRoom(dayRooms[0].room_id);
                setAggregatedRooms(null);
                // Keep `dayWindow` set so `effectiveWindow` (and
                // therefore chart + tabs) filter to the picked
                // tz-day rather than the broadcast's full extent.
                // `aggregatedRooms` stays null because there's only
                // one broadcast — the day-aggregate banner above
                // the chart is gated on `aggregatedRooms.length > 1`
                // and won't render here.
                setDayWindow({
                  dateYmd: date,
                  since: bounds.since,
                  until: bounds.until,
                });
                setCustomRange(null);
                setBrushIndices(null);
                return;
              }
              // Multiple broadcasts on this day → open the picker
              // with everything selected by default. The user can
              // narrow with checkboxes or use Select all / none.
              // Stash the bounds first so cancel cleanly drops them.
              setDayPickerBounds(bounds);
              setDayPicker({
                date,
                rooms: dayRooms,
                selected: new Set(dayRooms.map((r) => r.room_id)),
              });
              // Refetch with day bounds so the per-row chip totals
              // (diamonds / matches / likes) reflect only the slice
              // on the picked day — same window the chart will use
              // after the user confirms. A broadcast spanning
              // midnight typically shows >90% of its activity on one
              // side, so the unclipped chip can be off by an order
              // of magnitude. The legacy chips are kept until the
              // refetch resolves so the modal renders immediately.
              (async () => {
                try {
                  const clipped = await tiktokApi.listHostRooms(
                    handle, 200,
                    { since: bounds.since, until: bounds.until },
                  );
                  const byId = new Map(clipped.map((r) => [r.room_id, r]));
                  setDayPicker((p) => {
                    if (!p) return p;
                    return {
                      ...p,
                      rooms: p.rooms.map((r) => {
                        const c = byId.get(r.room_id);
                        if (!c) return r;
                        // Replace only the rollup fields; keep the
                        // start / end timestamps from the original
                        // (full-broadcast) row so the time labels
                        // continue to show the broadcast's actual
                        // span, not the day-clipped one.
                        return {
                          ...r,
                          diamonds: c.diamonds ?? r.diamonds,
                          matches: c.matches ?? r.matches,
                          likes: c.likes ?? r.likes,
                        };
                      }),
                    };
                  });
                } catch {
                  // Network blip → leave the unclipped chips up; the
                  // chart will still clip when the user confirms.
                }
              })();
            }}
          />
        </div>
      </div>

      {/* DAY-AGGREGATE banner. Visible when the user picked multiple
          broadcasts from the calendar's day-picker modal. Tells the
          user the chart is summed across N rooms, while the rest of
          the page is scoped to the first one. Reset returns to the
          single-room view on the first selected room. */}
      {aggregatedRooms && aggregatedRooms.length > 1 && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 dark:bg-emerald-500/10 dark:border-emerald-500/30 px-4 py-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div className="text-sm text-emerald-800 dark:text-emerald-200">
            <span className="font-mono text-[11px] mr-2">DAY VIEW</span>
            Chart and panels span <strong>{aggregatedRooms.length} broadcasts</strong>
            {' '}of this day.
          </div>
          <button
            type="button"
            onClick={() => {
              // Drop the day-aggregate scope, clear any brushed range,
              // unpin so the rooms-poller can auto-advance, and jump
              // directly to the most recent broadcast (rooms[] is
              // sorted newest-first by the listing endpoint).
              setAggregatedRooms(null);
              setDayWindow(null);
              setCustomRange(null);
              setBrushIndices(null);
              userPinnedRoomRef.current = false;
              const latest = rooms[0]?.room_id ?? null;
              if (latest && latest !== roomId) setRoomId(latest);
            }}
            className="text-xs font-mono text-emerald-700 hover:text-emerald-900 dark:text-emerald-300 dark:hover:text-emerald-100 underline decoration-dotted"
          >
            Return to current broadcast
          </button>
        </div>
      )}

      {/* CURRENT-LIVE banner. Shown only when the selected room is the
          one we believe is broadcasting right now (not ended + recent
          last_seen_at). */}
      {selectedRoom && !selectedRoom.ended_at && !roomEndedHeuristic(selectedRoom) && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 px-4 py-2.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 sm:gap-3">
          <div className="flex items-center gap-2.5 flex-wrap min-w-0">
            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-mono shrink-0">
              <span className="w-1.5 h-1.5 rounded-full bg-white mr-1 animate-pulse" />
              LIVE NOW
            </span>
            <span className="text-sm font-medium text-rose-700 dark:text-rose-300">
              @{handle} is broadcasting
            </span>
            {selectedRoom.title && (
              <span className="text-xs text-gray-600 truncate min-w-0">— {selectedRoom.title}</span>
            )}
          </div>
          <span className="text-[11px] font-mono text-gray-500 truncate sm:shrink-0">
            Room {selectedRoom.room_id}
          </span>
        </div>
      )}

      {/* PK battles panel. Always rendered when a broadcast is in
          scope so the user sees an explicit "no past battles" state
          instead of silently dropping the whole section (previously
          the panel was hidden when both active_match and the past
          list were empty, making it look like the page was missing
          something). */}
      {roomId && (
        <MatchesPanel
          activeMatch={stats?.active_match ?? null}
          pastMatches={matches}
          hostHandle={handle}
          hostProfile={hostProfile}
          onSelectMatch={setSelectedMatch}
          scopeLabel={chartViewLabel}
          readOnly={readOnly}
          // Forward the page-level gifter modal trigger so each
          // BattlerCard's Profile button surfaces the canonical
          // gift/comment history view.
          onSelectGifter={(u) =>
            setSelectedGifter({
              userId: u.userId,
              uniqueId: u.uniqueId,
              nickname: u.nickname,
              diamonds: undefined,
              gifts: undefined,
              comments: undefined,
              tab: 'gifts',
            })
          }
        />
      )}



      {/* Empty state */}
      {seriesByType.length === 0 && (
        <div className="card text-center py-10 text-sm text-gray-500">
          {loading ? 'Loading…' : 'No events in this window.'}
        </div>
      )}

      {/* Diamond value timeline — pinned at the top because $$$. */}
      {(diamondSeries.length > 0 && diamondSeries.some((v) => v > 0)) && (
        <section className="card">
          <div className="flex items-start justify-between mb-3 gap-3">
            <div className="min-w-0">
              <h2 className="auth-mono-label flex items-center gap-2">
                <Gem className="w-4 h-4 text-amber-500" />
                Gift value (diamonds)
              </h2>
              <p className="mt-1 text-[11px] font-mono text-gray-500 truncate">
                {chartViewLabel}
              </p>
            </div>
            <div className="flex items-center gap-3">
              {customRange && (
                <button
                  type="button"
                  onClick={() => {
                    setCustomRange(null);
                    setBrushIndices(null);
                  }}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-mono text-amber-800 hover:bg-amber-100 dark:text-amber-200 dark:hover:bg-amber-500/10"
                  title="Reset to full range"
                >
                  <X className="w-3 h-3" />
                  Reset
                </button>
              )}
              <span
                className="text-2xl font-bold tabular-nums text-amber-600"
                style={{ fontFamily: 'var(--font-mono-display)' }}
              >
                {(stats?.diamonds_total ?? 0).toLocaleString()} 💎
              </span>
            </div>
          </div>
          {customRange && (
            <div className="mb-2 flex items-center gap-2 text-xs px-2.5 py-1.5 rounded bg-amber-50 border border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/30">
              <span className="font-mono text-amber-800 dark:text-amber-200">
                Selected range:
              </span>
              <span className="font-mono text-amber-900 dark:text-amber-100">
                {customRange.label}
              </span>
            </div>
          )}
          <EChartsRangeArea
            points={diamondSeries}
            labels={xLabels}
            color="#f59e0b"
            height={200}
            selectedRange={brushIndices}
            onRangeSelect={onBrushChange}
            highlightRange={chartHighlight}
            bands={chartBands}
          />
          <p className="mt-2 text-[11px] font-mono text-gray-500">
            Click and drag inside the chart to filter the page to a custom time range.
          </p>

          {/* Per-broadcast contribution strip (day-aggregate mode).
              One chip per room with start→end time, 💎 contribution,
              and a colored dot. Clicking a chip BLINKS that broadcast's
              slice on the chart so you can see when its contribution
              landed — it doesn't switch rooms (use the dropdown or the
              picker for that). Hidden in single-room mode. */}
          {aggregatedRoomsChrono && aggregatedRoomsChrono.length > 1 && (
            <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-100/30">
              <div className="auth-mono-label mb-1.5">
                Broadcasts in this view
              </div>
              <div className="flex items-center gap-1.5 flex-wrap">
                {aggregatedRoomsChrono.map((r, idx) => {
                  const startLabel = fmtHM(r.first_seen_at, tz);
                  const endLabel = fmtHM(
                    r.ended_at ?? r.last_seen_at ?? null,
                    tz,
                  );
                  const tone = BROADCAST_PALETTE[idx % BROADCAST_PALETTE.length];
                  return (
                    <button
                      key={r.room_id}
                      type="button"
                      onClick={() => blinkBroadcast(r, tone)}
                      className="inline-flex items-center gap-1.5 px-2 py-1 rounded font-mono text-[11px] border border-gray-200 hover:bg-gray-100 dark:hover:bg-gray-100/30 text-gray-700 dark:text-gray-300 transition-colors"
                      title={`Blink this broadcast's range on the chart — ${r.title || r.room_id}`}
                    >
                      <span
                        aria-hidden
                        className="inline-block w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: tone }}
                      />
                      <span className="font-medium">
                        {startLabel} → {endLabel}
                      </span>
                      <span className="text-amber-700 dark:text-amber-300 tabular-nums">
                        💎 {compactCount(r.diamonds ?? 0)}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      )}

      {/* All events overlay — single chart with a toggle row for each
          event type. Click a pill to hide/show that series in the chart;
          replaces the stacked per-type cards (one big chart with the
          ability to scope to whichever types matter at the moment). */}
      {seriesByType.length > 0 && (
        <section className="card">
          <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
            <h2 className="auth-mono-label">
              All events overlay — {effectiveWindow.label.toLowerCase()}
            </h2>
            {stats && (
              <span className="text-xs text-gray-500 font-mono">
                {sumBy(stats.counts_window)} events in window
              </span>
            )}
          </div>

          {/* Toggle row. Each pill: dot in series colour, type label,
              total count. Hidden series → desaturated. Two helper
              buttons (All / None) for fast scoping. */}
          <div className="mb-3 flex items-center gap-1.5 flex-wrap">
            <button
              type="button"
              onClick={() => setHiddenSeries(new Set())}
              className="text-[10px] font-mono px-1.5 py-1 rounded text-gray-500 hover:text-gray-900 hover:bg-gray-50"
            >
              all
            </button>
            <button
              type="button"
              onClick={() =>
                setHiddenSeries(new Set(seriesByType.map((s) => s.key)))
              }
              className="text-[10px] font-mono px-1.5 py-1 rounded text-gray-500 hover:text-gray-900 hover:bg-gray-50"
            >
              none
            </button>
            <span className="w-px h-4 bg-gray-200 mx-1" aria-hidden />
            {seriesByType.map((s) => {
              const isHidden = hiddenSeries.has(s.key);
              return (
                <button
                  key={s.key}
                  type="button"
                  onClick={() =>
                    setHiddenSeries((prev) => {
                      const next = new Set(prev);
                      if (next.has(s.key)) next.delete(s.key);
                      else next.add(s.key);
                      return next;
                    })
                  }
                  className={
                    'inline-flex items-center gap-1.5 px-2 py-1 rounded font-mono text-[11px] border transition-colors ' +
                    (isHidden
                      ? 'border-gray-200 text-gray-400 bg-white hover:bg-gray-50'
                      : 'border-gray-200 bg-gray-50 text-gray-900 hover:bg-gray-100')
                  }
                  title={isHidden ? `Show ${s.label}` : `Hide ${s.label}`}
                >
                  <span
                    aria-hidden
                    className="inline-block w-2 h-2 rounded-full"
                    style={{
                      backgroundColor: isHidden ? '#d4d4d4' : s.color,
                    }}
                  />
                  <span>{s.label}</span>
                  <span
                    className={
                      'tabular-nums ' + (isHidden ? 'text-gray-400' : 'text-gray-500')
                    }
                  >
                    {(totals[s.key] ?? 0).toLocaleString()}
                  </span>
                </button>
              );
            })}
          </div>

          {visibleSeries.length === 0 ? (
            <p className="py-8 text-center text-xs text-gray-400 font-mono">
              No series selected — click a pill above.
            </p>
          ) : (
            <MultiLineChart
              series={visibleSeries.map(({ key, label, values, color }) => ({
                key,
                label,
                values,
                color,
              }))}
              labels={xLabels}
              height={260}
            />
          )}
        </section>
      )}

      {/* Diamonds by recipient — auto-hides for solo broadcasts where
          no `to_user` targeting was captured. */}
      <TikTokRoomRecipientsCard
        roomId={roomId}
        range={resolveRange(effectiveWindow, selectedRoom)}
        refreshKey={eventsRefreshKey}
        onSelectUser={setSelectedGifter}
      />

      {/* Top gifters / Comments — tabbed card */}
      <section className="card">
        <div className="flex items-center gap-1 mb-3 border-b border-gray-200">
          <CardTabButton
            active={giftersTab === 'gifters'}
            onClick={() => setGiftersTab('gifters')}
          >
            Top gifters
            {topGiftersTotal != null && (
              <span className="ml-1.5 text-[10px] font-mono text-gray-500">
                ({topGiftersTotal.toLocaleString()})
              </span>
            )}
          </CardTabButton>
          <CardTabButton
            active={giftersTab === 'comments'}
            onClick={() => setGiftersTab('comments')}
          >
            Comments
            {commentsTotal != null && (
              <span className="ml-1.5 text-[10px] font-mono text-gray-500">
                ({commentsTotal.toLocaleString()})
              </span>
            )}
          </CardTabButton>
          <CardTabButton
            active={giftersTab === 'crosslive'}
            onClick={() => setGiftersTab('crosslive')}
          >
            Cross-live
            {crossLiveTotal != null && (
              <span className="ml-1.5 text-[10px] font-mono text-gray-500">
                ({crossLiveTotal.toLocaleString()})
              </span>
            )}
          </CardTabButton>
          <button
            type="button"
            onClick={() => {
              setEventsRefreshKey((k) => k + 1);
              if (roomId) fetchStats(roomId, effectiveWindow, selectedRoom);
            }}
            className="ml-auto mr-1 mb-px inline-flex items-center gap-1 px-2 py-1 text-[11px] text-gray-500 hover:text-gray-900 rounded transition-colors"
            title={
              giftersTab === 'gifters'
                ? 'Refresh top gifters'
                : giftersTab === 'comments'
                  ? 'Refresh comments'
                  : 'Refresh cross-live gifters'
            }
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Scope chips. The first chip reflects the *chart's* active
            scope (single live / day-aggregate / brushed range) so the
            operator can tell which dataset the tables below sum over.
            "All time" is the second chip — a hard override that
            unions every recorded room for this host regardless of
            the chart's selection. */}
        <div className="flex items-center gap-2 mb-3 text-[11px] font-mono">
          <span className="text-gray-500 uppercase tracking-wider">Scope:</span>
          {(() => {
            // Label the chip from the actual chart scope, in priority
            // order. We name the picked DATE (e.g. "May 7 · 4
            // broadcasts") rather than the generic "This day" because
            // calendar picks can target any historic day — "this day"
            // sounds like today and misleads.
            let liveLabel = 'This live';
            if (customRange) {
              liveLabel = 'Selected range';
            } else if (dayWindow && aggregatedRooms && aggregatedRooms.length > 1) {
              const datePart = fmtShortDate(dayWindow.since, tz);
              liveLabel = `${datePart} · ${aggregatedRooms.length} broadcasts`;
            } else if (aggregatedRooms && aggregatedRooms.length > 1) {
              liveLabel = `${aggregatedRooms.length} broadcasts`;
            } else if (selectedRoom && selectedRoom.room_id !== roomId) {
              // The path roomId is the latest broadcast, but the user
              // pinned a different one via the broadcast selector.
              liveLabel = 'Selected broadcast';
            }
            return (
              <button
                type="button"
                onClick={() => setTabsScope('live')}
                className={`inline-flex items-center px-2 py-0.5 rounded-full border transition-colors ${
                  tabsScope === 'live'
                    ? 'bg-primary-100 dark:bg-primary-500/15 text-primary-700 dark:text-primary-300 border-primary-200 dark:border-primary-500/30'
                    : 'bg-white dark:bg-white/[0.03] text-gray-600 border-gray-200 hover:bg-gray-50'
                }`}
                aria-pressed={tabsScope === 'live'}
                title={chartViewLabel}
              >
                {liveLabel}
              </button>
            );
          })()}
          <button
            type="button"
            onClick={() => setTabsScope('alltime')}
            className={`inline-flex items-center px-2 py-0.5 rounded-full border transition-colors ${
              tabsScope === 'alltime'
                ? 'bg-primary-100 dark:bg-primary-500/15 text-primary-700 dark:text-primary-300 border-primary-200 dark:border-primary-500/30'
                : 'bg-white dark:bg-white/[0.03] text-gray-600 border-gray-200 hover:bg-gray-50'
            }`}
            aria-pressed={tabsScope === 'alltime'}
            title="Sum across every recorded broadcast for this host"
          >
            All time
            {tabsScope === 'alltime' && allHostRoomsLoading && (
              <Loader2 className="w-3 h-3 ml-1.5 animate-spin" />
            )}
            {tabsScope === 'alltime' && allHostRoomIds && (
              <span className="ml-1.5 opacity-70 tabular-nums">
                ({allHostRoomIds.length} rooms)
              </span>
            )}
          </button>
        </div>

        {giftersTab === 'gifters' && (
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            {/* LEFT column: the existing top-gifters list (60% of the
                row on md+, i.e. 3/5). The right column gets the
                remaining 40% (2/5). Stays unchanged otherwise — the
                right column is purely additive. */}
            <div className="md:col-span-3 min-w-0">
              <TikTokRoomGiftersTable
                roomId={roomId}
                extraRoomIds={effectiveExtraRoomIds}
                range={effectiveRange}
                refreshKey={eventsRefreshKey}
                onSelectGifter={setSelectedGifter}
                onTotalChange={setTopGiftersTotal}
                // Bubble the table's current page into parent state
                // so the donut card on the right consumes the same
                // rows — single `getRoomGifters` request feeds both.
                onItemsChange={setTopGiftersItems}
                onLoadingChange={setTopGiftersLoading}
              />
            </div>

            {/* RIGHT column: pie cards for the per-user aggregates we
                actually have. Today that's just gifters
                (`stats.top_gifters[0]` vs `stats.diamonds_total`). The
                commenter + liker aggregates aren't tracked per-user yet
                (only per-event totals), so we collapse them into a
                single "coming soon" notice instead of shipping two
                permanently-empty donut rings.
                Drops below the list on narrow viewports. */}
            <div className="md:col-span-2 flex flex-col gap-3 min-w-0">
              <TopUserPieCard
                title="Top Gifter"
                icon={<Crown className="w-3.5 h-3.5 text-amber-500" />}
                items={topGiftersItems}
                loading={topGiftersLoading}
              />
              {/* Coming-soon placeholder for per-user comment/like
                  aggregates — uses the project's established Lock +
                  left-border-accent pattern for not-yet-shipped state. */}
              <div className="rounded-lg border border-gray-200 dark:border-gray-100/10 bg-white dark:bg-gray-100/[0.05] border-l-4 border-l-gray-300 dark:border-l-gray-100/20 p-3">
                <div className="auth-mono-label flex items-center gap-1.5 mb-1.5 text-gray-500">
                  <Lock className="w-3 h-3" />
                  Coming soon
                </div>
                <p className="text-[11px] text-gray-500 leading-snug">
                  Top commenter &amp; top liker aggregates aren't tracked per-user yet — only per-event totals.
                </p>
              </div>
            </div>
          </div>
        )}

        {giftersTab === 'comments' && (
          <TikTokRoomCommentsTimeline
            roomId={roomId}
            extraRoomIds={effectiveExtraRoomIds}
            range={effectiveRange}
            refreshKey={eventsRefreshKey}
            onTotalChange={setCommentsTotal}
            onSelectUser={(u) =>
              setSelectedGifter({
                userId: u.userId,
                uniqueId: u.uniqueId,
                nickname: u.nickname,
                // Counters left undefined — the comments timeline only
                // knows the user's identity, not their lifetime gift /
                // comment totals. Forcing 0 here made the tab badges
                // render "(0)" instead of "(·)". The per-tab search's
                // own countEvents call still populates the pagination
                // total accurately once data loads.
                diamonds: undefined,
                gifts: undefined,
                comments: undefined,
                tab: u.tab ?? 'comments',
              })
            }
          />
        )}

        {/* Cross-live: gifters of this host who also gift in other
            tracked lives. The endpoint is host-scoped (not room-scoped)
            so the table reads the URL handle directly — it ignores the
            chart's range / scope chips above on purpose. The cross-
            live concept summarises a viewer's behaviour ACROSS lives,
            not within one broadcast window. */}
        {giftersTab === 'crosslive' && (
          <TikTokRoomCrossLiveGiftersTable
            handle={handle}
            refreshKey={eventsRefreshKey}
            onSelectCrossGifter={setSelectedCrossUserId}
            onTotalChange={setCrossLiveTotal}
          />
        )}

        <TikTokGifterDetailModal
          isOpen={selectedCrossUserId !== null}
          userId={selectedCrossUserId}
          onClose={() => setSelectedCrossUserId(null)}
          defaultTab="profile"
        />

      </section>

      {/* Recent activity tail — populated EXCLUSIVELY by the WebSocket
          stream. The public page intentionally skips the WS (see the
          `if (readOnly) return;` guard near the WS open call) because
          the WS endpoint is admin-auth-only and would leak non-public
          handles' real-time feed to anonymous viewers. With no other
          data source the section would sit on "Waiting for events…"
          forever, so we hide it entirely in readOnly mode. The other
          panels (gifters, comments timeline, match list) already cover
          "what's happening" via REST polling. */}
      {!readOnly && (
        <section className="card">
          <h2 className="auth-mono-label mb-2">Recent activity</h2>
          <ul className="space-y-1 text-xs font-mono max-h-72 overflow-auto">
            {recent.length === 0 && (
              <li className="text-gray-500">Waiting for events…</li>
            )}
            {recent.map((e, i) => {
              // When the event carries an identifiable actor, surface
              // a small profile button so the operator can drill into
              // that viewer's gift/comment history without searching
              // the gifters tab. We only have payload.user.nickname
              // for display — user_id comes through on the WS envelope.
              const u =
                (e.payload?.user as
                  | { unique_id?: string; nickname?: string }
                  | undefined) || undefined;
              const uniqueId = u?.unique_id ?? null;
              const nickname = u?.nickname ?? null;
              const userId = e.user_id;
              const hasActor = !!(userId && (uniqueId || nickname));
              return (
                <li key={i} className="flex items-start gap-1.5 min-w-0">
                  <span
                    className="shrink-0"
                    style={{ color: eventColor(e.type) }}
                  >
                    {e.type}
                  </span>
                  <span className="text-gray-700 min-w-0 flex-1 truncate">
                    {summarizeEvent(e)}
                  </span>
                  {hasActor && (
                    <button
                      type="button"
                      onClick={() =>
                        setSelectedGifter({
                          userId,
                          uniqueId,
                          nickname,
                          // Lifetime counters aren't in the WS payload —
                          // the modal renders "(·)" badges until its
                          // own per-tab queries populate the totals.
                          diamonds: undefined,
                          gifts: undefined,
                          comments: undefined,
                          tab: e.type === 'comment' ? 'comments' : 'gifts',
                        })
                      }
                      className="shrink-0 inline-flex items-center text-gray-500 hover:text-primary-600 transition-colors"
                      title={`Open profile — ${nickname || `@${uniqueId}` || userId}`}
                      aria-label="Open gifter profile"
                    >
                      <User className="w-3.5 h-3.5" />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <TikTokGifterDetailModal
        isOpen={selectedGifter !== null}
        onClose={() => setSelectedGifter(null)}
        userId={selectedGifter?.userId ?? null}
        uniqueId={selectedGifter?.uniqueId ?? null}
        nickname={selectedGifter?.nickname ?? null}
        // Don't default to 0 — for clicks from the comments timeline
        // we don't know the user's lifetime counters, and showing
        // "(0)" on the tab badges is misleading. Leaving these
        // undefined lets the modal render `(·)` instead and the
        // per-tab search query populates the real total in
        // pagination once data loads.
        diamondsTotal={selectedGifter?.diamonds}
        giftsCount={selectedGifter?.gifts}
        commentsCount={selectedGifter?.comments}
        // Profile-only mode (the host's own "Gifter Profile" button)
        // suppresses ALL scope props so `currentAvailable` in the
        // modal resolves to false → the "Current" tab strip hides
        // entirely and only the Profile (cross-host) view renders.
        // Default-tab pinned to 'profile' for the same reason.
        defaultTab={selectedGifter?.scope === 'profile-only' ? 'profile' : 'current'}
        currentInnerTab={selectedGifter?.tab ?? 'gifts'}
        roomId={selectedGifter?.scope === 'profile-only' ? null : roomId}
        // Pass the SAME room set the parent gifters/comments table
        // queries against (`effectiveExtraRoomIds`). In live scope
        // this is the day-aggregate extras (or undefined for a solo
        // broadcast); in all-time scope it's every recorded room for
        // this host. Without this, clicking a gifter surfaced by the
        // all-time table would query only the path roomId and the
        // modal would render empty for gifters who only contributed
        // in *other* broadcasts.
        //
        // When the click came from the match modal's donor panel
        // for an opponent-side gifter, `selectedGifter.extraRoomIds`
        // carries the rival's `room_id` (sibling-stream room). Merge
        // it in so opponent donors find their gifts — those events
        // live in the rival's broadcast, not the current page's room.
        //
        // In profile-only mode, drop the room set entirely so the
        // modal's Current tab disappears.
        extraRoomIds={(() => {
          if (selectedGifter?.scope === 'profile-only') return undefined;
          const base = effectiveExtraRoomIds ?? [];
          const extras = selectedGifter?.extraRoomIds ?? [];
          if (extras.length === 0) return effectiveExtraRoomIds;
          return Array.from(new Set([...base, ...extras]));
        })()}
        // Human-readable label for the room set so the modal's header
        // banner + scope chip name the dataset accurately. Mirrors the
        // scope-chip labelling above so the modal's framing matches
        // the parent table.
        roomSetLabel={(() => {
          if (selectedGifter?.scope === 'profile-only') return undefined;
          if (tabsScope === 'alltime') {
            const n = allHostRoomIds?.length ?? 0;
            return n > 0
              ? `All time · ${n} broadcast${n === 1 ? '' : 's'}`
              : 'All time';
          }
          if (customRange) {
            return 'Selected range';
          }
          if (dayWindow && aggregatedRooms && aggregatedRooms.length > 1) {
            const datePart = fmtShortDate(dayWindow.since, tz);
            return `${datePart} · ${aggregatedRooms.length} broadcasts`;
          }
          if (aggregatedRooms && aggregatedRooms.length > 1) {
            return `${aggregatedRooms.length} broadcasts`;
          }
          return undefined; // default "This broadcast"
        })()}
        windowSince={selectedGifter?.scope === 'profile-only' ? null : (selectedGifter?.since ?? null)}
        windowUntil={selectedGifter?.scope === 'profile-only' ? null : (selectedGifter?.until ?? null)}
        windowLabel={selectedGifter?.scope === 'profile-only' ? undefined : selectedGifter?.windowLabel}
        currentHandle={handle}
        readOnly={readOnly}
      />

      <TikTokMatchEventsModal
        isOpen={selectedMatch !== null}
        onClose={() => setSelectedMatch(null)}
        match={selectedMatch}
        hostHandle={handle}
        onSelectGifter={setSelectedGifter}
        onSelectMatch={setSelectedMatch}
        readOnly={readOnly}
      />

      <Modal
        isOpen={dayPicker !== null}
        onClose={() => {
          setDayPicker(null);
          setDayPickerBounds(null);
        }}
        title={
          dayPicker
            ? `${dayPicker.rooms.length} broadcasts on ${formatLongDateLocal(dayPicker.date)}`
            : ''
        }
        className="max-w-lg"
        footer={
          <div className="flex items-center justify-between gap-2 w-full">
            <span className="text-xs font-mono text-gray-500">
              {dayPicker?.selected.size ?? 0} of {dayPicker?.rooms.length ?? 0} selected
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                onClick={() => {
                  setDayPicker(null);
                  setDayPickerBounds(null);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={!dayPicker || dayPicker.selected.size === 0}
                onClick={() => {
                  if (!dayPicker) return;
                  const picked = dayPicker.rooms.filter((r) =>
                    dayPicker.selected.has(r.room_id),
                  );
                  if (picked.length === 0) return;
                  // Always pin the first (most recent) selected room
                  // so room-scoped panels have something to render.
                  pinRoom(picked[0].room_id);
                  setCustomRange(null);
                  setBrushIndices(null);
                  // 2+ rooms → enter day-aggregate chart mode. 1 → off.
                  setAggregatedRooms(picked.length > 1 ? picked : null);
                  // Promote the picker's zone-aware bounds onto
                  // dayWindow so the day-aggregate fetch + tabs use
                  // them as the canonical [since, until). Only when
                  // we're actually entering aggregate mode — single
                  // broadcast view scopes itself to that broadcast's
                  // own range.
                  if (picked.length > 1 && dayPickerBounds) {
                    setDayWindow({
                      dateYmd: dayPicker.date,
                      since: dayPickerBounds.since,
                      until: dayPickerBounds.until,
                    });
                  } else {
                    setDayWindow(null);
                  }
                  setDayPicker(null);
                  setDayPickerBounds(null);
                }}
              >
                Show {dayPicker?.selected.size && dayPicker.selected.size > 1
                  ? `${dayPicker.selected.size} broadcasts`
                  : 'broadcast'}
              </Button>
            </div>
          </div>
        }
      >
        {dayPicker && (
          <div className="flex flex-col gap-2">
            <p className="text-xs text-gray-500">
              Pick one or more broadcasts. Multiple → the chart aggregates
              their buckets (other panels follow the first selected).
            </p>
            <div className="flex items-center gap-2 text-[11px] font-mono">
              <button
                type="button"
                onClick={() => setDayPicker((p) => p && {
                  ...p,
                  selected: new Set(p.rooms.map((r) => r.room_id)),
                })}
                className="px-2 py-0.5 rounded border border-gray-200 hover:bg-gray-100 dark:hover:bg-gray-100/30"
              >
                Select all
              </button>
              <button
                type="button"
                onClick={() => setDayPicker((p) => p && {
                  ...p,
                  selected: new Set(),
                })}
                className="px-2 py-0.5 rounded border border-gray-200 hover:bg-gray-100 dark:hover:bg-gray-100/30"
              >
                Select none
              </button>
            </div>

            {dayPicker.rooms.map((r) => {
              const start = r.first_seen_at ? new Date(r.first_seen_at) : null;
              const end = r.ended_at
                ? new Date(r.ended_at)
                : r.last_seen_at
                  ? new Date(r.last_seen_at)
                  : null;
              // The picked calendar day in the user's timezone is the
              // [dayStartUtc, dayEndUtc) window everything in this row
              // is clipped to. If the broadcast started before midnight
              // the displayed "start" is 00:00; if it ran past midnight
              // the displayed "end" is 23:59:59. Duration becomes the
              // ON-DAY slice — matching the counters chips next to it
              // and the chart the user lands on after confirming.
              const dayStartUtc = dayPickerBounds
                ? new Date(dayPickerBounds.since)
                : null;
              const dayEndUtc = dayPickerBounds
                ? new Date(dayPickerBounds.until)
                : null;
              const startedBefore = !!(
                start && dayStartUtc && start.getTime() < dayStartUtc.getTime()
              );
              const endedAfter = !!(
                end && dayEndUtc && end.getTime() > dayEndUtc.getTime()
              );
              const clippedStart = startedBefore ? dayStartUtc : start;
              // dayEndUtc is the exclusive `until` (midnight of NEXT
              // day); display 23:59 to read as inclusive end-of-day.
              const clippedEnd = endedAfter && dayEndUtc
                ? new Date(dayEndUtc.getTime() - 60_000)
                : end;
              const startLabel = fmtHM(clippedStart, tz);
              const endLabel = fmtHM(clippedEnd, tz);
              const durMs =
                clippedStart && clippedEnd
                  ? Math.max(0, clippedEnd.getTime() - clippedStart.getTime())
                  : 0;
              const durMin = Math.floor(durMs / 60000);
              const isChecked = dayPicker.selected.has(r.room_id);
              return (
                <label
                  key={r.room_id}
                  className={
                    'w-full px-3 py-2.5 rounded-md border cursor-pointer ' +
                    'flex items-start gap-3 transition-colors ' +
                    (isChecked
                      ? 'border-primary-300 bg-primary-50 dark:bg-primary-500/10'
                      : 'border-gray-200 hover:bg-gray-100 dark:hover:bg-gray-100/30')
                  }
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() =>
                      setDayPicker((p) => {
                        if (!p) return p;
                        const next = new Set(p.selected);
                        if (next.has(r.room_id)) next.delete(r.room_id);
                        else next.add(r.room_id);
                        return { ...p, selected: next };
                      })
                    }
                    className="mt-1 shrink-0 accent-primary-600"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-sm">
                      {startLabel} → {endLabel}
                      <span className="ml-2 text-[10px] font-mono text-gray-500">
                        {durMin > 0
                          ? durMin >= 60
                            ? `${Math.floor(durMin / 60)}h ${durMin % 60}m`
                            : `${durMin}m`
                          : '—'}
                      </span>
                      {(startedBefore || endedAfter) && (
                        <span
                          className="ml-2 text-[10px] font-mono text-amber-700 dark:text-amber-300"
                          title={
                            'Broadcast extends outside this calendar day; '
                            + 'times + counters show only the slice on '
                            + formatLongDateLocal(dayPicker.date)
                          }
                        >
                          (clipped)
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] font-mono text-gray-500 truncate">
                      {r.title || `Room ${r.room_id}`}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-wrap text-[10px] font-mono shrink-0">
                    {!!r.diamonds && (
                      <span className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                        💎 {compactCount(r.diamonds)}
                      </span>
                    )}
                    {!!r.matches && (
                      <span className="px-1.5 py-0.5 rounded bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
                        ⚔ {r.matches}
                      </span>
                    )}
                    {!!r.likes && (
                      <span className="px-1.5 py-0.5 rounded bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">
                        ❤ {compactCount(r.likes)}
                      </span>
                    )}
                  </div>
                </label>
              );
            })}
          </div>
        )}
      </Modal>
    </PageShell>
  );
}

// ── helpers ─────────────────────────────────────────────────────────

/** Distinct, accessible palette for per-broadcast colour-coding in the
 *  day-aggregate strip (and any future stacked-band view). Cycles when
 *  a day has more broadcasts than colours; in practice 8+ broadcasts
 *  on one day is rare. */
const BROADCAST_PALETTE = [
  '#0ea5e9', // sky-500
  '#a855f7', // violet-500
  '#10b981', // emerald-500
  '#ef4444', // rose-500
  '#f59e0b', // amber-500
  '#14b8a6', // teal-500
  '#ec4899', // pink-500
  '#6366f1', // indigo-500
];

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

/** "2026-05-08" → "Friday, May 8, 2026" using the browser's locale.
 *  Used by the day-picker modal title; we can't reuse the calendar's
 *  helper because that one parses the same string format with a Date
 *  but doesn't expose itself outside the component. */
function formatLongDateLocal(iso: string): string {
  const [y, m, d] = iso.split('-').map((x) => Number(x));
  const dt = new Date(y, (m || 1) - 1, d || 1);
  return dt.toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function sumBy(o: Record<string, number>): number {
  let s = 0;
  for (const k in o) s += o[k];
  return s;
}

// Treat a room as ended when its last_seen_at is older than 5 minutes —
// covers cases where TikTok never sent a LiveEnd event but the room is
// effectively closed (most common reason: backend restart during a live).
const STALE_ROOM_MS = 5 * 60 * 1000;
function roomEndedHeuristic(room: TikTokRoom): boolean {
  if (room.ended_at) return true;
  if (!room.last_seen_at) return false;
  const ageMs = Date.now() - new Date(room.last_seen_at).getTime();
  return ageMs > STALE_ROOM_MS;
}

/** Event types whose chart counters we merge client-side from WS.
 *
 *  These match the names the backend uses in `tiktok_events.type`
 *  and the keys it emits in `TikTokRoomStats.buckets.by_type`. Other
 *  WS event types — match_*, viewer_count, room_info, live_end,
 *  room_pause, room_unpause — are handled separately:
 *    - match_* triggers a full `fetchStats` (the active_match state
 *      changes shape; safer to refetch than to merge).
 *    - viewer_count carries a snapshot value, not a delta — bound
 *      elsewhere from the live sparkline path.
 *    - room_info / live_end / room_pause / room_unpause change room-
 *      level state, not the chart counters.
 */
const MERGEABLE_WS_TYPES = new Set([
  'gift',
  'comment',
  'join',
  'like',
  'follow',
  'share',
]);

/**
 * Apply a single WS event to a `TikTokRoomStats` snapshot, producing
 * a new snapshot with the event's contribution merged into the
 * appropriate chart bucket.
 *
 * Each event row in `tiktok_events` is counted ONCE in
 * `buckets.by_type[type][idx]` (the backend's `COUNT(*) GROUP BY type`
 * doesn't multiply by `repeat_count`). So this merger increments the
 * per-type bucket counter by exactly 1 per WS event — matching the
 * server-side semantic so the next reconcile poll lines up cleanly.
 *
 * Gift is the only type that also moves the diamond chart:
 *   diamonds[idx]   += diamond_count * repeat_count
 *   diamonds_total  += diamond_count * repeat_count
 * (other types don't contribute to the diamond line.)
 *
 * Reconciliation: the next `fetchStats` returns authoritative
 * server state and replaces `stats` wholesale, wiping any merged
 * deltas. Drift between polls is bounded by one poll cycle — same
 * staleness the page had with WS off. Optimistic merge gives the
 * "live ticks" UX without changing the truth.
 *
 * Bucket selection rule: pick the bucket whose start time is the
 * largest one ≤ `Date.now()`. WS events arrive near-real-time, so
 * `Date.now()` is a fine approximation for the event time.
 *
 * No-ops when stats is null-ish, the event type isn't mergeable, or
 * the buckets array is empty.
 */
function applyEventDeltaToStats(
  stats: TikTokRoomStats,
  msg: TikTokWsEvent,
): TikTokRoomStats {
  if (!MERGEABLE_WS_TYPES.has(msg.type)) return stats;
  const starts = stats.buckets?.starts ?? [];
  if (starts.length === 0) return stats;

  // Find the bucket the event falls into. Walk backwards because
  // the most-recent buckets are the common case.
  const eventMs = Date.now();
  let idx = 0;
  for (let i = starts.length - 1; i >= 0; i--) {
    const startMs = new Date(starts[i]).getTime();
    if (Number.isFinite(startMs) && eventMs >= startMs) {
      idx = i;
      break;
    }
  }

  // Counter delta: every event row contributes +1 to its type's
  // bucket count and the matching counts_window / counts_total
  // entries.
  const prevByType = stats.buckets.by_type ?? {};
  const typeArr = (prevByType[msg.type] ?? new Array(starts.length).fill(0)).slice();
  typeArr[idx] = (typeArr[idx] ?? 0) + 1;
  const newByType = { ...prevByType, [msg.type]: typeArr };

  // Diamond delta: gift-only. Other types leave the diamond column
  // alone. We copy `diamonds[]` either way so the bucket-array
  // reference flips and downstream memos see a fresh value.
  const payload = (msg.payload ?? {}) as Record<string, unknown>;
  const diamondPer = Number(payload.diamond_count ?? 0);
  const repeat = Number(payload.repeat_count ?? 1);
  const diamondDelta =
    msg.type === 'gift' && Number.isFinite(diamondPer) && Number.isFinite(repeat) && diamondPer > 0
      ? diamondPer * repeat
      : 0;
  const newDiamonds = stats.buckets.diamonds.slice();
  if (diamondDelta > 0) {
    newDiamonds[idx] = (newDiamonds[idx] ?? 0) + diamondDelta;
  }

  return {
    ...stats,
    diamonds_total: (stats.diamonds_total ?? 0) + diamondDelta,
    counts_window: {
      ...stats.counts_window,
      [msg.type]: (stats.counts_window?.[msg.type] ?? 0) + 1,
    },
    counts_total: {
      ...stats.counts_total,
      [msg.type]: (stats.counts_total?.[msg.type] ?? 0) + 1,
    },
    buckets: {
      ...stats.buckets,
      diamonds: newDiamonds,
      by_type: newByType,
    },
  };
}

// ── ProfileHeaderCard ───────────────────────────────────────────────
//
// Rich profile header for the live-detail page: avatar, nickname +
// verified, follower / following / video / like counters, bio, current
// live state (with room id when broadcasting), and a freshness badge
// showing how long ago the last event landed.

interface ProfileHeaderCardProps {
  handle: string;
  profile: TikTokSubscription | null;
  recent: TikTokWsEvent[];
  selectedRoom: TikTokRoom | null;
  /** When true, suppress operator-only chrome: the listener-status
   *  health pills (Worker hb / Last event), the probe-debug button +
   *  modal (which read worker_log), and skip the listenerStatus poll
   *  entirely (the public namespace doesn't expose it). */
  readOnly?: boolean;
  /** Last-30-days activity summary emitted by `TikTokLiveCalendar`
   *  via its `onSummary` callback. Rendered as a single chip in the
   *  card header so the profile and the heatmap stay separated
   *  visually but share the headline number. `null` while the
   *  calendar fetch is in flight. */
  activitySummary?: import('@admin/components/TikTokLiveCalendar').TikTokLiveActivitySummary | null;
  /** Opens the host's gifter profile modal — same modal used for any
   *  user across the page, just pointed at the host themselves. Lets
   *  the operator see this host's cross-live gifter footprint (if the
   *  host has also gifted in any other monitored live). */
  onOpenHostProfile?: () => void;
}

function ProfileHeaderCard({
  handle,
  profile,
  recent,
  selectedRoom,
  readOnly = false,
  activitySummary = null,
  onOpenHostProfile,
}: ProfileHeaderCardProps) {
  const tiktokApi = useTikTokApi();
  // Re-render once a second so the "last event Xs ago" stays accurate
  // even when no new events arrive.
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const [debugOpen, setDebugOpen] = useState(false);

  // Poll the listener-status endpoint so we can show this handle's
  // backend-side health: the worker's heartbeat age (is the listener
  // process alive) and the session's last_event_age_s (when did the
  // worker last ingest an event for THIS handle). The WS-derived
  // `lastEventAgeS` below only sees events that arrived after the page
  // loaded — these two come from the worker's own counters and survive
  // page refreshes.
  //
  // Skipped in read-only mode: the public namespace doesn't surface
  // worker internals, and the pills + probe-debug button that consume
  // this data are hidden below.
  const [listenerStatus, setListenerStatus] = useState<
    import('@admin/services/tiktok').TikTokListenerStatus | null
  >(null);
  useEffect(() => {
    if (readOnly) return;
    let cancelled = false;
    const tick = () => {
      tiktokApi
        .listenerStatus()
        .then((r) => {
          if (!cancelled) setListenerStatus(r);
        })
        .catch(() => {
          /* keep stale status on transient error */
        });
    };
    tick();
    const t = setInterval(tick, 15_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
    // tiktokApi is stable per provider; safe to leave out of deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly]);

  // Find this handle's session entry across all workers, and the
  // worker that owns it (for heartbeat).
  const { sessionForHandle, workerForHandle } = useMemo(() => {
    if (!listenerStatus) {
      return { sessionForHandle: null, workerForHandle: null };
    }
    for (const w of listenerStatus.workers ?? []) {
      const s = (w.sessions ?? []).find((x) => x.handle === handle);
      if (s) return { sessionForHandle: s, workerForHandle: w };
    }
    // Fallback: top-level sessions array (in_process mode).
    const s = (listenerStatus.sessions ?? []).find((x) => x.handle === handle);
    return { sessionForHandle: s ?? null, workerForHandle: null };
  }, [listenerStatus, handle]);

  const lastEvent = recent[0];
  const lastEventAgeS = lastEvent
    ? Math.max(0, (Date.now() - new Date(lastEvent.payload?.ts as string ?? Date.now()).getTime()) / 1000)
    : null;

  const liveNow =
    selectedRoom && !selectedRoom.ended_at && !roomEndedHeuristic(selectedRoom);
  // Trust the `is_live` cache only if the live-status probe checked
  // recently. Without this, a stuck listener (e.g. parked on
  // AgeRestrictedError sleep) leaves `is_live=true` from the last
  // successful probe forever, and the UI keeps claiming LIVE long
  // after the streamer went offline.
  const LIVE_CACHE_FRESH_MS = 3 * 60 * 1000;
  const isLiveCachedFresh =
    profile?.is_live === true &&
    !!profile.live_checked_at &&
    Date.now() - new Date(profile.live_checked_at).getTime() < LIVE_CACHE_FRESH_MS;
  const showLive = liveNow || isLiveCachedFresh;

  return (
    <section className="card">
      <div className="flex items-start gap-4">
        <SafeAvatar
          src={profile?.avatar_url}
          size={80}
          className="ring-2 ring-gray-100 dark:ring-gray-100/30 shrink-0"
          fallback={
            <span className="font-mono text-2xl text-gray-500">
              {(profile?.nickname?.[0] || handle[0] || '?').toUpperCase()}
            </span>
          }
        />

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-semibold text-gray-900 truncate">
              {profile?.nickname || handle}
            </h1>
            {profile?.verified && (
              <span title="Verified" className="text-primary-600 text-sm">
                ✓
              </span>
            )}
            <span className="font-mono text-xs text-gray-500">@{handle}</span>
            {showLive ? (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-white mr-1 animate-pulse" />
                LIVE
              </span>
            ) : (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono text-[10px] bg-gray-100 text-gray-600 dark:bg-gray-100/30">
                offline
              </span>
            )}
            <FreshnessBadge ageS={lastEventAgeS} />
            {/* Gifter Profile shortcut — opens the same per-user modal
                used for any gifter, pointed at this host. Surfaces
                cross-live gifter activity (if the host has also
                gifted on other monitored lives) + any badges /
                identity captured on prior gift events.  Suppressed
                in read-only (public) mode and when we don't have a
                resolved profile_user_id yet (modal needs an id to
                fetch). */}
            {!readOnly && onOpenHostProfile && profile?.profile_user_id && (
              <button
                type="button"
                onClick={onOpenHostProfile}
                className="ml-auto inline-flex items-center gap-1 px-2.5 py-1 rounded font-mono text-[10px] uppercase tracking-wider border border-gray-200 text-gray-700 hover:bg-primary-50 hover:border-primary-300 hover:text-primary-700 dark:border-gray-100/15 dark:hover:bg-primary-500/10 dark:hover:border-primary-400 dark:hover:text-primary-300 transition-colors"
                title={`Open ${profile.nickname || `@${handle}`}'s gifter profile`}
              >
                <User className="w-3 h-3" />
                Gifter Profile
              </button>
            )}
          </div>

          <div className="mt-2 flex items-center gap-x-5 gap-y-1 flex-wrap text-sm">
            <ProfileStat label="Followers" value={profile?.follower_count} />
            <ProfileStat label="Following" value={profile?.following_count} />
            {profile?.profile_user_id && (
              <span className="text-[10px] font-mono text-gray-500">
                user_id: {profile.profile_user_id}
              </span>
            )}
          </div>

          {/* 30-day activity summary chip — emitted by the
              TikTokLiveCalendar via `onSummary`. We render it here
              (instead of inside the calendar's header) so the
              profile carries the headline number and the heatmap
              stays a clean grid. */}
          {activitySummary && activitySummary.activeDays > 0 && (
            <div className="mt-1.5 text-[11px] font-mono text-gray-500 tabular-nums flex items-center gap-1 flex-wrap">
              <span className="uppercase tracking-wider text-[9px] text-gray-400">
                30d
              </span>
              <span>·</span>
              <span>
                {activitySummary.activeDays} day
                {activitySummary.activeDays === 1 ? '' : 's'} active
              </span>
              <span>·</span>
              <span>
                {activitySummary.totalBroadcasts} broadcast
                {activitySummary.totalBroadcasts === 1 ? '' : 's'}
              </span>
              {activitySummary.totalMinutes > 0 && (
                <>
                  <span>·</span>
                  <span>{formatActivityDuration(activitySummary.totalMinutes)}</span>
                </>
              )}
              {activitySummary.totalDiamonds > 0 && (
                <>
                  <span>·</span>
                  <span className="text-amber-700 dark:text-amber-300">
                    {formatActivityCount(activitySummary.totalDiamonds)} 💎
                  </span>
                </>
              )}
              {activitySummary.totalMatches > 0 && (
                <>
                  <span>·</span>
                  <span>
                    {activitySummary.totalMatches} match
                    {activitySummary.totalMatches === 1 ? '' : 'es'}
                  </span>
                </>
              )}
            </div>
          )}

          {profile?.bio && (
            <p className="mt-2 text-xs text-gray-600 dark:text-gray-400 whitespace-pre-line line-clamp-3">
              {profile.bio}
            </p>
          )}

          {showLive && selectedRoom?.room_id && (
            <div className="mt-2 text-[11px] font-mono text-gray-500">
              Room <span className="text-rose-600">{selectedRoom.room_id}</span>
              {selectedRoom.title && (
                <span className="ml-2 text-gray-700">· {selectedRoom.title}</span>
              )}
            </div>
          )}

          {/* Freshness pills: when each piece of cached data was last
              refreshed. Helps the admin tell at a glance whether the
              page reflects something current or stale. */}
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <FreshnessTimestampPill
              label="Profile"
              isoString={profile?.profile_refreshed_at ?? null}
              tooltip="Last full profile scrape (nickname, follower counts, bio…). Refreshed by the worker every ~hour."
            />
            <FreshnessTimestampPill
              label="Live check"
              isoString={profile?.live_checked_at ?? null}
              tooltip="Last is-live check. The worker's centralized scraper polls this every ~60s for offline handles."
            />
            {/* Worker liveness — the listener PROCESS heartbeat, not
                this handle. Stale ⇒ ingestion is paused for everyone.
                Hidden in read-only mode (public viewers shouldn't see
                operator-side ingestion health). */}
            {!readOnly && (
              <FreshnessAgePill
                label="Worker hb"
                ageS={workerForHandle?.heartbeat_age_s ?? null}
                tooltip={
                  workerForHandle
                    ? `Worker ${workerForHandle.worker_key} (pid ${workerForHandle.pid}) — heartbeat to DB. Stale (>30s) means the listener process is hung or stopped; no events for any handle until it recovers.`
                    : 'No worker is currently assigned to this handle. Subscription is over capacity or unclaimed — only the live-status scraper covers it (no events ingested).'
                }
                neverLabel={workerForHandle ? 'never' : 'unassigned'}
                greenUntil={30}
                amberUntil={120}
              />
            )}
            {/* Per-session last-event ingestion. Comes from the worker's
                own counter, so it survives a page refresh (unlike the
                WS-derived FreshnessBadge above which only sees events
                arrived since this tab opened). Hidden in read-only
                mode for the same reason as the worker heartbeat pill. */}
            {!readOnly && (
              <FreshnessAgePill
                label="Last event"
                ageS={sessionForHandle?.last_event_age_s ?? null}
                tooltip={
                  sessionForHandle
                    ? `Most recent event ingested for @${handle} (state: ${sessionForHandle.state}, ${sessionForHandle.events_total.toLocaleString()} total in this session). 'never' usually means the creator hasn't been live since the worker started.`
                    : 'No active listener session for this handle yet — over capacity or just added. Once a worker claims it, this pill will populate.'
                }
                greenUntil={60}
                amberUntil={600}
              />
            )}
          </div>


          {/* Probe-debug trigger + modal — admin-only. Reads worker_log,
              which is operator-side state, so hidden in public mode. */}
          {!readOnly && (
            <>
              <button
                type="button"
                onClick={() => setDebugOpen(true)}
                className={
                  'mt-2 inline-flex items-center gap-1.5 text-[11px] font-mono ' +
                  (profile?.profile_error
                    ? 'text-amber-700 hover:text-amber-900 dark:text-amber-300 dark:hover:text-amber-100'
                    : 'text-gray-500 hover:text-gray-800')
                }
                title="Open probe-debug modal: latest error + recent probe history from worker_log"
              >
                <Bug className="w-3.5 h-3.5" />
                <span className="underline decoration-dotted">
                  {profile?.profile_error
                    ? `profile probe: ${profile.profile_error.split('\n')[0]}`
                    : 'probe history'}
                </span>
              </button>
              <ProbeDebugModal
                isOpen={debugOpen}
                onClose={() => setDebugOpen(false)}
                handle={handle}
                error={profile?.profile_error ?? null}
                profileRefreshedAt={profile?.profile_refreshed_at ?? null}
              />
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function ProfileStat({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="font-mono tabular-nums text-gray-900 font-medium">
        {value != null ? compactCount(value) : '—'}
      </span>
      <span className="text-[10px] uppercase tracking-wider text-gray-500">{label}</span>
    </span>
  );
}

function FreshnessBadge({ ageS }: { ageS: number | null }) {
  // Color: green <30s, amber <120s, gray older / missing.
  if (ageS == null) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] bg-gray-100 text-gray-500 dark:bg-gray-100/30"
        title="No events received yet on this page session"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
        no events yet
      </span>
    );
  }
  let tone: string;
  if (ageS < 30) tone = 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300';
  else if (ageS < 120) tone = 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300';
  else tone = 'bg-gray-100 text-gray-600 dark:bg-gray-100/30';
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] ${tone}`}
      title="How long ago the last event arrived for this handle"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60" />
      last event {formatAgo(ageS)}
    </span>
  );
}

function formatAgo(seconds: number): string {
  const s = Math.floor(seconds);
  if (s < 1) return 'now';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function FreshnessTimestampPill({
  label,
  isoString,
  tooltip,
}: {
  label: string;
  isoString: string | null;
  tooltip?: string;
}) {
  const { tz } = useTikTokTimezone();
  if (!isoString) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] bg-gray-100 text-gray-500 dark:bg-gray-100/30"
        title={tooltip}
      >
        {label}: never
      </span>
    );
  }
  const ageS = Math.max(0, (Date.now() - new Date(isoString).getTime()) / 1000);
  let tone: string;
  if (ageS < 120) tone = 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300';
  else if (ageS < 1800) tone = 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300';
  else tone = 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300';
  const fullTimestamp = fmtFull(isoString, tz);
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] ${tone}`}
      title={`${tooltip ?? ''}\n${fullTimestamp}`}
    >
      {label}: {formatAgo(ageS)}
    </span>
  );
}

/** Pill that takes a numeric age (seconds) directly — used for values
 *  that come from the listener-status snapshot already aged by the
 *  backend (no original ISO timestamp on hand). Same colour ramp as
 *  `FreshnessTimestampPill` for visual consistency. */
function FreshnessAgePill({
  label,
  ageS,
  tooltip,
  neverLabel = 'never',
  greenUntil = 30,
  amberUntil = 300,
}: {
  label: string;
  ageS: number | null | undefined;
  tooltip?: string;
  neverLabel?: string;
  /** Age (s) below which the pill is green. Defaults tuned for live
   *  signals: heartbeat=30s, last-event=30s. Override per use. */
  greenUntil?: number;
  amberUntil?: number;
}) {
  if (ageS == null) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] bg-gray-100 text-gray-500 dark:bg-gray-100/30"
        title={tooltip}
      >
        {label}: {neverLabel}
      </span>
    );
  }
  let tone: string;
  if (ageS < greenUntil) tone = 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300';
  else if (ageS < amberUntil) tone = 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300';
  else tone = 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300';
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] ${tone}`}
      title={tooltip}
    >
      {label}: {formatAgo(ageS)}
    </span>
  );
}

interface ProbeRecord {
  url: string;
  status: string;
  reason: string;
  bodyLen: string;
  snippet: string;
}

function parseProbeDebug(error: string): { headline: string; probes: ProbeRecord[] } {
  // The scraper formats `profile_error` as:
  //   "<headline> [last_reason; http=X; len=N]"
  //   "  <url> → reason=<R> http=<S> len=<N> | snippet=<...>"
  //   "  <url> → reason=<R> http=<S> len=<N> | snippet=<...>"
  const lines = (error || '').split('\n');
  const headline = lines[0]?.trim() ?? '';
  const probes: ProbeRecord[] = [];
  for (const raw of lines.slice(1)) {
    const m = /^\s*(\S+)\s*→\s*reason=(.+?)\s+http=(\S+)\s+len=(\S+?)(?:\s*\|\s*snippet=(.+))?$/.exec(raw);
    if (!m) continue;
    probes.push({
      url: m[1],
      reason: m[2].trim(),
      status: m[3],
      bodyLen: m[4],
      snippet: (m[5] ?? '').trim(),
    });
  }
  return { headline, probes };
}

function ProbeDebugModal({
  isOpen,
  onClose,
  handle,
  error,
  profileRefreshedAt,
}: {
  isOpen: boolean;
  onClose: () => void;
  handle: string;
  error: string | null;
  profileRefreshedAt: string | null;
}) {
  const tiktokApi = useTikTokApi();
  const { tz } = useTikTokTimezone();
  // Pull recent profile_probe_* rows from the worker_log so the modal
  // also surfaces partial-success and historical WAF detections, not
  // just the most-recent-failure stored in `profile_error`.
  const [history, setHistory] = useState<
    Array<{ ts: string | null; event: string; level: string; probes: ProbeRecord[] }>
  >([]);
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    tiktokApi
      .listenerLog({ handle, event_prefix: 'profile_probe', limit: 20 })
      .then((rows) => {
        if (cancelled) return;
        const flat: Array<{ ts: string | null; event: string; level: string; probes: ProbeRecord[] }> = [];
        for (const r of rows) {
          const probes = ((r.detail?.probes as unknown[]) ?? []) as Array<{
            url?: string; status?: number | string; reason?: string;
            body_len?: number; snippet?: string;
          }>;
          flat.push({
            ts: r.ts,
            event: r.event,
            level: r.level,
            probes: probes.map((p) => ({
              url: String(p.url ?? ''),
              status: String(p.status ?? '?'),
              reason: String(p.reason ?? '?'),
              bodyLen: String(p.body_len ?? 0),
              snippet: String(p.snippet ?? ''),
            })),
          });
        }
        setHistory(flat);
      })
      .catch(() => setHistory([]));
    return () => { cancelled = true; };
  }, [isOpen, handle]);

  // Parse the inline summary from the latest profile_error string.
  const { headline, probes } = error
    ? parseProbeDebug(error)
    : { headline: '', probes: [] };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Profile probe trace · @${handle}`}>
      <div className="space-y-4">
        {error ? (
          <div>
            <div className="auth-mono-label mb-1">Latest error</div>
            <p className="text-sm text-gray-800">{headline}</p>
            {profileRefreshedAt && (
              <p className="text-[11px] font-mono text-gray-500 mt-1">
                Last attempt: {fmtFull(profileRefreshedAt, tz)}
              </p>
            )}
          </div>
        ) : (
          <div>
            <div className="auth-mono-label mb-1">Latest error</div>
            <p className="text-sm text-emerald-700 dark:text-emerald-300">
              No error on the most recent refresh
              {profileRefreshedAt
                ? ` (${fmtFull(profileRefreshedAt, tz)})`
                : ''}
              . History below shows past WAF / partial-failure events.
            </p>
          </div>
        )}

        <div>
          <div className="auth-mono-label mb-1">What it means</div>
          <ul className="text-xs text-gray-700 list-disc pl-5 space-y-1">
            <li>
              <code className="font-mono">waf</code> = TikTok's SlardarWAF served a
              ~1.5 KB challenge page instead of the real profile HTML. Usually
              triggered by request rate from one IP. Wait, retry from a
              different network, or use the Electron sign broker (real-browser
              cookies).
            </li>
            <li>
              <code className="font-mono">no SIGI_STATE / __UNIVERSAL_DATA_FOR_REHYDRATION__</code>{' '}
              = the response was an HTML page but lacked TikTok's embedded
              JSON tag. Could be a redirect, a regional block, or TikTok
              changed their template.
            </li>
            <li>
              <code className="font-mono">exception: …</code> = network /
              connection / timeout failure before any HTTP response.
            </li>
            <li>
              <code className="font-mono">http</code> 200 with a tiny body
              length is almost always WAF. 403 / 404 / 5xx are TikTok-side
              rejections.
            </li>
          </ul>
        </div>

        {error && probes.length > 0 && (
          <div>
            <div className="auth-mono-label mb-1">Latest probe attempts</div>
            <div className="space-y-2">
              {probes.map((p, i) => (
                <ProbeRecordCard key={`latest-${i}`} index={i + 1} probe={p} />
              ))}
            </div>
          </div>
        )}

        {history.length > 0 && (
          <div>
            <div className="auth-mono-label mb-1">
              Recent probe events from worker_log ({history.length})
            </div>
            <div className="space-y-3">
              {history.map((h, idx) => (
                <div
                  key={idx}
                  className="rounded border border-gray-200 overflow-hidden"
                >
                  <div className="bg-gray-50 px-3 py-1.5 flex items-center gap-2 text-xs">
                    <span
                      className={
                        'font-mono px-1.5 py-0.5 rounded text-[10px] ' +
                        (h.event.endsWith('_failed')
                          ? 'bg-rose-100 text-rose-700'
                          : 'bg-amber-100 text-amber-800')
                      }
                    >
                      {h.event}
                    </span>
                    <span className="font-mono text-gray-500">
                      {h.ts ? fmtFull(h.ts, tz) : '—'}
                    </span>
                    <span className="ml-auto font-mono text-[10px] text-gray-500">
                      {h.probes.length} probe{h.probes.length === 1 ? '' : 's'}
                    </span>
                  </div>
                  <div className="p-2 space-y-1">
                    {h.probes.map((p, i) => (
                      <ProbeRecordCard
                        key={`${idx}-${i}`}
                        index={i + 1}
                        probe={p}
                        compact
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {error && (
          <div className="text-[10px] font-mono text-gray-500">
            Raw error (verbatim from <code>tiktok_subscriptions.profile_error</code>):
            <pre className="mt-1 px-2 py-1 bg-gray-100 dark:bg-gray-100/20 rounded whitespace-pre-wrap break-all">
              {error}
            </pre>
          </div>
        )}
      </div>
    </Modal>
  );
}

function ProbeRecordCard({
  index,
  probe,
  compact = false,
}: {
  index: number;
  probe: ProbeRecord;
  compact?: boolean;
}) {
  return (
    <div className="rounded border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 px-3 py-1.5 flex items-center gap-2 flex-wrap text-xs">
        <span className="font-mono text-gray-500">#{index}</span>
        <span className="font-mono text-gray-900 truncate" title={probe.url}>
          {probe.url}
        </span>
        <span className="ml-auto inline-flex items-center gap-2">
          <ProbePill label="reason" value={probe.reason} tone="rose" />
          <ProbePill label="http" value={probe.status} tone="sky" />
          <ProbePill label="len" value={probe.bodyLen} tone="gray" />
        </span>
      </div>
      {probe.snippet && (
        <pre
          className={
            'px-3 py-2 text-[10px] leading-tight font-mono whitespace-pre-wrap break-all bg-gray-900/95 text-gray-100 overflow-auto ' +
            (compact ? 'max-h-24' : 'max-h-48')
          }
        >
          {probe.snippet}
        </pre>
      )}
    </div>
  );
}

function ProbePill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'rose' | 'sky' | 'gray';
}) {
  const cls = (() => {
    switch (tone) {
      case 'rose': return 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300';
      case 'sky':  return 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300';
      default:     return 'bg-gray-100 text-gray-700 dark:bg-gray-100/30';
    }
  })();
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] ${cls}`}>
      <span className="opacity-70">{label}=</span>
      <span className="font-medium">{value}</span>
    </span>
  );
}

function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(0)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

/** Same shape as `compactCount` but lives next to its sibling
 *  duration formatter so the activity-summary chip in ProfileHeaderCard
 *  reads them both from one place. */
function formatActivityCount(n: number): string {
  return compactCount(n);
}

/** Minutes → human-readable "1d 5h 12m" form. Distinct from the
 *  start/end-ISO `formatDuration` already used by the chart row. */
function formatActivityDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h < 24) return m === 0 ? `${h}h` : `${h}h ${m}m`;
  const d = Math.floor(h / 24);
  const hh = h % 24;
  return hh === 0 ? `${d}d` : `${d}d ${hh}h`;
}

function CardTabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'flex items-center gap-1 px-2.5 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ' +
        (active
          ? 'border-primary-500 text-primary-700 dark:text-primary-300'
          : 'border-transparent text-gray-600 hover:text-gray-900')
      }
    >
      {children}
    </button>
  );
}

function summarizeEvent(e: TikTokWsEvent): string {
  const p = e.payload || {};
  const u = (p.user as { nickname?: string } | undefined)?.nickname || 'someone';
  if (e.type === 'comment') return `${u}: ${String(p.text ?? '').slice(0, 80)}`;
  if (e.type === 'gift') {
    const base = `${u} sent ${p.gift_name ?? 'gift'} ×${p.repeat_count ?? 1} (${p.diamond_count ?? 0}💎)`;
    const to = p.to_user as { unique_id?: string; nickname?: string } | undefined;
    const dest = to && (to.nickname || to.unique_id);
    return dest ? `${base} → ${to.nickname || `@${to.unique_id}`}` : base;
  }
  if (e.type === 'like') return `${u} liked (${p.count ?? 1})`;
  if (e.type === 'join') return `${u} joined`;
  if (e.type === 'match_start') return 'PK battle started';
  if (e.type === 'match_update') return 'battle scores updated';
  if (e.type === 'match_end') return 'battle ended';
  return JSON.stringify(p).slice(0, 120);
}

// ─── match helpers ─────────────────────────────────────────────────

/** Use TikTok's battle clock (settings.duration_seconds) when available —
 *  it's the canonical 5:00 / 5:01 / 6:00 (extended) battle length.
 *  Falls back to wall-clock between match_start and match_end events,
 *  but those happen AFTER the punish/victory-lap phase and are therefore
 *  longer than the battle itself by ~25-35 seconds. */
function formatBattleDuration(m: TikTokMatch): string {
  const d = m.settings?.duration_seconds;
  if (d && d > 0) {
    const mins = Math.floor(d / 60);
    const secs = d % 60;
    return `${mins}:${pad(secs)}`;
  }
  return formatDuration(m.started_at, m.ended_at ?? m.last_seen_at);
}

function formatStarted(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return '—';
  const a = new Date(start).getTime();
  const b = end ? new Date(end).getTime() : Date.now();
  const sec = Math.max(0, Math.floor((b - a) / 1000));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${pad(s)}`;
}

// ─── MatchesPanel ──────────────────────────────────────────────────
// Tabbed: "In progress" (live battle, if any) + "Past battles" (history).
// Always rendered with the rose accent so the section stays visually
// recognizable across both tabs.

const RESULT_TONE: Record<string, string> = {
  won: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  lost: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
  draw: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  ended: 'bg-gray-100 text-gray-700',
  ongoing: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300',
};

interface MatchesPanelProps {
  activeMatch: TikTokMatch | null;
  pastMatches: TikTokMatch[];
  hostHandle: string;
  hostProfile: HostProfile | null;
  onSelectMatch?: (m: TikTokMatch) => void;
  /** Optional human-readable scope hint ("Live broadcast · …",
   *  "Day view · Thu, May 7", etc.) — shown in the empty state so
   *  the user understands "no battles" applies to the current view,
   *  not the whole creator. */
  scopeLabel?: string;
  /** When true, suppress the rival monitor pills inside `LiveMatchView`. */
  readOnly?: boolean;
  /** Threaded down to the in-progress match view so each BattlerCard
   *  can open the canonical gifter modal for that anchor. Lives in the
   *  parent page (where the modal mounts), so we forward the setter. */
  onSelectGifter?: (sel: {
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
  }) => void;
}

// HostProfile is the full subscription record now — `MatchupCell`
// only reads user_id / nickname / avatar_url which exist on the
// subscription as `profile_user_id` / `nickname` / `avatar_url`.
type HostProfile = TikTokSubscription;

function MatchesPanel({
  activeMatch,
  pastMatches,
  hostHandle,
  hostProfile,
  onSelectMatch,
  scopeLabel,
  readOnly = false,
  onSelectGifter,
}: MatchesPanelProps) {
  // Default tab: live if there's an active match, otherwise past.
  const [tab, setTab] = useState<'live' | 'past'>(
    activeMatch ? 'live' : 'past'
  );
  // Auto-switch to live tab if a match starts while user is on "past".
  useEffect(() => {
    if (activeMatch && tab === 'past' && pastMatches.length === 0) {
      setTab('live');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMatch?.id]);

  const ended = pastMatches.filter((m) => m.ended_at);

  // No active battle → drop the tab bar entirely and just render the
  // past-battles list. The "No active battle" tab was just visual
  // noise on closed broadcasts / day-aggregate views, where there's
  // never a live PK to show.
  if (!activeMatch) {
    return (
      <section className="rounded-lg border border-rose-200 dark:border-rose-500/30 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2 bg-rose-50 dark:bg-rose-500/10 text-rose-800 dark:text-rose-200">
          <History className="w-4 h-4" />
          <span className="auth-mono-label">Past battles</span>
          <span className="text-gray-500 font-mono text-[11px]">
            ({ended.length})
          </span>
        </div>
        <div className="bg-white dark:bg-gray-100/5 p-4">
          <PastMatchesTable
            matches={ended}
            hostHandle={hostHandle}
            hostProfile={hostProfile}
            onSelect={onSelectMatch}
            scopeLabel={scopeLabel}
          />
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-rose-200 dark:border-rose-500/30 overflow-hidden">
      <div className="flex items-center gap-1 px-1 pt-1 bg-rose-50 dark:bg-rose-500/10">
        <TabButton active={tab === 'live'} onClick={() => setTab('live')}>
          <Swords className="w-4 h-4" />
          In progress
          <span className="ml-1.5 inline-flex items-center px-1.5 rounded-full bg-rose-500 text-white text-[10px] font-mono leading-4">
            live
          </span>
        </TabButton>
        <TabButton active={tab === 'past'} onClick={() => setTab('past')}>
          <History className="w-4 h-4" />
          Past battles
          <span className="ml-1.5 text-gray-500 font-mono text-[11px]">
            ({ended.length})
          </span>
        </TabButton>
      </div>
      <div className="bg-white dark:bg-gray-100/5 p-4">
        {tab === 'live' ? (
          <LiveMatchView
            match={activeMatch}
            hostHandle={hostHandle}
            readOnly={readOnly}
            onSelectGifter={onSelectGifter}
          />
        ) : (
          <PastMatchesTable
            matches={ended}
            hostHandle={hostHandle}
            hostProfile={hostProfile}
            onSelect={onSelectMatch}
            scopeLabel={scopeLabel}
          />
        )}
      </div>
    </section>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        'flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors ' +
        (active
          ? 'border-rose-500 text-rose-700 dark:text-rose-300'
          : 'border-transparent text-gray-600 hover:text-gray-900')
      }
    >
      {children}
    </button>
  );
}

interface LiveMatchViewProps {
  match: TikTokMatch;
  hostHandle: string;
  /** When true, hide the rival monitor pills + their confirmation
   *  modal. The pills call `createLive`, which is an admin-write
   *  endpoint not exposed to public viewers. */
  readOnly?: boolean;
  /** Threaded from MatchesPanel → parent page so each BattlerCard's
   *  Profile button can open the page-level gifter modal. */
  onSelectGifter?: (sel: {
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
  }) => void;
}

function LiveMatchView({
  match,
  hostHandle,
  readOnly = false,
  onSelectGifter,
}: LiveMatchViewProps) {
  const tiktokApi = useTikTokApi();
  // Re-render every second so the duration / countdown updates.
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const opponents = match.opponents || [];
  const host =
    opponents.find((o) => normalizeHandle(o) === hostHandle) || null;
  // Multi-team battles ship team_id on each anchor. When the host has
  // a team_id, "rivals" means anchors on a DIFFERENT team — not just
  // "everyone except the host". A 3v1 PK has 2 teammates on the host's
  // side; without this filter we'd render those teammates as rival
  // cards showing the *opposing* team's score (via `rivalScoreOf`'s
  // team_id → scoresByTeam fallback) — total nonsense. When no
  // team_ids are present (TikTok sometimes ships an empty mapping),
  // fall back to the legacy "anyone non-host is a rival" rule.
  const hostTeamId = host?.team_id != null ? String(host.team_id) : null;
  const rivals = hostTeamId
    ? opponents.filter((o) =>
        o.team_id != null && String(o.team_id) !== hostTeamId
      )
    : opponents.filter((o) => normalizeHandle(o) !== hostHandle);
  // Teammates: anchors on the SAME team as the host (excluding the
  // host themselves). Surfaced as a small chip row below the host
  // card so the operator can see who's fighting on the host's side.
  const teammates = hostTeamId
    ? opponents.filter((o) =>
        normalizeHandle(o) !== hostHandle
        && o.team_id != null
        && String(o.team_id) === hostTeamId
      )
    : [];

  // Rival-host monitoring affordance. Drives a bottom-of-card pill
  // that lets the operator jump straight from a PK battle into
  // monitoring the opponent — they're already showing intent (they
  // accepted the PK), so this is the right moment to track them.
  // We resolve the handle, check whether it's already in
  // `tiktok_subscriptions`, and render either a "✓ Monitoring" link
  // or a "+ Add to monitor" button (same UX as the match modal's
  // opponent cells + the gifter modal footer).
  const [subscribedSet, setSubscribedSet] = useState<Set<string>>(() => new Set());
  const [addRivalOpen, setAddRivalOpen] = useState<TikTokMatchOpponent | null>(null);
  useEffect(() => {
    // Skip in read-only mode: the public namespace doesn't expose
    // listLives, and the rival pills are hidden so we never need to
    // know the subscription set anyway.
    if (readOnly) {
      setSubscribedSet(new Set());
      return;
    }
    let cancelled = false;
    tiktokApi
      .listLives()
      .then((rows) => {
        if (cancelled) return;
        const set = new Set<string>();
        for (const r of rows) if (r.unique_id) set.add(r.unique_id.toLowerCase());
        setSubscribedSet(set);
      })
      .catch(() => { /* silent — backend's createLive guards against dupes anyway */ });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match.id, readOnly]);
  const confirmAddRival = async () => {
    const handle = addRivalOpen?.unique_id;
    if (!handle) return;
    try {
      await tiktokApi.createLive(handle, true);
      setSubscribedSet((prev) => {
        const next = new Set(prev);
        next.add(handle.toLowerCase());
        return next;
      });
      toast.success(`Now monitoring @${handle}`);
      setAddRivalOpen(null);
    } catch (e) {
      toast.error(
        (e as Error).message || `Failed to add @${handle} to monitor`,
      );
      throw e;
    }
  };

  // Per-anchor score takes precedence (set from `armies.host_score`); fall
  // back to team aggregate only when per-anchor isn't available.
  const scoresByTeam = match.scores || {};

  const hostScore = (() => {
    if (host?.score != null && Number(host.score) > 0) return Number(host.score);
    if (hostTeamId) return Number(scoresByTeam[hostTeamId] ?? 0);
    return 0;
  })();

  const rivalScore = (() => {
    const perAnchor = rivals.reduce(
      (sum, r) => sum + Number(r.score ?? 0),
      0
    );
    if (perAnchor > 0) return perAnchor;
    return Object.entries(scoresByTeam)
      .filter(([t]) => t !== hostTeamId)
      .reduce((acc, [, v]) => acc + Number(v ?? 0), 0);
  })();

  const total = hostScore + rivalScore;
  const hostPct = total > 0 ? (hostScore / total) * 100 : 50;
  // Per-rival score resolver — same logic as `rivalScore` but for
  // an individual anchor instead of the aggregate. Used to render
  // each rival's own BattlerCard in 3-way / 4-way battles where
  // the total rival pool is more than one creator.
  const rivalScoreOf = (r: TikTokMatchOpponent): number => {
    if (r.score != null) return Number(r.score);
    if (r.team_id != null) return Number(scoresByTeam[String(r.team_id)] ?? 0);
    return 0;
  };
  // Highlight whichever participant has the current best score —
  // host or the top-scoring rival. In 1v1 this reduces to the
  // previous "host vs rival" comparison; in multi-rival battles it
  // surfaces the actual leader rather than the first listed rival.
  const topRivalScore = rivals.reduce(
    (mx, r) => Math.max(mx, rivalScoreOf(r)),
    0,
  );
  const leaderSide: 'host' | 'rival' | 'tie' =
    total === 0
      ? 'tie'
      : hostScore > topRivalScore
        ? 'host'
        : hostScore < topRivalScore
          ? 'rival'
          : 'tie';

  // Countdown: TikTok PK battles count DOWN. Use BattleSetting.end_time_ms
  // when available (most accurate); fall back to start + duration_seconds.
  const countdown = computeCountdown(match);
  const phaseInfo = deriveMatchPhase(match, countdown);

  return (
    <div>
      {/* Header bar */}
      <div className="flex items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono uppercase tracking-wider ${phaseInfo.tone}`}
            title={`Phase: ${phaseInfo.phase}`}
          >
            {phaseInfo.animated && (
              <span className="w-1.5 h-1.5 rounded-full bg-current mr-1 animate-pulse opacity-90" />
            )}
            {phaseInfo.label}
          </span>
          <span className="auth-mono-label text-rose-700 dark:text-rose-300">
            PK battle
          </span>
        </div>
        <div className="flex items-baseline gap-5">
          <Stat
            label="Diamonds"
            value={`${(match.diamonds_total ?? 0).toLocaleString()} 💎`}
            tone="amber"
          />
          <Stat
            label={countdown != null ? 'Time left' : 'Duration'}
            value={
              countdown != null
                ? formatCountdown(countdown)
                : formatDuration(match.started_at, null)
            }
            tone="rose"
            big
          />
        </div>
      </div>

      {/* Versus card. Both teams render as horizontal flex rows of
          BattlerCards so multi-anchor battles (3v1, 2v2, 4-way) show
          everyone on equal footing. Teammates sit beside the host in
          the "our team" column; rivals stack horizontally in the
          "rival team" column. A vertical divider with the VS letters
          separates the two sides. The grid collapses to a single
          column on mobile — the divider becomes a horizontal rule
          implicit in the row gap. Each card carries its own Profile
          and Monitor affordances; we no longer render a separate
          monitor-pill row below the versus card. */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-4 items-stretch">
        {/* Host (our team) column — host first, then teammates. flex-wrap
            so cards reflow under the host on narrow desktops rather than
            forcing horizontal scroll. */}
        <div className="flex flex-wrap gap-2 items-stretch">
          <div className="flex-1 min-w-[160px] sm:min-w-[200px]">
            <BattlerCard
              person={host}
              score={hostScore}
              color="#10b981" /* emerald = home/host */
              fallbackHandle={hostHandle}
              align="left"
              winning={leaderSide === 'host'}
              // Host's profile button — surfaces the page-host's
              // gifter modal. We only wire it when we actually have a
              // user_id (some matches arrive without one); otherwise
              // hide the bottom row entirely.
              onProfileClick={
                onSelectGifter && host?.user_id
                  ? () =>
                      onSelectGifter({
                        userId: String(host.user_id),
                        uniqueId: host.unique_id ?? hostHandle,
                        nickname: host.nickname ?? null,
                      })
                  : undefined
              }
              // The page IS the host's monitored live — no monitor CTA.
              monitorState={null}
            />
          </div>
          {teammates.map((t, i) => {
            const tHandle = t.unique_id || null;
            const tHandleLc = tHandle?.toLowerCase() ?? null;
            const monitored = tHandleLc
              ? subscribedSet.has(tHandleLc)
              : false;
            // Per-teammate score uses the same per-anchor → team-id
            // fallback chain as rivalScoreOf. Most events ship
            // armies.host_score per anchor; the team_id fallback
            // splits the team total evenly, which is a defensible
            // best-effort when only the team total is known.
            const tScore = (() => {
              if (t.score != null) return Number(t.score);
              if (hostTeamId) {
                const teamTotal = Number(scoresByTeam[hostTeamId] ?? 0);
                // Even split across teammates+host; conservative since
                // we don't know the real per-anchor allocation.
                return Math.round(teamTotal / Math.max(1, teammates.length + 1));
              }
              return 0;
            })();
            return (
              <div
                key={t.user_id || tHandle || i}
                className="flex-1 min-w-[160px] sm:min-w-[200px]"
              >
                <BattlerCard
                  person={t}
                  score={tScore}
                  color="#10b981"
                  fallbackHandle={null}
                  align="left"
                  winning={false}
                  onProfileClick={
                    onSelectGifter && t.user_id
                      ? () =>
                          onSelectGifter({
                            userId: String(t.user_id),
                            uniqueId: tHandle,
                            nickname: t.nickname ?? null,
                          })
                      : undefined
                  }
                  // Hide the monitor row in read-only mode (the
                  // confirmation modal calls an admin-write endpoint
                  // not exposed publicly).
                  monitorState={
                    readOnly || !tHandle
                      ? null
                      : monitored
                        ? 'monitored'
                        : 'add'
                  }
                  monitorHandle={tHandle}
                  onMonitorClick={
                    tHandle ? () => setAddRivalOpen(t) : undefined
                  }
                />
              </div>
            );
          })}
        </div>
        <div className="flex items-center justify-center">
          {/* Vertical divider on md+; the "VS" sits at the midpoint of
              the divider so both team columns visually break against
              it. Collapses to a thin horizontal line on mobile. */}
          <div className="hidden md:block w-px self-stretch bg-gray-200 dark:bg-white/10 relative">
            <div
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-white dark:bg-gray-100/10 px-2 text-2xl font-extrabold text-rose-500 select-none"
              style={{ fontFamily: 'var(--font-mono-display)' }}
              aria-hidden
            >
              VS
            </div>
          </div>
          <div
            className="md:hidden text-3xl font-extrabold text-rose-500 select-none"
            style={{ fontFamily: 'var(--font-mono-display)' }}
            aria-hidden
          >
            VS
          </div>
        </div>
        {/* Rival column — same flex-wrap shape so 3-way / 4-way battles
            render multiple rivals side-by-side. */}
        {rivals.length === 0 ? (
          <div className="flex flex-wrap gap-2 items-stretch">
            <div className="flex-1 min-w-[160px] sm:min-w-[200px]">
              <BattlerCard
                person={null}
                score={rivalScore}
                color="#ef4444"
                fallbackHandle={null}
                align="right"
                winning={false}
              />
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2 items-stretch">
            {rivals.map((r, i) => {
              const sc = rivalScoreOf(r);
              const rHandle = r.unique_id || null;
              const rHandleLc = rHandle?.toLowerCase() ?? null;
              const monitored = rHandleLc
                ? subscribedSet.has(rHandleLc)
                : false;
              // Only the rival(s) tied for the top score get the
              // "winning" glow — and only when they're actually
              // beating the host. Otherwise nobody on the rival side
              // is highlighted (mirrors the host glow rule).
              const isLeader =
                leaderSide === 'rival' && sc === topRivalScore && sc > 0;
              return (
                <div
                  key={r.user_id || rHandle || i}
                  className="flex-1 min-w-[160px] sm:min-w-[200px]"
                >
                  <BattlerCard
                    person={r}
                    score={sc}
                    color="#ef4444" /* red = rival */
                    fallbackHandle={null}
                    align="right"
                    winning={isLeader}
                    onProfileClick={
                      onSelectGifter && r.user_id
                        ? () =>
                            onSelectGifter({
                              userId: String(r.user_id),
                              uniqueId: rHandle,
                              nickname: r.nickname ?? null,
                            })
                        : undefined
                    }
                    monitorState={
                      readOnly || !rHandle
                        ? null
                        : monitored
                          ? 'monitored'
                          : 'add'
                    }
                    monitorHandle={rHandle}
                    onMonitorClick={
                      rHandle ? () => setAddRivalOpen(r) : undefined
                    }
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Score progress bar */}
      {total > 0 ? (
        <div className="mt-4">
          <div className="relative h-3 rounded-full bg-gray-100 dark:bg-gray-100/30 overflow-hidden flex">
            <div
              className="bg-emerald-500 transition-[flex-basis] duration-500"
              style={{ flexBasis: `${hostPct}%` }}
            />
            <div
              className="bg-red-500 transition-[flex-basis] duration-500"
              style={{ flexBasis: `${100 - hostPct}%` }}
            />
          </div>
          <div className="flex items-center justify-between mt-1 text-xs font-mono text-gray-500">
            <span className="text-emerald-700 dark:text-emerald-300">
              {hostPct.toFixed(0)}%
            </span>
            <span>
              {hostScore.toLocaleString()} – {rivalScore.toLocaleString()}
            </span>
            <span className="text-red-700 dark:text-red-300">
              {(100 - hostPct).toFixed(0)}%
            </span>
          </div>
        </div>
      ) : (
        <div className="mt-4 text-center text-xs font-mono text-gray-500 italic">
          {phaseInfo.phase === 'pending' || phaseInfo.phase === 'live'
            ? 'Awaiting first gift…'
            : '0 – 0'}
        </div>
      )}

      {/* Top donors — unified ranked list of who paid into THIS
          battle. Combines both sides + unknown-recipient gifts and
          sorts by diamonds desc. Polls the gifters-by-side endpoint
          every 3s while the battle is live so leaderboard climbs
          are visible without a manual refresh. */}
      <LiveMatchTopDonors match={match} hostHandle={hostHandle} />

      {/* Note: the standalone "Rivals: + Add / ✓ Monitoring" pill row
          previously rendered here has been folded into each BattlerCard
          as a per-card footer affordance, so the entire match section
          carries only one source of truth for the monitor state. */}

      {/* Confirm modal — reuses the canonical Add Live preview so
          the operator sees the same avatar/followers/bio they'd see
          on /admin/tiktok's Add Live flow. Suppressed in read-only
          mode so it never mounts in public contexts (its onConfirm
          calls createLive, an admin-write endpoint). */}
      {!readOnly && (
        <TikTokAddLiveModal
          isOpen={addRivalOpen !== null}
          handle={addRivalOpen?.unique_id ?? ''}
          onCancel={() => setAddRivalOpen(null)}
          onConfirm={confirmAddRival}
        />
      )}
    </div>
  );
}

function LiveMatchTopDonors({
  match,
  hostHandle,
}: {
  match: TikTokMatch;
  hostHandle: string;
}) {
  const tiktokApi = useTikTokApi();
  const [sides, setSides] = useState<TikTokMatchGiftersBySide | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = () => {
      tiktokApi
        .getMatchGiftersBySide(match.id)
        .then((s) => { if (!cancelled) setSides(s); })
        .catch(() => { /* keep last good result */ })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    setLoading(true);
    fetchOnce();
    // Refresh while the match is live so the leaderboard catches up
    // with each gift. Stops polling once the match has an ended_at.
    if (!match.ended_at) {
      const t = setInterval(fetchOnce, 3000);
      return () => { cancelled = true; clearInterval(t); };
    }
    return () => { cancelled = true; };
  }, [match.id, match.ended_at]);

  if (!sides) {
    return (
      <div className="mt-4 text-xs font-mono text-gray-500 text-center py-3">
        {loading ? 'Loading top donors…' : 'No donor data yet.'}
      </div>
    );
  }
  type Row = TikTokMatchSideGifter & { side: 'host' | 'opponent' | 'unknown' };
  const rows: Row[] = [
    ...sides.host.map((g) => ({ ...g, side: 'host' as const })),
    ...sides.opponent.map((g) => ({ ...g, side: 'opponent' as const })),
    ...sides.unknown.map((g) => ({ ...g, side: 'unknown' as const })),
  ].sort((a, b) => b.diamonds - a.diamonds);
  if (rows.length === 0) return null;
  const total = rows.reduce((acc, r) => acc + r.diamonds, 0) || 1;
  const sideTone = (s: Row['side']) => {
    if (s === 'host')     return { dot: 'bg-emerald-500', label: `@${hostHandle}` };
    if (s === 'opponent') return { dot: 'bg-rose-500',    label: 'opponent' };
    return { dot: 'bg-gray-400 dark:bg-white/30', label: 'unknown' };
  };
  return (
    <section className="mt-4 rounded-lg border border-gray-200 bg-gray-50 dark:bg-white/[0.03] p-3">
      <div className="auth-mono-label flex items-center justify-between gap-1.5 mb-2">
        <span className="inline-flex items-center gap-1.5">
          <Crown className="w-3.5 h-3.5 text-amber-500" />
          Top donors · this battle
        </span>
        <span className="text-[10px] font-mono text-gray-500 normal-case tracking-normal">
          {rows.length} donor{rows.length === 1 ? '' : 's'} · {total.toLocaleString()} 💎
        </span>
      </div>
      <ol className="flex flex-col gap-1 text-xs font-mono">
        {rows.slice(0, 10).map((r, i) => {
          const display = r.nickname || r.unique_id || '—';
          const pct = (r.diamonds / total) * 100;
          const tone = sideTone(r.side);
          return (
            <li
              key={r.user_id}
              className="flex items-center gap-2 px-2 py-1.5 rounded border border-gray-200 bg-white dark:bg-white/[0.04]"
            >
              <span className="shrink-0 w-5 text-center text-gray-400 tabular-nums">
                #{i + 1}
              </span>
              <SafeAvatar
                src={r.avatar_url}
                size={28}
                className="shrink-0"
                fallback={
                  <span className="font-mono text-[10px] text-gray-500">
                    {display[0]?.toUpperCase()}
                  </span>
                }
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-gray-900">{display}</div>
                {r.unique_id && r.unique_id !== display && (
                  <div className="truncate text-[10px] text-gray-500">
                    @{r.unique_id}
                  </div>
                )}
              </div>
              <div className="shrink-0 text-right">
                <div className="tabular-nums font-bold text-amber-700 dark:text-amber-300">
                  {r.diamonds.toLocaleString()} 💎
                </div>
                <div className="text-[10px] text-gray-500 tabular-nums">
                  {r.gifts} gift{r.gifts === 1 ? '' : 's'} · {pct.toFixed(1)}%
                </div>
              </div>
              <span
                className="shrink-0 inline-flex items-center gap-1 ml-1 text-[9px] uppercase tracking-wider text-gray-500"
                title={`Backed ${tone.label}`}
              >
                <span className={`inline-block w-2 h-2 rounded-full ${tone.dot}`} />
                <span className="truncate max-w-[80px]">{tone.label}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** Top-N donut card. Drives the right-column Top Gifter card on
 *  the Top Gifters tab.
 *
 *  Pure presentation — does NOT fetch. The parent owns the data via
 *  `TikTokRoomGiftersTable`'s `onItemsChange` callback and passes
 *  whatever rows the table is currently showing here. Result: the
 *  donut visualises the CURRENT table page — paginate the table to
 *  page 2 and the donut shows page 2's rows. No duplicate request to
 *  `getRoomGifters`.
 *
 *  Slice colors via HSL rotation — each rank gets a distinct hue
 *  (starts at amber/38° to match the gift event color, then rotates
 *  the wheel evenly). Distinct colors let an operator identify any
 *  of the 10 users at a glance; single-hue alpha-fade was the wrong
 *  call for a categorical chart.
 *
 *  The right-side list shows only color-dot + truncated @handle —
 *  exact diamond values are intentionally absent (the gifters table
 *  on the left already carries them; the donut's role is just
 *  "who's in the top N"). */
function TopUserPieCard({
  title,
  icon,
  items,
  loading,
  emptyHint,
}: {
  title: string;
  icon: React.ReactNode;
  items: TikTokGifter[];
  loading?: boolean;
  emptyHint?: string;
}) {
  const cleanSlices = useMemo(
    () =>
      items
        .map((g) => ({
          // Use the @username (unique_id) as the slice label so the
          // list reads as a row of TikTok handles; fall back to the
          // display nickname only when the handle is missing.
          label: g.unique_id
            ? `@${g.unique_id}`
            : g.nickname || 'Unknown',
          value: g.diamonds ?? 0,
        }))
        .filter((s) => s.value > 0),
    [items],
  );
  const hasData = cleanSlices.length > 0;
  const slicesSum = cleanSlices.reduce((acc, s) => acc + s.value, 0);
  // No "Others" slice — the gifters endpoint returns row count, not
  // diamond sum, so any approximation we'd make for the long tail is
  // a lie (the tail's average diamonds-per-gifter is nowhere near the
  // top-10's average; whales + trickle distribution kills the math).
  // The donut therefore shows the top-10 proportions only. The header
  // chip + #1-share label both make this scope explicit.
  const top = cleanSlices[0];
  const topPct = hasData && slicesSum > 0 ? (top.value / slicesSum) * 100 : 0;

  // Per-slice colors via HSL rotation — each slice gets a distinct
  // hue so 10 users are visually identifiable at a glance. Starts at
  // 38° (amber, matching `eventColor('gift')`) and rotates the wheel
  // evenly. Saturation 70% + lightness 55% keeps every slice vivid
  // on both light and dark card surfaces.
  //
  // `sliceColorsFlat`: single color per slice for the legend dots on
  // the right. `sliceGradients`: radial-gradient ECharts spec per
  // slice (bright center → darker rim) so the donut reads with a
  // subtle dome-like depth. Faked-3D-via-shading is honest: it gives
  // the visual weight the user asked for without distorting slice
  // proportions the way a perspective-tilted "3D pie" would.
  const { sliceColorsFlat, sliceGradients } = useMemo(() => {
    const n = Math.max(cleanSlices.length, 1);
    const flat: string[] = [];
    const grad: {
      type: 'radial'; x: number; y: number; r: number;
      colorStops: { offset: number; color: string }[];
    }[] = [];
    for (let i = 0; i < cleanSlices.length; i++) {
      const hue = (38 + (360 / n) * i) % 360;
      flat.push(`hsl(${hue}, 70%, 55%)`);
      grad.push({
        type: 'radial',
        x: 0.5, y: 0.5, r: 0.85,
        colorStops: [
          { offset: 0,    color: `hsl(${hue}, 80%, 68%)` },
          { offset: 0.85, color: `hsl(${hue}, 75%, 52%)` },
          { offset: 1,    color: `hsl(${hue}, 70%, 40%)` },
        ],
      });
    }
    return { sliceColorsFlat: flat, sliceGradients: grad };
  }, [cleanSlices]);

  const option = useMemo(() => {
    if (!hasData) return null;
    return {
      tooltip: {
        trigger: 'item' as const,
        // Tooltip keeps the value visible on hover (so you can dig
        // into the exact 💎 amount per gifter without leaving the
        // card). The visible label list deliberately omits values —
        // the gifters table on the left already shows them in full.
        formatter: (params: { name: string; value: number; percent: number }) =>
          `${params.name}: ${params.value.toLocaleString()} 💎 (${params.percent}%)`,
      },
      series: [
        {
          type: 'pie' as const,
          radius: ['55%', '88%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: false,
          label: { show: false },
          labelLine: { show: false },
          // Thin separator stroke between slices + subtle outer
          // shadow makes the donut read with depth (the "3D feel"
          // requested, without perspective distortion).
          itemStyle: {
            borderWidth: 1.5,
            borderColor: 'rgba(255, 255, 255, 0.65)',
            shadowBlur: 10,
            shadowColor: 'rgba(0, 0, 0, 0.18)',
            shadowOffsetY: 3,
          },
          data: cleanSlices.map((s, i) => ({
            name: s.label,
            value: s.value,
            itemStyle: { color: sliceGradients[i] },
          })),
        },
      ],
    };
  }, [hasData, cleanSlices, sliceGradients]);

  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-3 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        {icon}
        {title}
        {hasData && (
          <span className="ml-auto text-[10px] font-mono text-gray-400">
            top {cleanSlices.length}
          </span>
        )}
      </div>
      {hasData && option ? (
        <div className="flex items-center gap-3">
          {/* LEFT: donut takes the rest of the card width as a square.
              `flex-1` lets it expand into space the list doesn't use;
              `min-w-0` lets it shrink on narrow viewports. Center
              label shows the #1's share of the visible top N. */}
          <div
            className="flex-1 min-w-0 aspect-square relative"
            role="img"
            aria-label={`${title} — top ${cleanSlices.length} users; leader ${top.label} at ${topPct.toFixed(0)}% of total`}
          >
            <ReactECharts
              echarts={echarts}
              option={option}
              style={{ height: '100%', width: '100%' }}
              opts={{ renderer: 'canvas' }}
              notMerge
              lazyUpdate
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <div className="text-2xl font-bold tabular-nums text-gray-900 leading-none">
                {topPct.toFixed(0)}%
              </div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 mt-1 text-center px-2 leading-tight">
                #1 of top {cleanSlices.length}
              </div>
            </div>
          </div>
          {/* RIGHT: ranked label list — color-dot + truncated handle
              only. `w-[140px]` hugs the content (most @handles fit
              comfortably; longer ones ellipsize) so the donut on the
              left can claim the rest of the card width. Values are
              intentionally absent (the table to the left has them);
              the pie's job is "who's in the top N". */}
          <ol className="shrink-0 w-[140px] space-y-0.5 text-[10px] font-mono">
            {cleanSlices.map((s, i) => (
              <li
                key={`${s.label}-${i}`}
                className="flex items-center gap-1.5 leading-tight"
              >
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ backgroundColor: sliceColorsFlat[i] }}
                />
                <span
                  className="truncate text-gray-700"
                  title={s.label}
                >
                  {s.label}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : loading ? (
        <div
          className="flex items-center justify-center text-xs text-gray-500 font-mono"
          style={{ minHeight: 180 }}
        >
          <Loader2 className="w-4 h-4 animate-spin mr-2" />
          Loading…
        </div>
      ) : (
        <div
          className="flex flex-col items-center justify-center text-center px-2 text-xs text-gray-500 font-mono"
          style={{ minHeight: 180 }}
        >
          <div className="mb-1">No data</div>
          {emptyHint && (
            <div className="text-[10px] text-gray-400 leading-snug">
              {emptyHint}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function normalizeHandle(o: { unique_id?: string | null; nickname?: string | null }): string | null {
  return (o.unique_id || o.nickname || null) || null;
}

function computeCountdown(match: TikTokMatch): number | null {
  const s = match.settings;
  if (!s) return null;
  const endMs = s.end_time_ms;
  if (endMs && endMs > 0) {
    const remaining = Math.max(0, Math.floor((endMs - Date.now()) / 1000));
    return remaining;
  }
  if (s.duration_seconds && s.start_time_ms) {
    const elapsed = Math.floor((Date.now() - s.start_time_ms) / 1000);
    return Math.max(0, s.duration_seconds - elapsed);
  }
  return null;
}

type MatchPhase =
  | 'pending'      // setup announced, hasn't started yet
  | 'live'         // countdown > 30s remaining
  | 'final'        // countdown 30s..0
  | 'overtime'     // countdown expired, ended_at not yet set (punish / victory lap)
  | 'completed';   // ended_at is set

interface MatchPhaseInfo {
  phase: MatchPhase;
  label: string;
  /** Tailwind tone classes for the badge */
  tone: string;
  /** Show an animated "live" dot. */
  animated: boolean;
}

function deriveMatchPhase(
  match: TikTokMatch,
  countdown: number | null,
): MatchPhaseInfo {
  if (match.ended_at) {
    return {
      phase: 'completed',
      label: 'Completed',
      tone: 'bg-gray-100 text-gray-700 dark:bg-gray-100/30',
      animated: false,
    };
  }
  if (!match.started_at) {
    return {
      phase: 'pending',
      label: 'Pending start',
      tone: 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300',
      animated: false,
    };
  }
  // started but not ended:
  if (countdown == null) {
    return {
      phase: 'live',
      label: 'Live',
      tone: 'bg-rose-500 text-white',
      animated: true,
    };
  }
  if (countdown <= 0) {
    // Countdown ran out — battle clock is done, but match_end hasn't fired
    // yet. TikTok holds the punish + victory lap here (~25–35 s).
    return {
      phase: 'overtime',
      label: 'Punish / Victory lap',
      tone: 'bg-amber-100 text-amber-900 dark:bg-amber-500/15 dark:text-amber-300',
      animated: true,
    };
  }
  if (countdown <= 30) {
    return {
      phase: 'final',
      label: 'Final stretch',
      tone: 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-300',
      animated: true,
    };
  }
  return {
    phase: 'live',
    label: 'Live',
    tone: 'bg-rose-500 text-white',
    animated: true,
  };
}

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

interface StatProps {
  label: string;
  value: string;
  tone: 'amber' | 'rose';
  big?: boolean;
}
function Stat({ label, value, tone, big }: StatProps) {
  const colorClass = tone === 'amber' ? 'text-amber-600' : 'text-rose-600';
  return (
    <div className="text-right">
      <div className="auth-mono-label">{label}</div>
      <div
        className={`tabular-nums font-bold ${colorClass} ${big ? 'text-2xl' : 'text-xl'}`}
        style={{ fontFamily: 'var(--font-mono-display)' }}
      >
        {value}
      </div>
    </div>
  );
}

interface BattlerCardProps {
  person: TikTokMatchOpponent | null;
  score: number;
  color: string;
  fallbackHandle: string | null;
  align: 'left' | 'right';
  winning: boolean;
  /** Optional bottom-row affordances. Each is independent — pass `null`
   *  / leave undefined to hide. Used so the same card renders for the
   *  page's host (no buttons — already on their page), teammates
   *  (profile + monitor), and rivals (profile + monitor). */
  onProfileClick?: () => void;
  /** Monitor state for this anchor: `null` hides the row entirely;
   *  `'add'` shows the "+ monitor" CTA; `'monitored'` shows a link to
   *  the live page. The container (LiveMatchView) owns the
   *  subscription set + add-modal trigger and threads them in. */
  monitorState?: 'add' | 'monitored' | null;
  onMonitorClick?: () => void;
  /** Used for the "monitored" link target — the handle without "@". */
  monitorHandle?: string | null;
}

function BattlerCard({
  person,
  score,
  color,
  fallbackHandle,
  align,
  winning,
  onProfileClick,
  monitorState,
  onMonitorClick,
  monitorHandle,
}: BattlerCardProps) {
  const handle = person ? normalizeHandle(person) : fallbackHandle;
  const nickname = person?.nickname || handle || '—';
  const avatarUrl = person?.avatar_url || null;
  const tags = person?.tags || [];
  const hasFooterActions = !!onProfileClick || monitorState != null;

  return (
    <div
      className={`relative rounded-xl p-4 transition-shadow ${
        winning ? 'shadow-lg' : ''
      }`}
      style={{
        backgroundColor: `${color}10`,
        border: `1px solid ${color}40`,
        boxShadow: winning ? `0 0 0 2px ${color}55` : undefined,
      }}
    >
      <div
        className={`flex items-center gap-3 ${align === 'right' ? 'flex-row-reverse text-right' : ''}`}
      >
        <div
          className="shrink-0 rounded-full"
          style={{ boxShadow: `0 0 0 3px ${color}`, backgroundColor: color }}
        >
          <SafeAvatar
            src={avatarUrl}
            size={64}
            className="!bg-transparent dark:!bg-transparent"
            fallback={
              <span className="font-mono text-xl text-white">
                {(nickname[0] || '?').toUpperCase()}
              </span>
            }
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-bold text-base truncate">{nickname}</div>
          {handle && (
            <div className="text-xs text-gray-500 font-mono truncate">
              @{handle.replace(/^@/, '')}
            </div>
          )}
          {tags.length > 0 && (
            <div
              className={`mt-1.5 flex flex-wrap gap-1 ${align === 'right' ? 'justify-end' : ''}`}
            >
              {tags.slice(0, 3).map((tag, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono"
                  style={{ backgroundColor: `${color}25`, color: color }}
                >
                  {tag.icon_url && (
                    <img
                      src={tag.icon_url}
                      alt=""
                      className="w-3 h-3"
                      referrerPolicy="no-referrer"
                    />
                  )}
                  {tag.content}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div
        className={`mt-3 text-3xl font-bold tabular-nums ${align === 'right' ? 'text-right' : ''}`}
        style={{ color, fontFamily: 'var(--font-mono-display)' }}
      >
        <AnimatedScore
          value={score}
          // Mirror the side's accent on the floating delta chip so
          // host gains rise green, rival gains rise red.
          tone={color === '#10b981' ? 'emerald' : 'rose'}
          deltaSize="sm"
        />
      </div>
      {hasFooterActions && (
        <div
          className={`mt-3 pt-2.5 border-t flex flex-wrap items-center gap-1.5 ${align === 'right' ? 'justify-end' : ''}`}
          style={{ borderColor: `${color}30` }}
        >
          {onProfileClick && (
            <button
              type="button"
              onClick={onProfileClick}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider text-gray-500 hover:text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-500/10 transition-colors"
              title="Open profile — gift / comment history"
            >
              <User className="w-3 h-3" />
              Profile
            </button>
          )}
          {monitorState === 'monitored' && monitorHandle && (
            <Link
              to="/admin/tiktok/$handle"
              params={{ handle: monitorHandle }}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-200 dark:hover:bg-emerald-500/25 transition-colors"
              title={`Open @${monitorHandle}'s live page — already monitored`}
            >
              <Radio className="w-3 h-3" />
              Monitoring
            </Link>
          )}
          {monitorState === 'add' && onMonitorClick && (
            <button
              type="button"
              onClick={onMonitorClick}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-primary-100 dark:bg-primary-500/15 text-primary-700 dark:text-primary-300 hover:bg-primary-200 dark:hover:bg-primary-500/25 transition-colors"
              title={monitorHandle ? `Start monitoring @${monitorHandle}'s lives` : 'Start monitoring'}
            >
              <Radio className="w-3 h-3" />
              + Monitor
            </button>
          )}
        </div>
      )}
    </div>
  );
}

interface PastMatchesTableProps {
  matches: TikTokMatch[];
  hostHandle: string;
  hostProfile: HostProfile | null;
  onSelect?: (m: TikTokMatch) => void;
  scopeLabel?: string;
}

const PAST_MATCHES_PAGE_SIZE = 5;

function PastMatchesTable({
  matches,
  hostHandle,
  hostProfile,
  onSelect,
  scopeLabel,
}: PastMatchesTableProps) {
  const { tz } = useTikTokTimezone();
  const [page, setPage] = useState(0);

  // Reset to page 0 whenever the matches list resets (room change, etc.).
  useEffect(() => {
    setPage(0);
  }, [matches.length]);

  if (matches.length === 0) {
    return (
      <div className="py-8 flex flex-col items-center gap-2 text-center">
        <Swords className="w-8 h-8 text-gray-300 dark:text-gray-100/40" />
        <p className="text-sm text-gray-700 dark:text-gray-300 font-medium">
          No PK battles yet
        </p>
        <p className="text-xs text-gray-500 max-w-xs">
          {scopeLabel
            ? `Nothing to show for: ${scopeLabel}.`
            : 'This view doesn\'t contain any PK battles.'}
          {' '}
          When @{hostHandle} starts a battle it will appear here.
        </p>
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil(matches.length / PAST_MATCHES_PAGE_SIZE));
  const pageStart = page * PAST_MATCHES_PAGE_SIZE;
  const visible = matches.slice(pageStart, pageStart + PAST_MATCHES_PAGE_SIZE);

  return (
    <div>
      {/* Desktop: 6-column table (md+). Below md the columns can't
          fit, so we render a stacked card list instead — no horizontal
          scroll. */}
      <table className="hidden md:table w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="text-left py-2 auth-mono-label">When</th>
            <th className="text-left py-2 auth-mono-label">Matchup</th>
            <th className="text-right py-2 auth-mono-label">Score</th>
            <th className="text-right py-2 auth-mono-label">Duration</th>
            <th className="text-right py-2 auth-mono-label">Diamonds</th>
            <th className="text-right py-2 auth-mono-label">Result</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((m) => {
            const { hostScore, rivalScore } = computeMatchScores(m, hostHandle);
            return (
              <tr
                key={m.id}
                className={
                  'border-b border-gray-100 transition-colors ' +
                  (onSelect ? 'hover:bg-gray-50 cursor-pointer' : '')
                }
                onClick={onSelect ? () => onSelect(m) : undefined}
                title={onSelect ? 'Click for full event log' : undefined}
              >
                <td className="py-2 font-mono text-xs text-gray-600 whitespace-nowrap align-middle">
                  {m.started_at ? fmtMonthDayTime(m.started_at, tz) : '—'}
                </td>
                <td className="py-2 align-middle">
                  <MatchupCell
                    match={m}
                    hostHandle={hostHandle}
                    hostProfile={hostProfile}
                  />
                </td>
                <td className="py-2 text-right font-mono text-xs tabular-nums align-middle whitespace-nowrap">
                  <span
                    className={
                      hostScore > rivalScore
                        ? 'text-emerald-700 dark:text-emerald-300 font-semibold'
                        : 'text-gray-700'
                    }
                  >
                    {hostScore.toLocaleString()}
                  </span>
                  <span className="mx-1 text-gray-400">:</span>
                  <span
                    className={
                      rivalScore > hostScore
                        ? 'text-rose-700 dark:text-rose-300 font-semibold'
                        : 'text-gray-700'
                    }
                  >
                    {rivalScore.toLocaleString()}
                  </span>
                </td>
                <td className="py-2 text-right font-mono text-xs align-middle">
                  {formatBattleDuration(m)}
                </td>
                <td className="py-2 text-right font-mono text-xs tabular-nums align-middle">
                  {(m.diamonds_total ?? 0).toLocaleString()}
                  <span className="ml-1 text-amber-600">💎</span>
                </td>
                <td className="py-2 text-right align-middle">
                  <span
                    className={
                      'font-mono text-[10px] px-1.5 py-0.5 rounded uppercase ' +
                      (RESULT_TONE[m.result] ?? RESULT_TONE.ended)
                    }
                  >
                    {m.result}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* Mobile: one card per match (below md). Header row: when +
          result chip. Middle: matchup (host vs rival). Bottom: score,
          duration, diamonds in three compact mono stats. */}
      <ul className="md:hidden flex flex-col gap-2">
        {visible.map((m) => {
          const { hostScore, rivalScore } = computeMatchScores(m, hostHandle);
          return (
            <li
              key={m.id}
              className={
                'rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 transition-colors ' +
                (onSelect ? 'cursor-pointer hover:bg-gray-50' : '')
              }
              onClick={onSelect ? () => onSelect(m) : undefined}
              title={onSelect ? 'Tap for full event log' : undefined}
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className="font-mono text-xs text-gray-600 whitespace-nowrap">
                  {m.started_at ? fmtMonthDayTime(m.started_at, tz) : '—'}
                </span>
                <span
                  className={
                    'font-mono text-[10px] px-1.5 py-0.5 rounded uppercase ' +
                    (RESULT_TONE[m.result] ?? RESULT_TONE.ended)
                  }
                >
                  {m.result}
                </span>
              </div>
              <div className="mb-2">
                <MatchupCell
                  match={m}
                  hostHandle={hostHandle}
                  hostProfile={hostProfile}
                />
              </div>
              <div className="pt-2 border-t border-gray-100 grid grid-cols-3 gap-2 text-[11px] font-mono">
                <div className="flex flex-col">
                  <span className="text-[10px] uppercase tracking-wider text-gray-400">Score</span>
                  <span className="tabular-nums">
                    <span
                      className={
                        hostScore > rivalScore
                          ? 'text-emerald-700 dark:text-emerald-300 font-semibold'
                          : 'text-gray-700'
                      }
                    >
                      {hostScore.toLocaleString()}
                    </span>
                    <span className="mx-1 text-gray-400">:</span>
                    <span
                      className={
                        rivalScore > hostScore
                          ? 'text-rose-700 dark:text-rose-300 font-semibold'
                          : 'text-gray-700'
                      }
                    >
                      {rivalScore.toLocaleString()}
                    </span>
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] uppercase tracking-wider text-gray-400">Duration</span>
                  <span className="tabular-nums text-gray-700">
                    {formatBattleDuration(m)}
                  </span>
                </div>
                <div className="flex flex-col text-right">
                  <span className="text-[10px] uppercase tracking-wider text-gray-400">Diamonds</span>
                  <span className="tabular-nums text-gray-900 font-semibold">
                    {(m.diamonds_total ?? 0).toLocaleString()}
                    <span className="ml-1 text-amber-600">💎</span>
                  </span>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-3 mt-1 border-t border-gray-100">
          <span className="text-[11px] font-mono text-gray-500">
            {pageStart + 1}–{Math.min(matches.length, pageStart + visible.length)} of{' '}
            {matches.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setPage((p) => Math.max(0, p - 1));
              }}
              disabled={page === 0}
              className="px-2 py-1 text-xs font-mono rounded text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-transparent"
              aria-label="Previous page"
            >
              ‹ Prev
            </button>
            <span className="text-[11px] font-mono text-gray-500 px-1">
              {page + 1} / {totalPages}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setPage((p) => Math.min(totalPages - 1, p + 1));
              }}
              disabled={page >= totalPages - 1}
              className="px-2 py-1 text-xs font-mono rounded text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-transparent"
              aria-label="Next page"
            >
              Next ›
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

interface MatchupCellProps {
  match: TikTokMatch;
  hostHandle: string;
  hostProfile: HostProfile | null;
}

/** Renders host on the left, "vs", rival(s) on the right — each with
 *  avatar + nickname + @handle. The winner gets a crown badge. Falls
 *  back gracefully when avatar/nickname/handle are missing (User icon). */
function MatchupCell({ match, hostHandle, hostProfile }: MatchupCellProps) {
  const opponents = match.opponents || [];
  // Merge host data: opponent record (for team/score/avatar from event)
  // ⊕ subscription profile (canonical avatar/nickname).
  const hostFromMatch = opponents.find((o) => normalizeHandle(o) === hostHandle);
  const host: TikTokMatchOpponent = {
    user_id: hostFromMatch?.user_id ?? hostProfile?.profile_user_id ?? null,
    unique_id: hostFromMatch?.unique_id ?? hostHandle,
    nickname: hostFromMatch?.nickname ?? hostProfile?.nickname ?? null,
    avatar_url: hostFromMatch?.avatar_url ?? hostProfile?.avatar_url ?? null,
  };
  const rivals = opponents.filter((o) => normalizeHandle(o) !== hostHandle);
  const winnerUserId = match.winner_user_id;

  const isWinner = (o: TikTokMatchOpponent): boolean => {
    if (!winnerUserId) return false;
    const oid = o.user_id != null ? String(o.user_id) : null;
    return oid != null && oid === String(winnerUserId);
  };

  return (
    <div className="flex items-center gap-2 min-w-0">
      <OpponentChip opponent={host} side="host" winner={isWinner(host)} />
      <span className="text-rose-500 font-bold text-xs shrink-0">vs</span>
      {rivals.length === 0 ? (
        <span className="text-xs text-gray-400 italic">unknown</span>
      ) : (
        rivals.map((o, i) => (
          <div key={i} className="flex items-center gap-1 min-w-0">
            {i > 0 && <span className="text-rose-400 text-xs shrink-0">·</span>}
            <OpponentChip opponent={o} side="rival" winner={isWinner(o)} />
          </div>
        ))
      )}
    </div>
  );
}

interface OpponentChipProps {
  opponent: TikTokMatchOpponent;
  side: 'host' | 'rival';
  winner?: boolean;
}

function OpponentChip({ opponent, side, winner = false }: OpponentChipProps) {
  const handle = (opponent.unique_id || '').replace(/^@/, '');
  // Build the label with a sane fallback chain. We avoid raw "?" — if
  // we have a numeric user_id we show that, otherwise "unknown".
  const initial = (opponent.nickname?.[0] || handle?.[0] || '').toUpperCase();
  const showInitial = initial.length > 0;
  const labelText =
    opponent.nickname ||
    handle ||
    (opponent.user_id ? `User ${String(opponent.user_id).slice(-6)}` : 'unknown');
  const ring =
    side === 'host'
      ? 'ring-emerald-200 dark:ring-emerald-500/30'
      : 'ring-rose-200 dark:ring-rose-500/30';
  const fallback =
    side === 'host'
      ? 'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300'
      : 'bg-rose-100 dark:bg-rose-500/20 text-rose-700 dark:text-rose-300';
  return (
    <div className="flex items-center gap-2 min-w-0 relative">
      <div className="relative shrink-0">
        <div className={`rounded-full ${fallback}`}>
          <SafeAvatar
            src={opponent.avatar_url}
            size={28}
            className={`!bg-transparent dark:!bg-transparent ring-1 ${ring}`}
            fallback={
              showInitial ? (
                <span className="font-mono text-[11px]">{initial}</span>
              ) : (
                <User className="w-3.5 h-3.5" />
              )
            }
          />
        </div>
        {winner && (
          <span
            className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-amber-400 text-amber-900 dark:bg-amber-300 flex items-center justify-center shadow-sm ring-1 ring-white dark:ring-gray-900"
            title="Battle winner"
          >
            <Crown className="w-2.5 h-2.5" />
          </span>
        )}
      </div>
      <div className="min-w-0">
        <div className="text-sm font-medium text-gray-900 truncate flex items-center gap-1">
          {labelText}
        </div>
        {handle && (
          <div className="text-[10px] font-mono text-gray-500 truncate">@{handle}</div>
        )}
      </div>
    </div>
  );
}

/** Compute host vs. rival score for a match. Mirrors LiveMatchView's
 *  per-anchor → team-aggregate fallback so the table and the live
 *  view agree. */
function computeMatchScores(
  match: TikTokMatch,
  hostHandle: string,
): { hostScore: number; rivalScore: number } {
  const opponents = match.opponents || [];
  const host = opponents.find((o) => normalizeHandle(o) === hostHandle);
  const rivals = opponents.filter((o) => normalizeHandle(o) !== hostHandle);
  const scores = match.scores || {};

  const teamScore = (teamId: number | string | null | undefined): number => {
    if (teamId == null) return 0;
    return Number(scores[String(teamId)] ?? 0);
  };

  const hostScore = (() => {
    if (host?.score != null) return Number(host.score);
    return teamScore(host?.team_id);
  })();

  const rivalScore = rivals.reduce((acc, r) => {
    if (r.score != null) return acc + Number(r.score);
    return acc + teamScore(r.team_id);
  }, 0);

  return { hostScore, rivalScore };
}


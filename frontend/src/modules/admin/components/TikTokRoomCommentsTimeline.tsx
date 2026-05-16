/**
 * Generalized event timeline for a single TikTok room.
 *
 * Originally a comments-only view; extended to support a per-type filter
 * so admins can browse any captured event type (gifts, subscribes,
 * captions, polls, donations, live pause, etc.).
 *
 * The component name is kept (`TikTokRoomCommentsTimeline`) for backward
 * compatibility with existing imports — the default `type` is still
 * `comment`, so callers that don't pass `defaultType` get the original
 * behavior.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowDown,
  Captions,
  ChevronLeft,
  ChevronRight,
  Filter,
  Gem,
  HandCoins,
  Heart,
  Loader2,
  MessageSquare,
  Pause,
  Play,
  Search,
  Smile,
  Star,
  Trophy,
  Users,
  X,
} from 'lucide-react';

import { type TikTokEvent } from '@admin/services/tiktok';
import { useTikTokApi } from '@admin/contexts/TikTokApiContext';
import { TikTokUserBadges, type IdentityBlock } from './TikTokUserBadges';
import { SafeAvatar } from '@admin/components/SafeAvatar';
import {
  useTikTokTimezone,
  dateKeyInZone,
  partsInZone,
} from '@admin/contexts/TikTokTimezoneContext';

export type TimelineEventType =
  | 'comment'
  | 'gift'
  | 'subscribe'
  | 'caption'
  | 'poll'
  | 'question'
  | 'emote'
  | 'envelope'
  | 'rank_update'
  | 'rank_text'
  | 'donation'
  | 'live_pause'
  | 'live_unpause';

interface RoomCommentsTimelineProps {
  roomId: string | null;
  /** Day-aggregate view: extra rooms whose events are summed alongside
   *  the path roomId. Empty / undefined → single-room behaviour. */
  extraRoomIds?: string[];
  /** Active range — passed through to the search API. */
  range?: { since?: string; until?: string; window_minutes?: number };
  /** Initial event-type selection. Defaults to "comment" so existing
   *  call sites keep their previous behavior. */
  defaultType?: TimelineEventType;
  /** When true, the in-component type-filter chip row is rendered.
   *  Default false — the live-detail page already labels the tab
   *  "Comments" so the chips inside (Comments / Gifts / Subs / …)
   *  were redundant. Future callers that want the multi-type browser
   *  can opt back in. */
  showTypeFilter?: boolean;
  /** Bumping this from the parent triggers an out-of-band refetch
   *  (used by the card-header refresh button on the Events tab). */
  refreshKey?: number;
  /** Bubble the server-side total up so the parent can render `(N)`
   *  on its tab label without a duplicate query. */
  onTotalChange?: (total: number) => void;
  /** When the user clicks a row, the parent can open the gifter modal.
   *  `tab: 'comments'` is included so the unified modal opens on the
   *  Comments tab directly — the user clicked a comment, they
   *  probably want to see more comments, not the gifts tab. */
  onSelectUser?: (u: {
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
    tab?: 'comments';
  }) => void;
}

// 10 was punishingly low for a chatty live (10 comments drop in
// seconds). 25 fits the default scroll height comfortably; power
// users can dial up to 200.
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const DEFAULT_PAGE_SIZE = 25;
// Live-tail poll cadence — fast enough to feel real-time, slow
// enough that a 30-comment-per-second creator doesn't hammer the
// API.
const LIVE_TAIL_INTERVAL_MS = 3_000;

// Order of chips left → right. We expose only types that are realistically
// browseable; viewer_count + like + join + follow + share are too noisy
// to read line-by-line (and are already in the chart counts).
const TYPE_OPTIONS: Array<{
  key: TimelineEventType;
  label: string;
  icon: React.ReactNode;
  color: string;
}> = [
  { key: 'comment',     label: 'Comments',  icon: <MessageSquare className="w-3 h-3" />, color: '#0ea5e9' },
  { key: 'gift',        label: 'Gifts',     icon: <Gem className="w-3 h-3" />,           color: '#f59e0b' },
  { key: 'subscribe',   label: 'Subs',      icon: <Star className="w-3 h-3" />,          color: '#f43f5e' },
  { key: 'caption',     label: 'Captions',  icon: <Captions className="w-3 h-3" />,      color: '#14b8a6' },
  { key: 'poll',        label: 'Polls',     icon: <Trophy className="w-3 h-3" />,        color: '#8b5cf6' },
  { key: 'question',    label: 'Q&A',       icon: <Activity className="w-3 h-3" />,      color: '#6366f1' },
  { key: 'emote',       label: 'Emotes',    icon: <Smile className="w-3 h-3" />,         color: '#ec4899' },
  { key: 'envelope',    label: 'Envelopes', icon: <Heart className="w-3 h-3" />,         color: '#ef4444' },
  { key: 'donation',    label: 'Donations', icon: <HandCoins className="w-3 h-3" />,     color: '#10b981' },
  { key: 'rank_update', label: 'Rank ↻',    icon: <Users className="w-3 h-3" />,         color: '#a855f7' },
  { key: 'live_pause',  label: 'Pauses',    icon: <Pause className="w-3 h-3" />,         color: '#9ca3af' },
];

export function TikTokRoomCommentsTimeline({
  roomId,
  extraRoomIds,
  range,
  defaultType = 'comment',
  showTypeFilter = false,
  refreshKey = 0,
  onTotalChange,
  onSelectUser,
}: RoomCommentsTimelineProps) {
  const tiktokApi = useTikTokApi();
  const { tz } = useTikTokTimezone();
  // Stable string key for the extras — array identity flips every
  // render even when contents don't.
  const extraKey = (extraRoomIds ?? []).join(',');
  const [activeType, setActiveType] = useState<TimelineEventType>(defaultType);
  const [events, setEvents] = useState<TikTokEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [loading, setLoading] = useState(false);
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  // Live-tail mode — polling refetch every ~3s when conditions are
  // met (page 1, no search, tab visible). Defaults on for the comment
  // tab where it's the most useful; can be toggled per-session.
  const [liveTail, setLiveTail] = useState(true);
  // Number of new items that arrived while the user was scrolled
  // away from the top. Drives the "↓ N new" jump-to-latest pill.
  const [unreadDelta, setUnreadDelta] = useState(0);
  // Scroll-container ref + isAtTop tracker. We only auto-scroll the
  // container when the user is already pinned to the top — otherwise
  // we'd yank them away from whatever they're reading.
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const isAtTopRef = useRef(true);
  // Topmost event id from the previous fetch — used to count newly-
  // arrived items between ticks for the unread badge.
  const prevTopIdRef = useRef<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setSearchQuery(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const activeMeta = useMemo(
    () => TYPE_OPTIONS.find((t) => t.key === activeType) ?? TYPE_OPTIONS[0],
    [activeType]
  );

  // Common filter set used by both /events/search and /events/count so
  // the row-list and the total stay in lock-step.
  const filters = useMemo(() => {
    if (!roomId) return null;
    const f: {
      room_id?: string;
      room_ids?: string[];
      type: string;
      since?: string;
      until?: string;
      q?: string;
    } = { type: activeType };
    if (extraRoomIds && extraRoomIds.length > 0) {
      // Multi-room: backend resolves room_ids ∪ {roomId} on the SQL
      // side. Sending both keeps single-room callers untouched.
      f.room_id = roomId;
      f.room_ids = Array.from(new Set([roomId, ...extraRoomIds]));
    } else {
      f.room_id = roomId;
    }
    if (range?.since) f.since = range.since;
    if (range?.until) f.until = range.until;
    if (range?.window_minutes) {
      const since = new Date(Date.now() - range.window_minutes * 60 * 1000);
      f.since = since.toISOString();
    }
    if (searchQuery) f.q = searchQuery;
    return f;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, extraKey, activeType, range?.since, range?.until, range?.window_minutes, searchQuery]);

  // Reset offset whenever the result set itself changes shape.
  useEffect(() => {
    setOffset(0);
  }, [activeType, roomId, extraKey, range?.since, range?.until, range?.window_minutes, searchQuery, pageSize, refreshKey]);

  // Fetch the active page + total in parallel.
  useEffect(() => {
    if (!filters) {
      setEvents([]);
      setTotal(0);
      onTotalChange?.(0);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all([
      tiktokApi.searchEvents({ ...filters, limit: pageSize, offset }),
      tiktokApi.countEvents(filters),
    ])
      .then(([rows, countRes]) => {
        if (cancelled) return;
        // Tally newly-arrived items vs the previous top id. When the
        // user is at the top of the scroll container we auto-show
        // them; when scrolled down, we bump the unread pill instead.
        const prevTopId = prevTopIdRef.current;
        if (prevTopId && rows.length > 0) {
          let added = 0;
          for (const r of rows) {
            if (String(r.id) === prevTopId) break;
            added += 1;
          }
          if (added > 0 && !isAtTopRef.current) {
            setUnreadDelta((n) => n + added);
          }
        }
        prevTopIdRef.current = rows[0] ? String(rows[0].id) : null;
        setEvents(rows);
        setTotal(countRes.total);
        onTotalChange?.(countRes.total);
      })
      .catch(() => {
        if (cancelled) return;
        setEvents([]);
        setTotal(0);
        onTotalChange?.(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // refreshKey forces a refetch when the parent bumps it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, offset, pageSize, refreshKey]);

  // Live-tail polling. Conditions to fire:
  //   • liveTail toggle on
  //   • we're on page 1 (offset = 0) — pagination + tail can't coexist
  //   • no active search — chasing a ranged query in real-time is noise
  //   • tab is visible — backgrounded tabs shouldn't hammer the API
  // Pause is automatic via the visibility check; the user can also
  // explicitly toggle off.
  useEffect(() => {
    if (!filters) return;
    if (!liveTail) return;
    if (offset !== 0) return;
    if (searchQuery) return;
    let interval: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (interval != null) return;
      interval = setInterval(() => {
        if (document.visibilityState !== 'visible') return;
        // Touch the offset-state via a no-op effect bump: re-fire
        // the same fetch by depending on a tick counter.
        tiktokApi
          .searchEvents({ ...filters, limit: pageSize, offset: 0 })
          .then((rows) => {
            const prevTopId = prevTopIdRef.current;
            let added = 0;
            if (prevTopId && rows.length > 0) {
              for (const r of rows) {
                if (String(r.id) === prevTopId) break;
                added += 1;
              }
            }
            prevTopIdRef.current = rows[0] ? String(rows[0].id) : null;
            setEvents(rows);
            if (isAtTopRef.current) {
              // user is reading the top — silently update
            } else if (added > 0) {
              setUnreadDelta((n) => n + added);
            }
          })
          .catch(() => { /* silent — next tick will retry */ });
        tiktokApi
          .countEvents(filters)
          .then((c) => {
            setTotal(c.total);
            onTotalChange?.(c.total);
          })
          .catch(() => { /* silent */ });
      }, LIVE_TAIL_INTERVAL_MS);
    };
    const stop = () => {
      if (interval != null) {
        clearInterval(interval);
        interval = null;
      }
    };
    if (document.visibilityState === 'visible') start();
    const onVis = () => {
      if (document.visibilityState === 'visible') start();
      else stop();
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [filters, liveTail, offset, searchQuery, pageSize, onTotalChange]);

  // Track scroll position so live-tail knows when to silently update
  // vs bump the unread pill.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      isAtTopRef.current = el.scrollTop <= 8;
      // When the user scrolls back to top, clear the unread pill.
      if (isAtTopRef.current && unreadDelta > 0) {
        setUnreadDelta(0);
      }
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [unreadDelta]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + events.length, total);

  const grouped = useMemo(() => {
    const out: Array<{ dateLabel: string; items: TikTokEvent[] }> = [];
    let last = '';
    for (const e of events) {
      const label = dateKeyInZone(e.ts, tz);
      if (label !== last) {
        out.push({ dateLabel: label, items: [] });
        last = label;
      }
      out[out.length - 1].items.push(e);
    }
    return out;
  }, [events, tz]);

  if (!roomId) {
    return (
      <p className="text-sm text-gray-500 py-6 text-center">
        Select a broadcast to view events.
      </p>
    );
  }

  // The chip row is opt-in — most callers (the live-detail page in
  // particular) already label their tab "Comments", so showing a
  // multi-type switcher inside the comments view duplicates the same
  // label. Pass `showTypeFilter` to bring it back.
  const typeChips = showTypeFilter ? (
    <div className="flex items-center gap-1 mb-3 flex-wrap">
      <Filter className="w-3 h-3 text-gray-400 mr-0.5" />
      {TYPE_OPTIONS.map((t) => {
        const isActive = t.key === activeType;
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveType(t.key)}
            className={
              'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors ' +
              (isActive
                ? 'text-white shadow-sm'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:hover:bg-white/10')
            }
            style={isActive ? { backgroundColor: t.color } : undefined}
          >
            {t.icon}
            {t.label}
          </button>
        );
      })}
    </div>
  ) : null;

  // Toolbar: search + live-tail toggle + count. Sticky at the top
  // of the scroll region so chrome doesn't scroll away on long lists.
  const toolbar = (
    <div className="space-y-2 pb-2">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
        <input
          type="search"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder={`Search ${activeMeta.label.toLowerCase()} by user or text…`}
          className="w-full pl-8 pr-8 py-1.5 text-sm rounded border border-gray-200 bg-white dark:bg-white/5 focus:outline-none focus:ring-1 focus:ring-sky-400 focus:border-sky-400"
        />
        {searchInput && (
          <button
            type="button"
            onClick={() => setSearchInput('')}
            aria-label="Clear search"
            // Hit-target padding so touch users can actually tap.
            className="absolute right-1 top-1/2 -translate-y-1/2 inline-flex items-center justify-center w-7 h-7 text-gray-400 hover:text-gray-700"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-gray-600 flex-wrap">
        <span className="tabular-nums">
          {showingFrom.toLocaleString()}–{showingTo.toLocaleString()} of{' '}
          {total.toLocaleString()} {activeMeta.label.toLowerCase()}
          {searchQuery && ` matching "${searchQuery}"`}
          {loading && <Loader2 className="ml-1.5 w-3 h-3 inline animate-spin" />}
        </span>
        {/* Live-tail toggle. The pulse dot is the same axis the
            notifications drawer uses for its connection signal so
            the visual language stays consistent across the app. */}
        <button
          type="button"
          onClick={() => setLiveTail((v) => !v)}
          className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full font-mono text-[11px] border transition-colors ${
            liveTail
              ? 'bg-rose-50 border-rose-200 text-rose-700 dark:bg-rose-500/10 dark:border-rose-500/30 dark:text-rose-300'
              : 'bg-white dark:bg-white/5 border-gray-200 text-gray-600 hover:border-gray-300'
          }`}
          title={
            liveTail
              ? `Live-tail on — refreshes every ${LIVE_TAIL_INTERVAL_MS / 1000}s when on page 1`
              : 'Live-tail off — manual refresh only'
          }
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${liveTail ? 'bg-rose-500 animate-pulse' : 'bg-gray-400'}`}
            aria-hidden
          />
          {liveTail ? 'Live' : 'Paused'}
        </button>
      </div>
    </div>
  );

  if (loading && events.length === 0) {
    return (
      <div>
        {typeChips}
        {toolbar}
        <div className="py-8 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
          Loading {activeMeta.label.toLowerCase()}…
        </div>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div>
        {typeChips}
        {toolbar}
        <p className="text-sm text-gray-500 py-6 text-center">
          {activeMeta.icon}
          <span className="ml-2">
            {searchQuery
              ? `No ${activeMeta.label.toLowerCase()} match that search.`
              : `No ${activeMeta.label.toLowerCase()} in this scope.`}
          </span>
        </p>
      </div>
    );
  }

  return (
    <div className="relative">
      {typeChips}
      {/* Sticky toolbar — keeps search + count + live toggle pinned
          while the user scrolls a long list. */}
      <div className="sticky top-0 z-20 bg-white pt-1 -mx-1 px-1 border-b border-gray-200">
        {toolbar}
      </div>

      {/* Viewport-relative scroll height: was a fixed 28rem (448px)
          which felt punishingly small on a 1440p display and crowded
          on narrow phones. `min(60vh, 32rem)` gives 60% of viewport
          on phones, capped at 32rem on desktops. */}
      <div
        ref={scrollRef}
        className="relative max-h-[min(60vh,32rem)] overflow-y-auto pr-1 -mr-1"
      >
        <div
          aria-hidden
          className="absolute left-9 sm:left-[5.25rem] top-0 bottom-0 w-px bg-gray-200"
        />

        {grouped.map((group) => (
          <div key={group.dateLabel} className="relative">
            <div className="sticky top-0 z-10 bg-white py-1 mb-1.5">
              <span className="text-[10px] font-mono text-gray-600 uppercase tracking-wider">
                {group.dateLabel}
              </span>
            </div>

            {group.items.map((e) => (
              <EventRow
                key={e.id}
                event={e}
                type={activeType}
                color={activeMeta.color}
                searchQuery={searchQuery}
                onSelectUser={onSelectUser}
              />
            ))}
          </div>
        ))}
      </div>

      {/* Jump-to-latest pill — fires only when live-tail brought in
          new items while the user was scrolled away from the top. */}
      {unreadDelta > 0 && (
        <button
          type="button"
          onClick={() => {
            scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
            setUnreadDelta(0);
          }}
          className="absolute bottom-16 sm:bottom-14 left-1/2 -translate-x-1/2 z-30 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-sky-500 text-white text-xs font-mono shadow-lg hover:bg-sky-600 animate-in fade-in"
        >
          <ArrowDown className="w-3.5 h-3.5" />
          {unreadDelta} new
        </button>
      )}

      {/* Page-by-page pagination + per-page selector. Replaces the
          previous "Load more" cursor scroll: explicit pages are easier
          to share, easier to cap (default 10 = the user's request),
          and let us show "page X of Y" plus the running count. */}
      {total > 0 && (
        <div className="mt-3 flex items-center justify-between gap-2 text-xs flex-wrap">
          <span className="font-mono text-gray-500">
            page {currentPage} / {totalPages}
            {loading && <Loader2 className="ml-2 w-3 h-3 inline animate-spin" />}
          </span>
          <div className="flex items-center gap-3">
            <label className="inline-flex items-center gap-1 font-mono text-[11px] text-gray-500">
              per page
              <select
                value={pageSize}
                onChange={(e) => setPageSize(Number(e.target.value))}
                className="font-mono text-[11px] py-0.5 pl-1 pr-1 rounded border border-gray-200 bg-white dark:bg-white/5"
                aria-label="Rows per page"
              >
                {PAGE_SIZE_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setOffset((o) => Math.max(0, o - pageSize))}
                disabled={offset === 0 || loading}
                // 36px on mobile (touch-friendly), 28px on sm+
                className="inline-flex items-center justify-center w-9 h-9 sm:w-7 sm:h-7 rounded border border-gray-200 text-gray-700 hover:bg-gray-50 dark:hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
                aria-label="Previous page"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() =>
                  setOffset((o) =>
                    o + pageSize < total ? o + pageSize : o
                  )
                }
                disabled={offset + pageSize >= total || loading}
                className="inline-flex items-center justify-center w-9 h-9 sm:w-7 sm:h-7 rounded border border-gray-200 text-gray-700 hover:bg-gray-50 dark:hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
                aria-label="Next page"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

interface EventRowProps {
  event: TikTokEvent;
  type: TimelineEventType;
  color: string;
  searchQuery: string;
  onSelectUser?: (u: {
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
    tab?: 'comments';
  }) => void;
}

function EventRow({
  event,
  type,
  color,
  searchQuery,
  onSelectUser,
}: EventRowProps) {
  const { tz } = useTikTokTimezone();
  const p = (event.payload || {}) as Record<string, unknown>;
  const u =
    (p.user as
      | {
          unique_id?: string;
          nickname?: string;
          avatar_url?: string;
          identity?: IdentityBlock;
        }
      | undefined) || {};
  const userClickable = onSelectUser != null && (u.unique_id || event.user_id);
  const display = u.nickname || u.unique_id || '—';
  const seed = (display[0] || '?').toUpperCase();

  // Identity-driven row tint. Subscribers / mods / top gifters get
  // a faint left-border accent so VIPs are scannable at a glance.
  // Accent colors don't auto-invert, so we add explicit dark
  // variants per CLAUDE.md.
  const id = u.identity;
  const tint =
    id?.is_top_gifter
      ? 'border-l-2 border-l-amber-400 bg-amber-50/40 dark:bg-amber-500/[0.06]'
      : id?.is_subscribe
        ? 'border-l-2 border-l-rose-400 bg-rose-50/30 dark:bg-rose-500/[0.06]'
        : id?.is_moderator
          ? 'border-l-2 border-l-sky-400 bg-sky-50/30 dark:bg-sky-500/[0.06]'
          : 'border-l-2 border-l-transparent';

  return (
    <div
      className={
        `group relative flex items-start gap-2 sm:gap-3 py-1.5 pl-1 ${tint} ` +
        (userClickable ? 'cursor-pointer hover:bg-gray-50 rounded-r' : '')
      }
      onClick={
        userClickable
          ? () =>
              onSelectUser?.({
                userId: event.user_id,
                uniqueId: u.unique_id ?? null,
                nickname: u.nickname ?? null,
                tab: 'comments',
              })
          : undefined
      }
    >
      {/* Time column — full HH:MM:SS on sm+, compact HH:MM on
          mobile to save 4.5rem of horizontal space. */}
      <div
        className="hidden sm:block font-mono text-[11px] text-gray-600 shrink-0 text-right tabular-nums pt-1"
        style={{ width: '4.5rem' }}
      >
        {formatTime(event.ts, tz)}
      </div>

      {/* Avatar replaces the colored dot — identity is the timeline
          marker. Falls back to an initials chip when avatar URL
          is missing (older events from before to_user capture). */}
      <div className="relative shrink-0">
        <SafeAvatar
          src={u.avatar_url}
          size={28}
          className="ring-2 ring-white dark:ring-gray-900"
          fallback={
            <span className="font-mono text-[11px] text-gray-500">{seed}</span>
          }
        />
        {/* Type pip on the bottom-right of the avatar. Tiny 10px
            color dot — the type is also reflected by the body
            tag, so this is just a quick visual axis. */}
        <span
          className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full ring-2 ring-white dark:ring-gray-900"
          style={{ backgroundColor: color }}
          aria-hidden
        />
      </div>

      <div className="min-w-0 flex-1">
        {(u.nickname || u.unique_id) && (
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <span className="font-medium text-sm text-gray-900 truncate max-w-[12rem]">
              {display}
            </span>
            {u.unique_id && u.nickname && (
              <span className="text-[10px] font-mono text-gray-600 truncate max-w-[10rem]">
                @{u.unique_id}
              </span>
            )}
            <TikTokUserBadges identity={u.identity} />
            {/* Inline mobile-only time — replaces the 4.5rem column. */}
            <span className="sm:hidden ml-auto text-[10px] font-mono text-gray-500 tabular-nums">
              {formatTimeShort(event.ts, tz)}
            </span>
          </div>
        )}
        <EventBody
          type={type}
          payload={p}
          searchQuery={searchQuery}
        />
      </div>
    </div>
  );
}

function EventBody({
  type,
  payload,
  searchQuery,
}: {
  type: string;
  payload: Record<string, unknown>;
  searchQuery: string;
}) {
  switch (type) {
    case 'comment': {
      const text = String(payload.text ?? payload.content ?? '');
      return (
        <div className="text-sm break-words text-gray-700 whitespace-pre-wrap">
          {text
            ? highlight(text, searchQuery)
            : <span className="text-gray-400 italic">(empty)</span>}
        </div>
      );
    }
    case 'caption': {
      // Captions have two shapes:
      //   • New (post-fix): payload.translations = [{lang, text}, …]
      //   • Old (legacy):   payload.content = stringified Python repr
      //     e.g. "[CaptionContent(lang='es', content='hi there')]"
      // The legacy shape was produced by `str(content)` on a list of
      // CaptionContent objects. Regex-parse it best-effort. If both
      // shapes are absent, fall back to `payload.text` (very old).
      type Tx = { lang: string | null; text: string };
      let translations: Tx[] = [];
      const raw = payload.translations as unknown;
      if (Array.isArray(raw)) {
        translations = raw
          .map((tx: unknown): Tx | null => {
            if (typeof tx !== 'object' || tx == null) return null;
            const t = tx as { lang?: unknown; text?: unknown };
            const text = typeof t.text === 'string' ? t.text : '';
            if (!text) return null;
            return {
              lang: typeof t.lang === 'string' ? t.lang : null,
              text,
            };
          })
          .filter((t): t is Tx => t !== null);
      }
      if (translations.length === 0) {
        const legacy = String(payload.content ?? payload.text ?? '');
        if (legacy) {
          // /content='([^']*)'/g — handles repeated CaptionContent
          // entries in a single repr-list. Each match is a translation.
          const re = /lang=(?:'([^']*)'|None|None)[^,]*,\s*content='((?:[^'\\]|\\.)*)'/g;
          let m: RegExpExecArray | null;
          while ((m = re.exec(legacy)) !== null) {
            translations.push({
              lang: m[1] || null,
              text: m[2].replace(/\\'/g, "'"),
            });
          }
          // No matches? At least show the raw string so the operator
          // sees something rather than a silent empty row.
          if (translations.length === 0) {
            translations.push({ lang: null, text: legacy });
          }
        }
      }
      if (translations.length === 0) {
        return <span className="text-gray-400 italic text-sm">(empty)</span>;
      }
      return (
        <div className="text-sm break-words text-gray-700 whitespace-pre-wrap space-y-0.5">
          {translations.map((tx, i) => (
            <div key={i}>
              {tx.lang && (
                <span className="inline-block text-[9px] font-mono uppercase tracking-wider text-gray-500 mr-1.5 align-middle">
                  {tx.lang}
                </span>
              )}
              {highlight(tx.text, searchQuery)}
            </div>
          ))}
        </div>
      );
    }
    case 'gift': {
      const name = String(payload.gift_name ?? `gift #${payload.gift_id ?? '?'}`);
      const repeat = Number(payload.repeat_count ?? 1);
      const diamonds = Number(payload.diamond_count ?? 0);
      const total = diamonds * repeat;
      const to = payload.to_user as
        | { unique_id?: string; nickname?: string }
        | undefined;
      const recipient = to && (to.nickname || to.unique_id);
      return (
        <div className="text-sm break-words text-gray-700">
          sent <span className="font-medium">{name}</span>
          {repeat > 1 && <span className="font-mono text-[11px]"> ×{repeat}</span>}
          {total > 0 && (
            <span className="ml-1.5 font-mono text-[11px] text-amber-700">
              ({total.toLocaleString()} 💎)
            </span>
          )}
          {recipient && (
            <span className="ml-1.5 text-[11px] text-gray-500">
              → <span className="font-mono">{to.nickname || `@${to.unique_id}`}</span>
            </span>
          )}
        </div>
      );
    }
    case 'subscribe': {
      const months = Number(payload.sub_month ?? 0);
      const tier = String(payload.subscribe_type ?? '') || null;
      return (
        <div className="text-sm break-words text-gray-700">
          subscribed
          {months > 0 && (
            <span className="font-mono text-[11px] ml-1">· {months}mo</span>
          )}
          {tier && <span className="font-mono text-[11px] ml-1 text-rose-700">{tier}</span>}
        </div>
      );
    }
    case 'donation': {
      const total = Number(payload.total ?? 0);
      const currency = String(payload.currency ?? 'USD');
      return (
        <div className="text-sm break-words text-gray-700">
          donated{' '}
          <span className="font-mono font-medium">
            {total.toLocaleString()} {currency}
          </span>
        </div>
      );
    }
    case 'envelope': {
      const diamonds = Number(payload.diamond_count ?? 0);
      return (
        <div className="text-sm break-words text-gray-700">
          dropped envelope
          {diamonds > 0 && (
            <span className="font-mono text-[11px] ml-1 text-amber-700">
              ({diamonds.toLocaleString()} 💎)
            </span>
          )}
        </div>
      );
    }
    case 'emote': {
      const list = (payload.emotes as Array<{ image_url?: string; emote_id?: string }>) || [];
      if (list.length === 0) return <div className="text-sm text-gray-500 italic">(emoji)</div>;
      return (
        <div className="flex items-center gap-1 mt-0.5">
          {list.slice(0, 6).map((e, i) =>
            e.image_url ? (
              <img
                key={i}
                src={e.image_url}
                alt=""
                className="w-5 h-5"
                referrerPolicy="no-referrer"
                loading="lazy"
              />
            ) : (
              <span key={i} className="text-[10px] font-mono text-gray-500">
                {e.emote_id}
              </span>
            ),
          )}
        </div>
      );
    }
    case 'poll': {
      const title = String(payload.title ?? '') || `Poll #${payload.poll_id ?? '?'}`;
      const options = Number(payload.options_count ?? 0);
      return (
        <div className="text-sm break-words text-gray-700">
          poll: <span className="font-medium">{title}</span>
          {options > 0 && (
            <span className="font-mono text-[11px] ml-1">· {options} options</span>
          )}
        </div>
      );
    }
    case 'question': {
      const text = String(payload.text ?? '') || '(empty)';
      return (
        <div className="text-sm break-words text-gray-700">
          asked: <span className="italic">{text}</span>
        </div>
      );
    }
    case 'rank_update': {
      // RankUpdate carries no actionable info beyond "leaderboard
      // refreshed". Show a quiet pulse marker so the row isn't blank
      // when an operator browses this type explicitly.
      const tab = String(payload.tab_label ?? payload.tab_type ?? '') || 'leaderboard';
      return (
        <div className="text-sm text-gray-500">
          {tab} refreshed
        </div>
      );
    }
    case 'rank_text': {
      // Two payload shapes:
      //   • New: payload.self_msg / other_msg = { pattern, pieces[] }
      //     where each piece is { type:'user'|'string', … }. Splice
      //     the pattern with the substitutions.
      //   • Legacy: same fields are stringified Python repr blobs.
      //     Best-effort regex extracts the user nickname + the rank
      //     number; otherwise show before→after only.
      const before = payload.owner_idx_before;
      const after = payload.owner_idx_after;
      type Piece =
        | { type: 'string'; value: string }
        | { type: 'user'; user_id?: number | null; nickname?: string | null; username?: string | null; avatar_url?: string | null };
      type Msg = { pattern?: string | null; pieces?: Piece[] };

      const pickMsg = (): Msg | null => {
        // Prefer `other_msg` (third-person — the message the rest of
        // the room sees); `self_msg` is the first-person variant.
        const candidates = [payload.other_msg, payload.self_msg];
        for (const m of candidates) {
          if (m && typeof m === 'object' && !Array.isArray(m)) {
            const cast = m as Msg;
            if (cast.pattern || (cast.pieces && cast.pieces.length > 0)) return cast;
          }
        }
        return null;
      };

      const renderPattern = (msg: Msg) => {
        const pat = msg.pattern || '';
        const pieces = msg.pieces || [];
        // Discriminate the placeholder type from the *pattern* token
        // (`{0:user}` vs `{0:string}`), not from the piece's recorded
        // `type`. A backend bug shipped a window of rank_text events
        // where every TextPiece was tagged `type: 'user'` (even the
        // rank-number string pieces), so trusting `piece.type` for
        // those rows would print "@user" where a number belongs.
        // Pattern-driven dispatch + a `user_id` truthiness check on
        // the piece data is the durable rendering rule.
        const renderPiece = (
          piece: Piece | undefined,
          slotKind: string,
        ): React.ReactNode => {
          if (!piece) return null;
          if (slotKind === 'user') {
            const id = (piece as { user_id?: number | null }).user_id ?? 0;
            const nick = (piece as { nickname?: string | null }).nickname;
            const uname = (piece as { username?: string | null }).username;
            // Skip placeholder users (uid=0 + no display fields). Don't
            // render "@user" for them — the data is broken; better to
            // collapse to a quiet ellipsis than to claim a viewer who
            // doesn't exist.
            if (!id && !nick && !uname) {
              return <span className="font-mono text-gray-400">…</span>;
            }
            return <span className="font-medium">{nick || uname || '@user'}</span>;
          }
          // string slot — pull value off whichever shape we got.
          const value =
            (piece as { value?: string }).value
              ?? (piece as { nickname?: string }).nickname  // legacy
              ?? '?';
          return <span className="font-mono">{value}</span>;
        };
        if (!pat) {
          // No pattern → join pieces, dispatching off the piece's own
          // type since there's no slot info to lean on.
          return pieces.map((p, i) =>
            p.type === 'user'
              ? renderPiece(p, 'user')
              : renderPiece(p, 'string'),
          );
        }
        const parts: React.ReactNode[] = [];
        const re = /\{(\d+):([a-z]+)\}/gi;
        let lastIdx = 0;
        let m: RegExpExecArray | null;
        let key = 0;
        while ((m = re.exec(pat)) !== null) {
          if (m.index > lastIdx) parts.push(pat.slice(lastIdx, m.index));
          const idx = Number(m[1]);
          const slotKind = (m[2] || '').toLowerCase();
          const piece = pieces[idx];
          const rendered = renderPiece(piece, slotKind);
          if (rendered != null) {
            parts.push(
              <span key={key++}>{rendered}</span>,
            );
          }
          lastIdx = m.index + m[0].length;
        }
        if (lastIdx < pat.length) parts.push(pat.slice(lastIdx));
        return parts;
      };

      const msg = pickMsg();
      if (msg) {
        return (
          <div className="text-sm break-words text-gray-700">
            {renderPattern(msg)}
            {before != null && after != null && Number(before) !== Number(after) && (
              <span className="ml-1.5 font-mono text-[11px] text-gray-500">
                #{String(before)} → #{String(after)}
              </span>
            )}
          </div>
        );
      }
      // Legacy fallback — try to pull `nick_name='…'` and the trailing
      // string_value out of the repr.
      const legacy = String(payload.other_msg ?? payload.self_msg ?? '');
      let nickname: string | null = null;
      const nm = /nick_name='([^']*)'/.exec(legacy);
      if (nm) nickname = nm[1];
      const rm = /string_value='(\d+)'/g;
      let rankAfter: string | null = null;
      let mm: RegExpExecArray | null;
      while ((mm = rm.exec(legacy)) !== null) rankAfter = mm[1];
      return (
        <div className="text-sm break-words text-gray-700">
          {nickname ? (
            <>
              <span className="font-medium">{nickname}</span>
              {' '}became No.{' '}
              <span className="font-mono">{rankAfter ?? '?'}</span>
              {' '}viewer
            </>
          ) : (
            <span className="text-gray-500">rank changed</span>
          )}
          {before != null && after != null && Number(before) !== Number(after) && (
            <span className="ml-1.5 font-mono text-[11px] text-gray-500">
              #{String(before)} → #{String(after)}
            </span>
          )}
        </div>
      );
    }
    case 'live_pause':
      return (
        <div className="text-sm text-gray-700 inline-flex items-center gap-1">
          <Pause className="w-3 h-3" /> Stream paused
        </div>
      );
    case 'live_unpause':
      return (
        <div className="text-sm text-gray-700 inline-flex items-center gap-1">
          <Play className="w-3 h-3" /> Stream resumed
        </div>
      );
    default:
      return (
        <div className="text-sm text-gray-500 font-mono text-[11px] truncate">
          {JSON.stringify(payload).slice(0, 200)}
        </div>
      );
  }
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

function formatTime(iso: string, tz: string): string {
  if (!iso) return '—';
  const p = partsInZone(iso, tz);
  return `${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

/** Compact time for the inline mobile-only timestamp — drops the
 *  seconds since the row already shows the row order chronologically. */
function formatTimeShort(iso: string, tz: string): string {
  if (!iso) return '—';
  const p = partsInZone(iso, tz);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

/** Highlight occurrences of `query` inside `text` with `<mark>`.
 *  Case-insensitive, returns ReactNode array suitable for
 *  rendering inside a `<span>` / `<div>`. Returns the original
 *  string when query is empty. */
function highlight(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const q = query.trim();
  if (!q) return text;
  const lower = text.toLowerCase();
  const needle = q.toLowerCase();
  const out: React.ReactNode[] = [];
  let i = 0;
  let last = 0;
  while ((i = lower.indexOf(needle, last)) !== -1) {
    if (i > last) out.push(text.slice(last, i));
    out.push(
      <mark
        key={`m-${i}`}
        className="bg-amber-100 text-amber-900 px-0.5 rounded-sm dark:bg-amber-500/30 dark:text-amber-100"
      >
        {text.slice(i, i + needle.length)}
      </mark>,
    );
    last = i + needle.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

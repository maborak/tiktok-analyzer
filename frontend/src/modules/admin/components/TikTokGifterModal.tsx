import { useEffect, useMemo, useState } from 'react';
import { Link } from '@tanstack/react-router';
import toast from 'react-hot-toast';
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Gift as GiftIcon,
  Gem,
  Loader2,
  MessageSquare,
  Network,
  Radio,
  Search,
  Star,
  Swords,
  Users,
  X,
} from 'lucide-react';

import { TikTokDailyHeatmap30 } from '@admin/components/TikTokDailyHeatmap30';

import { Input } from '@/components/ui/Input';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { TikTokAddLiveModal } from '@admin/components/TikTokAddLiveModal';
import {
  type TikTokCommonGifterDetail,
  type TikTokEvent,
  type TikTokUserMatchEntry,
} from '@admin/services/tiktok';
import { useTikTokApi } from '@admin/contexts/TikTokApiContext';
import {
  useTikTokTimezone,
  fmtMonthDayTime,
  partsInZone,
} from '@admin/contexts/TikTokTimezoneContext';

interface GifterModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Gifter context — used for filtering and the modal header.
   *
   *  Counters are optional: callers that already have a row's diamond/
   *  gift totals (the leaderboard chip path) should pass them through
   *  so the header + tab badges show real numbers immediately. Callers
   *  that DON'T have those numbers (the comments-timeline path —
   *  clicking a commenter only knows their identity, not their
   *  lifetime counters) should leave them undefined. The badge then
   *  renders `(·)` instead of a misleading `(0)`, and the per-tab
   *  search query's own `total` populates pagination as normal. */
  userId: string | null;
  uniqueId: string | null;
  nickname: string | null;
  diamondsTotal?: number;
  giftsCount?: number;
  commentsCount?: number;
  /** When set, scope all queries to this room only. Otherwise show
   *  the user's history across every monitored room. */
  roomId?: string | null;
  /** Day-aggregate / multi-room context: every other room id that's
   *  in scope alongside `roomId`. Both the gifters table and this
   *  modal need to see the full set so a viewer who only gifted in
   *  the OTHER rooms of a multi-broadcast day still surfaces here.
   *  Used when scope='room' (the default for in-room views). */
  extraRoomIds?: string[];
  /** Auto-select the Comments tab on open (used when the user clicked
   *  the comments chip rather than the gifter row). */
  defaultTab?: 'gifts' | 'timeline' | 'comments' | 'relationships' | 'matches';
  /** The handle whose page the modal is being viewed from. Used by the
   *  Relationships tab to mark "this host" in the per-host list and
   *  to suppress the redundant link back to the same page. Optional —
   *  falls through harmlessly if the parent doesn't pass it. */
  currentHandle?: string;
  /** When provided, an extra scope chip ("windowLabel") is shown that
   *  bounds searchEvents to [windowSince, windowUntil). Used when the
   *  modal is opened from a past-match modal so the gift / comment
   *  history reflects ONLY that battle window, not the user's whole
   *  history in this room. */
  windowSince?: string | null;
  windowUntil?: string | null;
  windowLabel?: string;
  /** Override for the `scope='room'` button label. The modal's default
   *  ("This broadcast") is misleading when `extraRoomIds` carries a
   *  full host-wide room set (all-time view) or a day-aggregate set —
   *  parents pass a more accurate phrase here, e.g. "All time (50
   *  broadcasts)" or "Day · 3 broadcasts". The same string also drives
   *  the contextual header banner so the operator immediately sees
   *  which dataset the modal is rendering. */
  roomSetLabel?: string;
  /** Set to `true` when the modal is opened from a public / read-only
   *  context (e.g. the unauthenticated public lives page). Suppresses
   *  every admin-write affordance — the favourite button, the "Add to
   *  monitor" pill, and the underlying favourite-state + listLives
   *  prefetches — so anonymous viewers don't see broken actions or
   *  trigger 401 toasts. Data tabs (Gifts/Comments/Relationships/
   *  Matches) and scope chips remain functional; the Close button
   *  stays in the footer. Default `false` (admin context). */
  readOnly?: boolean;
  /** When `true`, render WITHOUT the outer `<Modal>` chrome, the
   *  identity-row header (avatar / nickname / stats), the footer
   *  action buttons (Favorites / Add-to-monitor / Close), AND the
   *  Add-Live confirmation modal. Used by the unified
   *  `TikTokGifterDetailModal` which provides its own shared header
   *  + close affordance + tabs at the shell level. Parent is
   *  responsible for only mounting this component when its tab is
   *  active; `isOpen` is ignored in embedded mode (effects always
   *  fire as if open).
   *
   *  Defaults to false → backwards-compatible with every existing
   *  call site. */
  embedded?: boolean;
}

interface GiftRow {
  ts: string;
  giftName: string;
  repeat: number;
  perGiftDiamonds: number;
  totalDiamonds: number;
  roomId: string;
  eventId: string;
  /** Recipient nickname / @handle if TikTok identified one (multi-guest
   *  lives, PK battles). null in solo lives where to_user equals the host. */
  recipientLabel: string | null;
}

const PAGE_SIZES = [25, 50, 100, 250] as const;

export function TikTokGifterModal({
  isOpen,
  onClose,
  userId,
  uniqueId,
  nickname,
  diamondsTotal,
  giftsCount,
  commentsCount,
  roomId,
  defaultTab = 'gifts',
  windowSince,
  windowUntil,
  windowLabel,
  currentHandle,
  extraRoomIds,
  roomSetLabel,
  readOnly = false,
  embedded = false,
}: GifterModalProps) {
  const tiktokApi = useTikTokApi();
  const { tz } = useTikTokTimezone();
  // In embedded mode the parent (the unified TikTokGifterDetailModal)
  // only mounts us when its tab is active — so we should always
  // treat the modal as "open" for the data-fetching effects below.
  // We use a derived alias instead of mutating the prop so React's
  // exhaustive-deps lint stays satisfied with a single named value.
  const isOpenEff = embedded || isOpen;
  // Stable string key for the extras — array identity flips every
  // render. Used in dep arrays without re-running on no-op changes.
  const extraKey = (extraRoomIds ?? []).join(',');
  const [tab, setTab] = useState<
    'gifts' | 'timeline' | 'comments' | 'relationships' | 'matches'
  >(defaultTab);
  // Per-day diamond / gift totals for the (user, currentHandle) pair
  // over the last 30 days. Drives the Timeline tab's heatmap. Lazy-
  // fetched the first time the user lands on the Timeline tab and
  // re-fetched when userId/handle changes.
  const [dailySeries, setDailySeries] = useState<
    Array<{ day: string; diamonds: number; gifts: number }> | null
  >(null);
  const [dailySeriesLoading, setDailySeriesLoading] = useState(false);
  const [dailySeriesError, setDailySeriesError] = useState<string | null>(null);
  // Cross-host activity for the Relationships tab. Lazy-fetched the
  // first time the user lands on the tab; cached for the lifetime of
  // the open modal so flipping back-and-forth doesn't re-hit the
  // backend.
  const [relationships, setRelationships] = useState<TikTokCommonGifterDetail | null>(null);
  const [relationshipsLoading, setRelationshipsLoading] = useState(false);
  const [relationshipsError, setRelationshipsError] = useState<string | null>(null);
  // Favourite toggle — same UX as the Common Gifter detail modal.
  // Lazy-loaded on open so the button reflects current truth.
  const [isFavorite, setIsFavorite] = useState<boolean | null>(null);
  const [favoriteBusy, setFavoriteBusy] = useState(false);
  // Matches the user contributed to within the active scope. Lazy-
  // fetched on first land on the Matches tab; refetched when scope
  // changes (different room set or time window). Each entry pairs the
  // match identity with this user's per-match contribution so we can
  // render "battle vs @opp · 1.2k💎 from you" cleanly.
  const [matchesData, setMatchesData] = useState<{
    items: TikTokUserMatchEntry[];
    total: number;
  } | null>(null);
  const [matchesLoading, setMatchesLoading] = useState(false);
  const [matchesError, setMatchesError] = useState<string | null>(null);
  const [matchesPage, setMatchesPage] = useState(0);
  const MATCHES_PAGE_SIZE = 20;
  // Monitoring affordance — same UX as the Match Events modal's
  // opponent cells: footer flips between "+ Add to monitor" and
  // "✓ Monitoring" based on whether this gifter's @handle is already
  // in `tiktok_subscriptions`. Confirmation goes through the canonical
  // TikTokAddLiveModal so the operator sees identical preview data
  // (avatar, follower count, live state, bio, dupe-warning banner).
  const [isMonitored, setIsMonitored] = useState<boolean>(false);
  const [addMonitorOpen, setAddMonitorOpen] = useState<boolean>(false);
  const hasWindow = Boolean(windowSince && windowUntil);
  // Scope: 'window' (bounded by [windowSince, windowUntil)) or 'room'.
  // The previous 'all' (cross-host) option was removed — cross-host
  // exploration lives under the Profile tab of the unified shell now,
  // and surfacing it inside the in-room Current view was confusing
  // ("this broadcast" + "cross-host" implies a third axis the data
  // doesn't actually have).
  type Scope = 'window' | 'room';
  const [scope, setScope] = useState<Scope>(hasWindow ? 'window' : 'room');

  const [giftEvents, setGiftEvents] = useState<TikTokEvent[]>([]);
  const [commentEvents, setCommentEvents] = useState<TikTokEvent[]>([]);
  const [loading, setLoading] = useState(false);

  // ── Pagination + filters (per-tab) ─────────────────────────────
  // Lifted into the modal so reopening the modal under a new user
  // resets cleanly and so the toolbar can render alongside the
  // tab-specific view body.
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(50);
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [minDiamonds, setMinDiamonds] = useState<number | ''>('');
  // Total count from the count endpoint — drives the pagination UI
  // and the "X of Y matching" counter. null while a filter combo's
  // count is in flight.
  const [total, setTotal] = useState<number | null>(null);

  // Debounce free-text → 200ms.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);

  // Reset on open / user change.
  useEffect(() => {
    if (!isOpenEff) return;
    setTab(defaultTab);
    setScope(hasWindow ? 'window' : 'room');
    setPage(0);
    setQ('');
    setDebouncedQ('');
    setMinDiamonds('');
    setTotal(null);
    setRelationships(null);
    setRelationshipsError(null);
    setIsFavorite(null);
    setMatchesData(null);
    setMatchesError(null);
    setMatchesPage(0);
    setDailySeries(null);
    setDailySeriesError(null);
  }, [isOpenEff, userId, roomId, defaultTab, hasWindow]);

  // Lazy-fetch the per-(user, currentHandle) daily series the first
  // time the Timeline tab is activated. Cached for the lifetime of
  // the open modal — flipping back and forth doesn't re-hit the
  // backend. Skipped when there's no currentHandle in the click
  // payload (e.g. opening from a search index where the host is
  // ambiguous); Timeline still renders, just with an empty-state.
  useEffect(() => {
    if (!isOpenEff || !userId || tab !== 'timeline') return;
    if (dailySeries !== null || dailySeriesLoading) return;
    if (!currentHandle) {
      setDailySeries([]);
      return;
    }
    let cancelled = false;
    setDailySeriesLoading(true);
    setDailySeriesError(null);
    tiktokApi
      .getUserHostDailySeries({ userId, handle: currentHandle, days: 30 })
      .then((rows) => {
        if (cancelled) return;
        setDailySeries(rows);
      })
      .catch((e) => {
        if (cancelled) return;
        setDailySeriesError((e as Error).message || 'Failed to load timeline');
      })
      .finally(() => {
        if (!cancelled) setDailySeriesLoading(false);
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpenEff, userId, currentHandle, tab]);

  // Force matches refetch when scope or paging changes.
  useEffect(() => {
    setMatchesData(null);
    setMatchesPage(0);
  }, [scope, extraKey, windowSince, windowUntil]);

  // Eager-load matches when the modal opens (not just on tab click)
  // so the tab badge shows the count immediately and clicking the tab
  // is instant. The single request pulls the first page; pagination
  // refetches the next page when needed. Cancel flag guards stale
  // resolves on rapid scope changes.
  useEffect(() => {
    if (!isOpenEff || !userId) return;
    let cancelled = false;
    setMatchesLoading(true);
    setMatchesError(null);
    // Build the room-set + time window from the same scope semantics
    // the gifts/comments queries use, so the Matches tab respects the
    // operator's scope chip selection.
    const roomIds: string[] | undefined = roomId
      ? Array.from(new Set([roomId, ...(extraRoomIds ?? [])]))
      : (extraRoomIds && extraRoomIds.length > 0
          ? Array.from(new Set(extraRoomIds))
          : undefined);
    const since = scope === 'window' ? (windowSince ?? undefined) : undefined;
    const until = scope === 'window' ? (windowUntil ?? undefined) : undefined;
    tiktokApi
      .listUserMatches({
        userId,
        roomIds,
        since,
        until,
        limit: MATCHES_PAGE_SIZE,
        offset: matchesPage * MATCHES_PAGE_SIZE,
      })
      .then((res) => {
        if (cancelled) return;
        setMatchesData(res);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setMatchesError(e.message || 'Failed to load matches');
      })
      .finally(() => {
        if (!cancelled) setMatchesLoading(false);
      });
    return () => { cancelled = true; };
  }, [isOpenEff, userId, scope, extraKey, roomId, windowSince, windowUntil, matchesPage]);

  // Reset to page 1 + force a count refetch whenever the active
  // filter set changes.
  useEffect(() => {
    setPage(0);
    setTotal(null);
  }, [tab, scope, debouncedQ, minDiamonds, pageSize]);

  // Pull the current favourite state once the modal opens — drives
  // the star + label on the footer button. Skipped entirely in
  // read-only mode (public viewers can't favourite, and the API call
  // requires admin auth — would 401-toast for anonymous visitors).
  useEffect(() => {
    if (readOnly) {
      setIsFavorite(null);
      return;
    }
    if (!isOpenEff || !userId) {
      setIsFavorite(null);
      return;
    }
    let cancelled = false;
    tiktokApi
      .isFavoriteGifter(userId)
      .then((r) => { if (!cancelled) setIsFavorite(r.is_favorite); })
      .catch(() => { if (!cancelled) setIsFavorite(false); });
    return () => { cancelled = true; };
  }, [isOpenEff, userId, readOnly]);

  // Monitoring check — same pattern as match modal. Read from
  // listLives so a recently-added handle reflects without a hard
  // refresh. Resets to false when modal closes or user changes.
  // Skipped in read-only mode — the monitor pill is hidden anyway,
  // and listLives requires admin auth (would 401 for public viewers).
  useEffect(() => {
    if (readOnly) {
      setIsMonitored(false);
      return;
    }
    if (!isOpenEff || !uniqueId) {
      setIsMonitored(false);
      return;
    }
    let cancelled = false;
    tiktokApi
      .listLives()
      .then((rows) => {
        if (cancelled) return;
        const handle = uniqueId.toLowerCase();
        setIsMonitored(rows.some((r) => r.unique_id?.toLowerCase() === handle));
      })
      .catch(() => {
        // Silent — defaults to false; the backend's createLive guards
        // against dupes anyway so a stale "not monitored" is harmless.
      });
    return () => { cancelled = true; };
  }, [isOpenEff, uniqueId, readOnly]);

  const confirmAddMonitor = async () => {
    if (!uniqueId) return;
    try {
      await tiktokApi.createLive(uniqueId, true);
      setIsMonitored(true);
      toast.success(`Now monitoring @${uniqueId}`);
      setAddMonitorOpen(false);
    } catch (e) {
      toast.error(
        (e as Error).message || `Failed to add @${uniqueId} to monitor`,
      );
      throw e; // surface to TikTokAddLiveModal so it stays open
    }
  };

  const onToggleFavorite = async () => {
    if (!userId || favoriteBusy) return;
    setFavoriteBusy(true);
    try {
      if (isFavorite) {
        await tiktokApi.removeFavoriteGifter(userId);
        setIsFavorite(false);
        toast.success('Removed from favourites');
      } else {
        await tiktokApi.addFavoriteGifter(userId);
        setIsFavorite(true);
        toast.success('Added to favourites — alerts will fire when they gift');
      }
      // Cross-component invalidation: the page-level toast filter and
      // the Favourites tab listen for this and refresh in place.
      window.dispatchEvent(new CustomEvent('tiktok:favorites-changed'));
    } catch (e) {
      toast.error((e as Error).message || 'Favourite toggle failed');
    } finally {
      setFavoriteBusy(false);
    }
  };

  // Prefetch the cross-host breakdown the moment the modal opens —
  // even if the user starts on the Gifts or Comments tab. Without
  // this the Relationships tab badge `(N hosts)` is empty until the
  // user clicks into the tab, which made it look static. Cheap query
  // (one round-trip; backend reads from the summary table), and the
  // data is reused if/when the user does switch tabs.
  //
  // Skipped in read-only mode: `getCommonGifterDetail` is an
  // admin-only endpoint (not mirrored on the public namespace), so
  // the call would 404 and toast an error. The Relationships tab
  // remains visible but renders its empty/error state — the more
  // visceral Gifts / Comments / Matches tabs cover the public viewer's
  // actual use case.
  useEffect(() => {
    if (!isOpenEff || !userId) return;
    if (relationships !== null) return;
    if (readOnly) return;
    let cancelled = false;
    setRelationshipsLoading(true);
    setRelationshipsError(null);
    tiktokApi
      .getCommonGifterDetail(userId)
      .then((d) => {
        if (cancelled) return;
        setRelationships(d);
      })
      .catch((e) => {
        if (cancelled) return;
        setRelationshipsError((e as Error).message || 'Failed to load relationships');
      })
      .finally(() => {
        if (!cancelled) setRelationshipsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpenEff, userId, relationships, readOnly]);

  // Fetch the active tab's page of events whenever scope / tab /
  // user / filters / page change.
  useEffect(() => {
    if (!isOpenEff || !userId) return;
    let cancelled = false;
    const type = tab === 'gifts' ? 'gift' : 'comment';
    setLoading(true);
    const roomsInScope = roomId
      ? Array.from(new Set([roomId, ...(extraRoomIds ?? [])]))
      : undefined;
    const md =
      tab === 'gifts' && minDiamonds !== '' && Number(minDiamonds) > 0
        ? Number(minDiamonds)
        : undefined;
    const trimmed = debouncedQ || undefined;
    const baseParams = {
      user_id: userId,
      type,
      room_id: roomsInScope && roomsInScope.length === 1 ? roomsInScope[0] : undefined,
      room_ids: roomsInScope && roomsInScope.length > 1 ? roomsInScope : undefined,
      since: scope === 'window' ? windowSince ?? undefined : undefined,
      until: scope === 'window' ? windowUntil ?? undefined : undefined,
      q: trimmed,
      min_diamonds: md,
    } as const;
    Promise.all([
      tiktokApi.searchEvents({
        ...baseParams,
        limit: pageSize,
        offset: page * pageSize,
      }),
      // Only refetch the count when we don't already have one for
      // this filter combo. The reset useEffect nulls `total` whenever
      // any filter input changes.
      total === null
        ? tiktokApi.countEvents(baseParams)
        : Promise.resolve({ total }),
    ])
      .then(([rows, c]) => {
        if (cancelled) return;
        if (tab === 'gifts') setGiftEvents(rows);
        else setCommentEvents(rows);
        setTotal(c.total ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        if (tab === 'gifts') setGiftEvents([]);
        else setCommentEvents([]);
        setTotal(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    isOpenEff, userId, scope, roomId, extraKey, tab,
    windowSince, windowUntil, debouncedQ, minDiamonds, pageSize, page,
  ]);

  // ── derived ───────────────────────────────────────────────────────

  const { giftRows, byGift } = useMemo(() => {
    const giftRows: GiftRow[] = giftEvents.map((e) => {
      const p = (e.payload || {}) as Record<string, unknown>;
      const repeat = Number(p.repeat_count ?? 1) || 1;
      const perGift = Number(p.diamond_count ?? 0) || 0;
      // TikTokLive emits `to_user` for every gift but uses an empty
      // placeholder (user_id=0, nickname="", unique_id="") in solo
      // broadcasts — that placeholder logically means "the host". When
      // a gifter targets a specific anchor in a multi-guest live or PK,
      // the fields are populated with the recipient's real identity.
      // Pre-capture rows simply lack the `to_user` key entirely.
      const hasToUser = Object.prototype.hasOwnProperty.call(p, 'to_user');
      const to = p.to_user as
        | { user_id?: number | string; unique_id?: string; nickname?: string }
        | undefined;
      const targeted =
        !!to &&
        !!to.user_id &&
        String(to.user_id) !== '0' &&
        Boolean(to.nickname || to.unique_id);
      const recipientLabel = !hasToUser
        ? null
        : targeted
          ? (to!.nickname || `@${String(to!.unique_id || '').replace(/^@/, '')}`)
          : 'Host';
      return {
        ts: e.ts,
        giftName: String(p.gift_name ?? p.gift_id ?? '?'),
        repeat,
        perGiftDiamonds: perGift,
        totalDiamonds: perGift * repeat,
        roomId: e.room_id,
        eventId: e.id,
        recipientLabel,
      };
    });
    const agg: Record<string, { name: string; count: number; diamonds: number }> = {};
    for (const r of giftRows) {
      const k = r.giftName;
      if (!agg[k]) agg[k] = { name: k, count: 0, diamonds: 0 };
      agg[k].count += r.repeat;
      agg[k].diamonds += r.totalDiamonds;
    }
    const byGift = Object.values(agg).sort((a, b) => b.diamonds - a.diamonds);
    return { giftRows, byGift };
  }, [giftEvents]);

  const visibleDiamonds = giftRows.reduce((acc, r) => acc + r.totalDiamonds, 0);

  // The body content rendered inside the Modal in standalone mode AND
  // returned directly in embedded mode (where the unified
  // TikTokGifterDetailModal provides the surrounding chrome). The
  // identity row inside is gated on `!embedded` so the unified
  // shell's shared header isn't duplicated.
  const bodyContent = (
    <>
      {/* Identity row — only in standalone mode. */}
      {!embedded && (
        <div className="flex items-center justify-between gap-3 mb-4">
          <div>
            <div className="text-base font-bold">{nickname || 'Unknown'}</div>
            {uniqueId && (
              <div className="text-xs font-mono text-gray-500">@{uniqueId}</div>
            )}
            {userId && (
              <div className="text-[10px] font-mono text-gray-400">ID: {userId}</div>
            )}
          </div>
          <div className="flex items-baseline gap-4">
            {typeof diamondsTotal === 'number' && diamondsTotal > 0 && (
              <Stat label="Diamonds" value={diamondsTotal.toLocaleString()} accent="amber" />
            )}
            {typeof giftsCount === 'number' && giftsCount > 0 && (
              <Stat label="Gifts" value={giftsCount.toLocaleString()} />
            )}
            {typeof commentsCount === 'number' && commentsCount > 0 && (
              <Stat label="Comments" value={commentsCount.toLocaleString()} accent="sky" />
            )}
          </div>
        </div>
      )}

      {/* Contextual scope banner — tells the operator at a glance
          WHICH dataset is being summed below. */}
      {roomId && (() => {
        const activeLabel =
          scope === 'window'
            ? (windowLabel ?? 'Selected window')
            : (roomSetLabel ?? 'This broadcast');
        return (
          <div className="mb-3 text-[11px] font-mono text-gray-500 inline-flex items-center gap-1.5">
            <span className="uppercase tracking-wider">Showing:</span>
            <span className="font-medium text-gray-700">{activeLabel}</span>
          </div>
        );
      })()}

      {/* Scope toggle — shown ONLY when there's a window context
          (e.g. a past battle the operator drilled into), giving
          them the choice between "this battle" and "this broadcast".
          With no window, the only remaining scope is the broadcast
          itself, so the toggle becomes a single-segment control —
          redundant — and we hide it entirely. Cross-host scope was
          dropped from this view; cross-host exploration lives on
          the Profile tab of the unified shell. */}
      {roomId && hasWindow && (
        <div className="flex items-center gap-1 mb-3 text-xs overflow-x-auto whitespace-nowrap -mx-4 px-4 sm:mx-0 sm:px-0">
          <ScopeButton
            active={scope === 'window'}
            onClick={() => setScope('window')}
          >
            {windowLabel ?? 'This window'}
          </ScopeButton>
          <ScopeButton active={scope === 'room'} onClick={() => setScope('room')}>
            {roomSetLabel ?? 'This broadcast'}
          </ScopeButton>
        </div>
      )}

      {/* Tabs. Horizontal-scroll on narrow viewports — labels +
          counts add up to ~440px, which overflows on phones and
          would otherwise wrap and break the underline alignment.
          The `-mx-4 px-4 sm:mx-0 sm:px-0` bleed lets the scroll
          chrome extend to the modal edges so trimmed content is
          visibly scrollable, not silently cut. Same pattern as
          the match-events modal's tab bar. */}
      <div
        className="flex items-center gap-1 mb-3 border-b border-gray-200 overflow-x-auto whitespace-nowrap -mx-4 px-4 sm:mx-0 sm:px-0"
        role="tablist"
      >
        <TabButton active={tab === 'gifts'} onClick={() => setTab('gifts')}>
          <GiftIcon className="w-3.5 h-3.5" />
          Gifts
          <span className="ml-1.5 text-[10px] text-gray-500 font-mono">
            ({giftsCount ?? '·'})
          </span>
        </TabButton>
        <TabButton active={tab === 'timeline'} onClick={() => setTab('timeline')}>
          <CalendarDays className="w-3.5 h-3.5" />
          Timeline
        </TabButton>
        <TabButton active={tab === 'comments'} onClick={() => setTab('comments')}>
          <MessageSquare className="w-3.5 h-3.5" />
          Comments
          <span className="ml-1.5 text-[10px] text-gray-500 font-mono">
            ({commentsCount ?? '·'})
          </span>
        </TabButton>
        <TabButton
          active={tab === 'relationships'}
          onClick={() => setTab('relationships')}
        >
          <Network className="w-3.5 h-3.5" />
          Relationships
          {relationships && (
            <span className="ml-1.5 text-[10px] text-gray-500 font-mono">
              ({relationships.totals.host_count})
            </span>
          )}
        </TabButton>
        <TabButton active={tab === 'matches'} onClick={() => setTab('matches')}>
          <Swords className="w-3.5 h-3.5" />
          Matches
          {matchesData && (
            <span className="ml-1.5 text-[10px] text-gray-500 font-mono">
              ({matchesData.total})
            </span>
          )}
        </TabButton>
      </div>

      {/* Toolbar — only on event-list tabs (Gifts/Comments). The
          Timeline / Relationships / Matches tabs use their own
          layouts and don't share the search/min-diamonds filter. */}
      {(tab === 'gifts' || tab === 'comments') && (
        <EventListToolbar
          tab={tab}
          q={q}
          setQ={setQ}
          minDiamonds={minDiamonds}
          setMinDiamonds={setMinDiamonds}
        />
      )}

      {tab === 'gifts' && (
        <GiftsView
          loading={loading}
          rows={giftRows}
          byGift={byGift}
          visibleDiamonds={visibleDiamonds}
          showRoomCol={!roomId}
        />
      )}
      {tab === 'timeline' && (
        <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
          <div className="auth-mono-label flex items-center gap-1.5 mb-3">
            <CalendarDays className="w-3.5 h-3.5 text-amber-500" />
            When do they gift{currentHandle ? ` @${currentHandle}` : ''}?{' '}
            <span className="opacity-70">· last 30 days</span>
          </div>
          {dailySeriesLoading && (
            <div className="text-[11px] font-mono text-gray-500 py-6 text-center">
              <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
              Loading timeline…
            </div>
          )}
          {dailySeriesError && (
            <div className="text-[11px] font-mono text-rose-600 dark:text-rose-300 py-6 text-center">
              {dailySeriesError}
            </div>
          )}
          {!dailySeriesLoading && !dailySeriesError && dailySeries && (
            dailySeries.length > 0 ? (
              <TikTokDailyHeatmap30
                points={dailySeries.map((p) => ({
                  day: p.day,
                  diamonds: p.diamonds,
                }))}
              />
            ) : (
              <div className="text-[11px] font-mono text-gray-500 py-6 text-center">
                No gifting activity in the last 30 days
                {currentHandle ? ` in @${currentHandle}'s broadcasts` : ''}.
              </div>
            )
          )}
        </section>
      )}
      {tab === 'comments' && (
        <CommentsView
          loading={loading}
          events={commentEvents}
          showRoomCol={!roomId}
        />
      )}
      {tab === 'relationships' && (
        <RelationshipsView
          data={relationships}
          loading={relationshipsLoading}
          error={relationshipsError}
          currentHandle={currentHandle}
          tz={tz}
        />
      )}
      {tab === 'matches' && (
        <MatchesView
          data={matchesData}
          loading={matchesLoading}
          error={matchesError}
          page={matchesPage}
          pageSize={MATCHES_PAGE_SIZE}
          onPage={setMatchesPage}
          currentHandle={currentHandle}
          tz={tz}
        />
      )}

      {/* Pagination strip — `X–Y of Z · per page · ‹ N/M ›`. Always
          rendered when there's any data, even if `total <= pageSize`,
          so the per-page selector remains accessible. */}
      {(tab === 'gifts' || tab === 'comments') && total != null && total > 0 && (
        <Pagination
          page={page}
          pageSize={pageSize}
          setPageSize={setPageSize}
          total={total}
          pageItemCount={
            tab === 'gifts' ? giftRows.length : commentEvents.length
          }
          loading={loading}
          onPage={setPage}
        />
      )}
    </>
  );

  // Embedded mode: caller renders the wrapping Modal + close chrome.
  // We return just the body so the unified shell can place it inside
  // its own tab pane.
  if (embedded) return bodyContent;

  return (
    <>
    {/* Add-to-monitor confirmation — reuses the canonical Add Live
        modal so the operator sees identical preview data. Rendered
        as a sibling so it stacks above the gifter modal cleanly.
        Suppressed in read-only mode so it never mounts in public
        contexts where no admin actions exist to trigger it. */}
    {!readOnly && uniqueId && (
      <TikTokAddLiveModal
        isOpen={addMonitorOpen}
        handle={uniqueId}
        onCancel={() => setAddMonitorOpen(false)}
        onConfirm={confirmAddMonitor}
      />
    )}
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={nickname ? `${nickname}` : 'Viewer history'}
      className="max-w-3xl"
      footer={
        <div className="flex items-center justify-between gap-2 w-full">
          <span className="text-xs text-gray-500 font-mono">
            {tab === 'gifts'
              ? `${(total ?? giftRows.length).toLocaleString()} gift event${(total ?? giftRows.length) === 1 ? '' : 's'}`
              : tab === 'comments'
                ? `${(total ?? commentEvents.length).toLocaleString()} comment${(total ?? commentEvents.length) === 1 ? '' : 's'}`
                : ''}
          </span>
          <div className="flex items-center gap-2">
            {!readOnly && (
              <Button
                variant={isFavorite ? 'primary' : 'ghost'}
                onClick={onToggleFavorite}
                disabled={favoriteBusy || !userId}
                title={
                  isFavorite
                    ? 'Remove from favourites — stops live alerts when they gift'
                    : 'Add to favourites — fires a live alert whenever they gift in any tracked broadcast'
                }
              >
                <Star
                  className={`w-4 h-4 mr-1.5 ${isFavorite ? 'fill-current' : ''}`}
                />
                {isFavorite ? 'Favourited' : 'Add to Favourites'}
              </Button>
            )}
            {/* Add-to-monitor — mirrors the affordance on the Match
                Events modal opponent cells. Disabled for anonymous
                gifters (no @handle) and rendered as a confirming
                "Monitoring" pill once the handle is in subscriptions.
                Hidden entirely in read-only / public mode. */}
            {!readOnly && uniqueId && (
              isMonitored ? (
                <Link
                  to="/admin/tiktok/$handle"
                  params={{ handle: uniqueId }}
                  onClick={onClose}
                  className="inline-flex items-center gap-1 px-3 py-2 rounded text-xs font-mono uppercase tracking-wider bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30 hover:bg-emerald-200 dark:hover:bg-emerald-500/25 transition-colors"
                  title="Open this creator's live page"
                >
                  <Radio className="w-3.5 h-3.5" />
                  ✓ Monitoring
                </Link>
              ) : (
                <Button
                  variant="ghost"
                  onClick={() => setAddMonitorOpen(true)}
                  title="Start monitoring this creator's lives"
                >
                  <Radio className="w-4 h-4 mr-1.5" />
                  Add to monitor
                </Button>
              )
            )}
            <Button variant="ghost" onClick={onClose}>Close</Button>
          </div>
        </div>
      }
    >
      {bodyContent}
    </Modal>
    </>
  );
}

// ─── views ─────────────────────────────────────────────────────────

interface GiftsViewProps {
  loading: boolean;
  rows: GiftRow[];
  byGift: Array<{ name: string; count: number; diamonds: number }>;
  visibleDiamonds: number;
  showRoomCol: boolean;
}
function GiftsView({ loading, rows, byGift, visibleDiamonds, showRoomCol }: GiftsViewProps) {
  // GiftsView is defined OUTSIDE TikTokGifterModal (top-level fn), so
  // it doesn't inherit the parent's `tz` closure — read it directly.
  const { tz } = useTikTokTimezone();
  return (
    <>
      {byGift.length > 0 && (
        <div className="mb-4">
          <div className="auth-mono-label mb-1.5 flex items-center gap-1.5">
            <Gem className="w-3.5 h-3.5 text-amber-500" />
            By gift
          </div>
          <div className="flex flex-wrap gap-1.5">
            {byGift.map((g) => (
              <span
                key={g.name}
                className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border border-amber-200 bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/30"
              >
                <span className="font-medium">{g.name}</span>
                <span className="font-mono text-gray-500">×{g.count}</span>
                <span className="font-mono tabular-nums text-amber-700 dark:text-amber-300">
                  {g.diamonds.toLocaleString()}💎
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {loading && (
        <div className="py-8 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
          Loading gift history…
        </div>
      )}
      {!loading && rows.length === 0 && (
        <div className="py-8 text-center text-sm text-gray-500">
          <GiftIcon className="w-4 h-4 inline mr-2" />
          No gifts found.
        </div>
      )}
      {!loading && rows.length > 0 && (
        <>
          {/* Desktop: dense table — denser scan + comparable columns.
              Hidden below `md` (768px) where the column count would
              force horizontal scroll. */}
          <table className="hidden md:table w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-2 auth-mono-label">When</th>
                <th className="text-left py-2 auth-mono-label">Gift</th>
                <th className="text-right py-2 auth-mono-label">×</th>
                <th className="text-right py-2 auth-mono-label">💎 each</th>
                <th className="text-right py-2 auth-mono-label">💎 total</th>
                <th className="text-left py-2 auth-mono-label">Recipient</th>
                {showRoomCol && <th className="text-left py-2 auth-mono-label">Room</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.eventId} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                  <td className="py-2 font-mono text-xs text-gray-600 whitespace-nowrap">
                    {formatTs(r.ts, tz)}
                  </td>
                  <td className="py-2 text-xs">{r.giftName}</td>
                  <td className="py-2 text-right font-mono text-xs tabular-nums">
                    {r.repeat}
                  </td>
                  <td className="py-2 text-right font-mono text-xs tabular-nums text-gray-500">
                    {r.perGiftDiamonds}
                  </td>
                  <td className="py-2 text-right font-mono text-xs tabular-nums font-semibold text-amber-700 dark:text-amber-300">
                    {r.totalDiamonds.toLocaleString()}
                  </td>
                  <td className="py-2 text-xs text-gray-700">
                    {r.recipientLabel == null ? (
                      <span
                        className="text-gray-300 font-mono text-[10px]"
                        title="Recipient was not captured for this gift (event predates the to_user field). Newer gifts will show 'Host' or the targeted guest."
                      >
                        —
                      </span>
                    ) : r.recipientLabel === 'Host' ? (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono text-[10px] bg-gray-100 text-gray-600 dark:bg-gray-100/30 dark:text-gray-300">
                        Host
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center px-1.5 py-0.5 rounded font-mono text-[10px] bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300"
                        title="Gift was targeted at a specific guest / opponent (multi-guest live or PK battle)"
                      >
                        {r.recipientLabel}
                      </span>
                    )}
                  </td>
                  {showRoomCol && (
                    <td className="py-2 font-mono text-[10px] text-gray-500">
                      {r.roomId}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-gray-200">
                <td
                  colSpan={4 + (showRoomCol ? 1 : 0)}
                  className="py-2 text-right text-xs auth-mono-label"
                >
                  Visible total
                </td>
                <td className="py-2 text-right font-mono tabular-nums font-bold text-amber-700 dark:text-amber-300">
                  {visibleDiamonds.toLocaleString()}💎
                </td>
                <td />
                {showRoomCol && <td />}
              </tr>
            </tfoot>
          </table>

          {/* Mobile: card list — one row per gift, no horizontal
              scroll. Only renders below `md`. */}
          <ul className="md:hidden flex flex-col gap-1.5">
            {rows.map((r) => (
              <li
                key={r.eventId}
                className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2"
              >
                <div className="flex items-baseline justify-between gap-2 mb-0.5">
                  <div className="min-w-0 flex-1 text-sm font-medium text-gray-900 truncate">
                    {r.giftName}
                    {r.repeat > 1 && (
                      <span className="ml-1.5 text-xs font-mono text-gray-500">
                        ×{r.repeat}
                      </span>
                    )}
                  </div>
                  <div className="shrink-0 font-mono tabular-nums font-bold text-amber-700 dark:text-amber-300">
                    {r.totalDiamonds.toLocaleString()} 💎
                  </div>
                </div>
                <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-gray-500">
                  <div className="min-w-0 flex items-center gap-2 truncate">
                    <span className="tabular-nums shrink-0">{formatTs(r.ts, tz)}</span>
                    {r.perGiftDiamonds > 0 && r.repeat > 1 && (
                      <span className="shrink-0">
                        ({r.perGiftDiamonds.toLocaleString()} 💎 each)
                      </span>
                    )}
                    {showRoomCol && (
                      <span className="text-[10px] truncate" title={`Room ${r.roomId}`}>
                        · {r.roomId}
                      </span>
                    )}
                  </div>
                  <div className="shrink-0">
                    {r.recipientLabel == null ? (
                      <span
                        className="text-gray-300 text-[10px]"
                        title="Recipient was not captured for this gift (event predates the to_user field). Newer gifts will show 'Host' or the targeted guest."
                      >
                        —
                      </span>
                    ) : r.recipientLabel === 'Host' ? (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-gray-100 text-gray-600 dark:bg-gray-100/30 dark:text-gray-300">
                        Host
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300"
                        title="Gift was targeted at a specific guest / opponent (multi-guest live or PK battle)"
                      >
                        {r.recipientLabel}
                      </span>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {/* Mobile-only visible-total bar — desktop has the equivalent
              in the table footer. */}
          <div className="md:hidden mt-3 pt-2 border-t border-gray-200 flex items-baseline justify-between text-xs">
            <span className="auth-mono-label">Visible total</span>
            <span className="font-mono tabular-nums font-bold text-amber-700 dark:text-amber-300">
              {visibleDiamonds.toLocaleString()} 💎
            </span>
          </div>
        </>
      )}
    </>
  );
}

interface CommentsViewProps {
  loading: boolean;
  events: TikTokEvent[];
  showRoomCol: boolean;
}
function CommentsView({ loading, events, showRoomCol }: CommentsViewProps) {
  // Same scoping note as `GiftsView` — pull `tz` from the context
  // directly since this fn isn't lexically inside TikTokGifterModal.
  const { tz } = useTikTokTimezone();

  if (loading) {
    return (
      <div className="py-8 text-center text-gray-500">
        <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
        Loading comments…
      </div>
    );
  }
  if (events.length === 0) {
    return (
      <div className="py-8 text-center text-gray-500">
        <MessageSquare className="w-4 h-4 inline mr-2" />
        This user hasn't commented in this scope.
      </div>
    );
  }

  return (
    <>
      {/* Desktop table (md+). Below md, the `When` + `Room` fixed-
          width columns force horizontal scroll, so we render cards. */}
      <table className="hidden md:table w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="text-left py-2 auth-mono-label" style={{ width: '12rem' }}>When</th>
            <th className="text-left py-2 auth-mono-label">Comment</th>
            {showRoomCol && (
              <th className="text-left py-2 auth-mono-label" style={{ width: '12rem' }}>Room</th>
            )}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => {
            const text = String((e.payload || {}).text ?? '');
            return (
              <tr key={e.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                <td className="py-2 font-mono text-xs text-gray-600 whitespace-nowrap align-top">
                  {formatTs(e.ts, tz)}
                </td>
                <td className="py-2 text-sm break-words">
                  {text || <span className="text-gray-400 italic">(empty)</span>}
                </td>
                {showRoomCol && (
                  <td className="py-2 font-mono text-[10px] text-gray-500 align-top">
                    {e.room_id}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>

      {/* Mobile cards (below md) — comment text dominates; timestamp
          + optional room badge sit on a meta row underneath. */}
      <ul className="md:hidden flex flex-col gap-1.5">
        {events.map((e) => {
          const text = String((e.payload || {}).text ?? '');
          return (
            <li
              key={e.id}
              className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2"
            >
              <div className="text-sm break-words mb-1">
                {text || <span className="text-gray-400 italic">(empty)</span>}
              </div>
              <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-gray-500">
                <span className="tabular-nums">{formatTs(e.ts, tz)}</span>
                {showRoomCol && (
                  <span className="text-[10px] truncate" title={`Room ${e.room_id}`}>
                    · {e.room_id}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}

// ─── small bits ────────────────────────────────────────────────────

interface StatProps {
  label: string;
  value: string;
  accent?: 'amber' | 'sky';
}
function Stat({ label, value, accent }: StatProps) {
  const colorCls =
    accent === 'amber'
      ? 'text-amber-600'
      : accent === 'sky'
        ? 'text-sky-600'
        : 'text-gray-900';
  return (
    <div className="text-right">
      <div className="auth-mono-label">{label}</div>
      <div
        className={`tabular-nums font-bold text-xl ${colorCls}`}
        style={{ fontFamily: 'var(--font-mono-display)' }}
      >
        {value}
      </div>
    </div>
  );
}

function ScopeButton({
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
        'shrink-0 whitespace-nowrap px-2.5 py-1 rounded font-mono text-[11px] border transition-colors ' +
        (active
          ? 'bg-primary-50 text-primary-700 border-primary-200 dark:bg-primary-500/10 dark:border-primary-500/30'
          : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50')
      }
    >
      {children}
    </button>
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
      type="button"
      onClick={onClick}
      // `shrink-0` keeps labels intact when the parent flex row is
      // overflow-scrolling; otherwise the tabs squish unreadably on
      // narrow viewports. `whitespace-nowrap` belt-and-suspenders
      // since some labels contain a count span that would otherwise
      // wrap to a new line.
      className={
        'shrink-0 whitespace-nowrap flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ' +
        (active
          ? 'border-primary-500 text-primary-700 dark:text-primary-300'
          : 'border-transparent text-gray-600 hover:text-gray-900')
      }
    >
      {children}
    </button>
  );
}

function formatTs(iso: string, tz: string): string {
  if (!iso) return '—';
  const p = partsInZone(iso, tz);
  return `${p.month}/${p.day} ${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

// ─── Toolbar (search + filters + page size) ────────────────────────

interface EventListToolbarProps {
  tab: 'gifts' | 'comments';
  q: string;
  setQ: (v: string) => void;
  minDiamonds: number | '';
  setMinDiamonds: (v: number | '') => void;
}

function EventListToolbar({
  tab,
  q, setQ,
  minDiamonds, setMinDiamonds,
}: EventListToolbarProps) {
  const placeholder =
    tab === 'gifts'
      ? 'Filter by gift name or recipient handle (server-side)…'
      : 'Filter by comment text (server-side)…';
  return (
    <div className="mb-3 flex items-center gap-2 flex-wrap">
      {/* Same search shape as `TikTokRoomGiftersTable` — full-width
          input, search icon left, X clear right, focus ring sky. */}
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={placeholder}
          className="w-full pl-8 pr-8 py-1.5 text-sm rounded border border-gray-200 bg-white focus:outline-none focus:ring-1 focus:ring-sky-400 focus:border-sky-400"
        />
        {q && (
          <button
            type="button"
            onClick={() => setQ('')}
            aria-label="Clear filter"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {tab === 'gifts' && (
        <label className="inline-flex items-center gap-1.5 text-[11px] font-mono text-gray-500">
          <Gem className="w-3 h-3 text-amber-500" />
          Min 💎
          <Input
            type="number"
            min={0}
            value={minDiamonds}
            onChange={(e) =>
              setMinDiamonds(e.target.value === '' ? '' : Number(e.target.value))
            }
            placeholder="0"
            className="text-xs font-mono w-24"
          />
        </label>
      )}
    </div>
  );
}

interface PaginationProps {
  page: number;
  pageSize: number;
  setPageSize: (n: number) => void;
  total: number;
  pageItemCount: number;
  loading?: boolean;
  onPage: (n: number) => void;
}

/** Integrated bottom strip — `X–Y of Z · per page · ‹ N/M ›`.
 *  Mirrors the canonical pattern from `TikTokRoomGiftersTable` so
 *  every paginated table in the app reads the same. */
function Pagination({
  page,
  pageSize,
  setPageSize,
  total,
  pageItemCount,
  loading,
  onPage,
}: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const offset = safePage * pageSize;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + pageItemCount, total);
  return (
    <div className="mt-3 flex items-center justify-between gap-2 text-xs flex-wrap">
      <span className="font-mono text-gray-500">
        {showingFrom.toLocaleString()}–{showingTo.toLocaleString()} of{' '}
        {total.toLocaleString()}
        {loading && <Loader2 className="ml-2 w-3 h-3 inline animate-spin" />}
      </span>
      <div className="flex items-center gap-3">
        <label className="inline-flex items-center gap-1 font-mono text-[11px] text-gray-500">
          per page
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="font-mono text-[11px] py-0.5 pl-1 pr-1 rounded border border-gray-200 bg-white"
            aria-label="Rows per page"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onPage(Math.max(0, safePage - 1))}
            disabled={safePage === 0 || loading}
            className="inline-flex items-center justify-center w-7 h-7 rounded border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Previous page"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          <span className="font-mono text-gray-600 px-2">
            {safePage + 1} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => onPage(safePage + 1 < totalPages ? safePage + 1 : safePage)}
            disabled={safePage + 1 >= totalPages || loading}
            className="inline-flex items-center justify-center w-7 h-7 rounded border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Next page"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── MatchesView ───────────────────────────────────────────────────
//
// Lists every PK/match this user contributed gifts to, within the
// active scope. Each row carries the host + opponents identity, the
// match window, and THIS user's per-match contribution so the
// operator can pattern-spot "this whale only shows up for the
// late-night PKs against @opp".

interface MatchesViewProps {
  data: { items: TikTokUserMatchEntry[]; total: number } | null;
  loading: boolean;
  error: string | null;
  page: number;
  pageSize: number;
  onPage: (p: number) => void;
  currentHandle?: string;
  tz: string;
}

function MatchesView({
  data,
  loading,
  error,
  page,
  pageSize,
  onPage,
  currentHandle,
  tz,
}: MatchesViewProps) {
  if (loading && !data) {
    return (
      <div className="py-10 text-center text-sm text-gray-500">
        <Loader2 className="w-4 h-4 inline animate-spin mr-1.5" />
        Loading matches…
      </div>
    );
  }
  if (error) {
    return (
      <div className="py-6 text-center text-sm text-rose-600">{error}</div>
    );
  }
  if (!data || data.total === 0) {
    return (
      <div className="py-10 text-center text-sm text-gray-500">
        No match contributions in this scope.
      </div>
    );
  }
  const totalPages = Math.max(1, Math.ceil(data.total / pageSize));
  return (
    <div className="flex flex-col gap-2">
      {data.items.map((m) => {
        const hostHandle = m.host_unique_id ?? '';
        // Strip the host from the opponents list when rendering "vs"
        // since hosts appear in their own opponents block in 4-way
        // battles.
        const others = m.opponents.filter(
          (o) => (o.unique_id || '').toLowerCase() !== hostHandle.toLowerCase(),
        );
        const isCurrentHost =
          currentHandle && hostHandle.toLowerCase() === currentHandle.toLowerCase();
        return (
          <div
            key={m.match_id}
            className="rounded border border-gray-200 bg-gray-50 dark:bg-white/[0.03] px-3 py-2"
          >
            <div className="flex items-center justify-between gap-2 mb-1">
              <div className="text-[11px] font-mono text-gray-500 truncate">
                {m.started_at && (
                  <span className="tabular-nums">
                    {fmtMonthDayTime(m.started_at, tz)}
                  </span>
                )}
                {m.ended_at && m.started_at && (
                  <span className="ml-1.5">
                    · {fmtDurationFromIso(m.started_at, m.ended_at)}
                  </span>
                )}
              </div>
              <div className="shrink-0 inline-flex items-center gap-1.5 text-[10px] font-mono">
                <span className="tabular-nums font-bold text-amber-700 dark:text-amber-300">
                  {m.user_diamonds.toLocaleString()} 💎
                </span>
                <span className="text-gray-500">
                  ({m.user_gifts} gift{m.user_gifts === 1 ? '' : 's'})
                </span>
              </div>
            </div>
            <div className="flex items-baseline gap-1 flex-wrap text-sm">
              {hostHandle ? (
                isCurrentHost ? (
                  <span className="font-medium text-gray-900">@{hostHandle}</span>
                ) : (
                  <Link
                    to="/admin/tiktok/$handle"
                    params={{ handle: hostHandle }}
                    className="font-medium text-primary-700 hover:underline"
                  >
                    @{hostHandle}
                  </Link>
                )
              ) : (
                <span className="text-gray-500 italic">unknown host</span>
              )}
              {others.length > 0 && (
                <span className="text-gray-500 text-xs">vs</span>
              )}
              {others.map((o, i) => (
                <span key={(o.unique_id ?? i) + '-' + i} className="text-xs font-mono text-gray-700">
                  @{o.unique_id ?? '?'}
                  {i < others.length - 1 ? ',' : ''}
                </span>
              ))}
            </div>
          </div>
        );
      })}
      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-2 text-[11px] font-mono text-gray-500 pt-1">
          <button
            type="button"
            onClick={() => onPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="inline-flex items-center px-1.5 py-0.5 rounded hover:bg-gray-100 disabled:opacity-30"
          >
            <ChevronLeft className="w-3 h-3" />
          </button>
          <span className="tabular-nums">
            {page + 1} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => onPage(Math.min(totalPages - 1, page + 1))}
            disabled={page + 1 >= totalPages}
            className="inline-flex items-center px-1.5 py-0.5 rounded hover:bg-gray-100 disabled:opacity-30"
          >
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}

/** Format a duration between two iso timestamps as `Hh Mm` / `Mm Ss`. */
function fmtDurationFromIso(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return '—';
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}m ${sec % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

// ─── RelationshipsView ─────────────────────────────────────────────
//
// Shows where ELSE this gifter sends gifts. Backed by
// /admin/tiktok/common-gifters/{user_id}/detail — the same payload
// the standalone Common Gifter modal uses, but rendered as a compact
// per-host list in this nested modal context. Hosts are sorted by
// diamonds desc; the "current" host (the page the modal was opened
// from) is marked and its row keeps the link disabled.

interface RelationshipsViewProps {
  data: TikTokCommonGifterDetail | null;
  loading: boolean;
  error: string | null;
  currentHandle?: string;
  tz: string;
}

function RelationshipsView({
  data,
  loading,
  error,
  currentHandle,
  tz,
}: RelationshipsViewProps) {
  if (error) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 px-4 py-6 text-sm text-rose-700 dark:text-rose-300">
        {error}
      </div>
    );
  }
  if (loading && !data) {
    return (
      <div className="py-10 text-center text-sm text-gray-500">
        <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
        Loading cross-host activity…
      </div>
    );
  }
  if (!data || data.hosts.length === 0) {
    return (
      <div className="py-8 flex flex-col items-center gap-2 text-center">
        <Users className="w-8 h-8 text-gray-300 dark:text-gray-100/40" />
        <p className="text-sm text-gray-700 dark:text-gray-300 font-medium">
          No other hosts
        </p>
        <p className="text-xs text-gray-500 max-w-xs">
          This viewer hasn't gifted to any other tracked creator yet.
        </p>
      </div>
    );
  }

  // Hosts sorted desc by diamonds (already that order from the
  // backend). Compute % share so each host's row tells you "how
  // important is this host in this viewer's gifting?".
  const totalDiamonds = data.totals.diamonds;
  const currentNorm = (currentHandle || '').replace(/^@/, '').toLowerCase();

  return (
    <div className="flex flex-col gap-3">
      {/* Compact summary strip — saves the user a glance back at the
          tab badge to count hosts. */}
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs font-mono text-gray-600">
        <span>
          <Users className="w-3 h-3 inline -mt-0.5 mr-1 text-primary-500" />
          <span className="text-primary-700 dark:text-primary-300 font-medium">
            {data.totals.host_count}
          </span>{' '}
          hosts
        </span>
        <span>
          <Radio className="w-3 h-3 inline -mt-0.5 mr-1 text-emerald-500" />
          <span className="text-gray-900 dark:text-gray-100">
            {data.totals.room_count}
          </span>{' '}
          rooms
        </span>
        <span>
          <Gem className="w-3 h-3 inline -mt-0.5 mr-1 text-amber-500" />
          <span className="text-amber-700 dark:text-amber-300">
            {data.totals.diamonds.toLocaleString()}
          </span>{' '}
          total
        </span>
        <span>
          first: {fmtMonthDayTime(data.totals.first_seen_at, tz)}
          {' '}· last: {fmtMonthDayTime(data.totals.last_seen_at, tz)}
        </span>
      </div>

      <ul className="rounded-lg border border-gray-200 overflow-hidden divide-y divide-gray-100 dark:divide-gray-100/30">
        {data.hosts.map((h) => {
          const isCurrent = h.host.toLowerCase() === currentNorm;
          const pct = totalDiamonds > 0 ? (h.diamonds / totalDiamonds) * 100 : 0;
          return (
            <li
              key={h.host}
              className={
                'p-3 flex items-start gap-3 ' +
                (isCurrent
                  ? 'bg-primary-50/60 dark:bg-primary-500/10'
                  : 'hover:bg-gray-50 dark:hover:bg-gray-100/10')
              }
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="font-medium text-gray-900 dark:text-gray-100 truncate">
                    @{h.host}
                  </span>
                  {isCurrent && (
                    <span
                      className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-primary-100 dark:bg-primary-500/15 text-primary-800 dark:text-primary-200 text-[10px] font-mono"
                      title="The page you're currently viewing"
                    >
                      this host
                    </span>
                  )}
                  <span
                    className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-200 text-[10px] font-mono"
                    title="Share of this viewer's total cross-host diamonds"
                  >
                    {pct.toFixed(1)}%
                  </span>
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs font-mono text-gray-600">
                  <span className="text-amber-700 dark:text-amber-300 tabular-nums">
                    💎 {h.diamonds.toLocaleString()}
                  </span>
                  <span className="text-gray-500 tabular-nums">
                    {h.gifts.toLocaleString()} gifts
                  </span>
                  <span className="text-gray-500 tabular-nums">
                    {h.room_count} rooms
                  </span>
                  {h.comment_count > 0 && (
                    <span className="text-sky-700 dark:text-sky-300 tabular-nums">
                      {h.comment_count.toLocaleString()} comments
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-[11px] font-mono text-gray-500">
                  first: {fmtMonthDayTime(h.first_seen_at, tz)}
                  {' '}· last: {fmtMonthDayTime(h.last_seen_at, tz)}
                </div>
                {h.top_gifts.length > 0 && (
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    {h.top_gifts.slice(0, 4).map((g) => (
                      <span
                        key={g.gift_name}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] bg-gray-100 dark:bg-gray-100/15 text-gray-700 dark:text-gray-300"
                        title={`${g.diamonds.toLocaleString()} 💎 across ${g.count.toLocaleString()} gifts`}
                      >
                        <span className="truncate max-w-[8rem]">{g.gift_name}</span>
                        <span className="text-gray-500 tabular-nums">×{g.count.toLocaleString()}</span>
                      </span>
                    ))}
                    {h.top_gifts.length > 4 && (
                      <span className="text-[10px] text-gray-500 font-mono">
                        +{h.top_gifts.length - 4} more
                      </span>
                    )}
                  </div>
                )}
              </div>
              {!isCurrent && (
                <Link
                  to="/admin/tiktok/$handle"
                  params={{ handle: h.host }}
                  className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-primary-200 text-primary-700 hover:bg-primary-50 hover:border-primary-300 dark:text-primary-300 text-xs font-medium"
                  title={`Open @${h.host}'s live-detail page`}
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  View Host Live
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

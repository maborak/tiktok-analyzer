import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, Loader2, Search, X } from 'lucide-react';

import { type TikTokGifter } from '@admin/services/tiktok';
import { useTikTokApi } from '@admin/contexts/TikTokApiContext';
import { TikTokUserBadges } from '@admin/components/TikTokUserBadges';

interface Props {
  roomId: string | null;
  /** Day-aggregate view: extra rooms whose gifters should be summed
   *  with the path roomId. Empty / undefined → single-room behavior. */
  extraRoomIds?: string[];
  /** Match `getRoomStats`'s effective range so the gifters table reflects
   *  the same window as the rest of the page. Pass `undefined` for "all". */
  range: { since?: string; until?: string };
  /** Bumped by the parent (refresh button, room change) to force a refetch. */
  refreshKey: number;
  /** When a row is clicked we hand the user context up so the parent can
   *  open its shared GifterModal (which already has gifts/comments tabs). */
  onSelectGifter: (g: {
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
    diamonds: number;
    gifts: number;
    comments: number;
    tab: 'gifts' | 'comments';
  }) => void;
  /** Bubble the server-side total up to the parent — the live-detail
   *  page uses this to render `Top gifters (N)` on the tab label. */
  onTotalChange?: (total: number) => void;
  /** Bubble the CURRENT page's items up so sibling visualizations
   *  (the Top Gifter donut on the right of the table) can render the
   *  same rows without firing a duplicate `getRoomGifters` call. The
   *  donut visualises whatever page / search / page-size the user is
   *  looking at — page 2 of the table → donut shows that page's slice. */
  onItemsChange?: (items: TikTokGifter[]) => void;
  /** Bubble the table's loading state up so siblings can mirror it
   *  (donut shows a spinner during the fetch instead of an empty
   *  "No data" flash between page changes). */
  onLoadingChange?: (loading: boolean) => void;
}

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 10;

export function TikTokRoomGiftersTable({
  roomId,
  extraRoomIds,
  range,
  refreshKey,
  onSelectGifter,
  onTotalChange,
  onItemsChange,
  onLoadingChange,
}: Props) {
  const tiktokApi = useTikTokApi();
  // Stringify the extras for use as a stable dep key — array identity
  // changes every render even when contents don't.
  const extraKey = (extraRoomIds ?? []).join(',');
  const [items, setItems] = useState<TikTokGifter[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);

  // Debounce typed search; reset paging when the query changes.
  const [debouncedQ, setDebouncedQ] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  // Reset offset whenever inputs that change the result set change.
  useEffect(() => {
    setOffset(0);
  }, [roomId, extraKey, range.since, range.until, debouncedQ, refreshKey, pageSize]);

  useEffect(() => {
    if (!roomId) {
      setItems([]);
      setTotal(0);
      onTotalChange?.(0);
      onItemsChange?.([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    onLoadingChange?.(true);
    tiktokApi
      .getRoomGifters(roomId, {
        since: range.since,
        until: range.until,
        q: debouncedQ || undefined,
        limit: pageSize,
        offset,
        extra_room_ids: extraRoomIds && extraRoomIds.length > 0 ? extraRoomIds : undefined,
      })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
        onTotalChange?.(res.total);
        onItemsChange?.(res.items);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
        onTotalChange?.(0);
        onItemsChange?.([]);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        onLoadingChange?.(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, extraKey, range.since, range.until, debouncedQ, offset, pageSize, refreshKey]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + items.length, total);

  return (
    <div>
      <div className="relative mb-3">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by nickname or @handle (server-side)…"
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

      {loading && items.length === 0 ? (
        <div className="py-8 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
          Loading gifters…
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-gray-500 py-4 text-center">
          {debouncedQ
            ? 'No gifters match that filter.'
            : 'No gifts yet.'}
        </p>
      ) : (
        <>
          {/* Desktop: dense 5-column table (md+). Hidden below md
              where the columns would force horizontal scroll. */}
          <table className="hidden md:table w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-2 auth-mono-label w-10">#</th>
                <th className="text-left py-2 auth-mono-label">User</th>
                <th className="text-right py-2 auth-mono-label">Diamonds</th>
                <th className="text-right py-2 auth-mono-label">Gifts</th>
                <th className="text-right py-2 auth-mono-label">Comments</th>
              </tr>
            </thead>
            <tbody>
              {items.map((g, i) => (
                <tr
                  key={g.user_id ?? i}
                  className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors"
                  onClick={() =>
                    onSelectGifter({
                      userId: g.user_id,
                      uniqueId: g.unique_id,
                      nickname: g.nickname,
                      diamonds: g.diamonds,
                      gifts: g.gifts,
                      comments: g.comments,
                      tab: 'gifts',
                    })
                  }
                  title="Click for full gift history"
                >
                  <td className="py-2 font-mono text-xs text-gray-500 tabular-nums">
                    {offset + i + 1}
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-2 min-w-0">
                      {g.avatar_url ? (
                        <img
                          src={g.avatar_url}
                          alt=""
                          className="w-6 h-6 rounded-full object-cover flex-shrink-0 bg-gray-100"
                          loading="lazy"
                        />
                      ) : (
                        <span
                          aria-hidden
                          className="w-6 h-6 rounded-full flex-shrink-0 bg-gray-100 inline-flex items-center justify-center text-[10px] font-mono text-gray-400"
                        >
                          {(g.nickname || g.unique_id || '?').slice(0, 1).toUpperCase()}
                        </span>
                      )}
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-medium truncate">{g.nickname ?? '—'}</span>
                          <TikTokUserBadges identity={g.identity} />
                        </div>
                        {g.unique_id && (
                          <div className="text-[11px] text-gray-500 font-mono truncate">
                            @{g.unique_id}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="text-right py-2 font-mono tabular-nums">
                    {g.diamonds.toLocaleString()}
                  </td>
                  <td className="text-right py-2 font-mono tabular-nums">
                    {g.gifts.toLocaleString()}
                  </td>
                  <td className="text-right py-2">
                    {g.comments > 0 ? (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectGifter({
                            userId: g.user_id,
                            uniqueId: g.unique_id,
                            nickname: g.nickname,
                            diamonds: g.diamonds,
                            gifts: g.gifts,
                            comments: g.comments,
                            tab: 'comments',
                          });
                        }}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300 hover:bg-sky-100 dark:hover:bg-sky-500/20 transition-colors"
                        title="View this user's comments"
                      >
                        💬 {g.comments}
                      </button>
                    ) : (
                      <span className="text-gray-300 font-mono text-[10px]">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Mobile: stacked card per gifter (below md). Avatar +
              nickname + badges on the top row, totals + comments chip
              on the bottom row. Whole card opens the Gifts tab; the
              comments chip stops propagation and opens Comments. */}
          <ul className="md:hidden flex flex-col gap-2">
            {items.map((g, i) => (
              <li
                key={g.user_id ?? i}
                className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 cursor-pointer hover:bg-gray-50 transition-colors"
                onClick={() =>
                  onSelectGifter({
                    userId: g.user_id,
                    uniqueId: g.unique_id,
                    nickname: g.nickname,
                    diamonds: g.diamonds,
                    gifts: g.gifts,
                    comments: g.comments,
                    tab: 'gifts',
                  })
                }
                title="Tap for full gift history"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono text-[10px] text-gray-500 tabular-nums shrink-0 w-6">
                    #{offset + i + 1}
                  </span>
                  {g.avatar_url ? (
                    <img
                      src={g.avatar_url}
                      alt=""
                      className="w-8 h-8 rounded-full object-cover flex-shrink-0 bg-gray-100"
                      loading="lazy"
                    />
                  ) : (
                    <span
                      aria-hidden
                      className="w-8 h-8 rounded-full flex-shrink-0 bg-gray-100 inline-flex items-center justify-center text-xs font-mono text-gray-400"
                    >
                      {(g.nickname || g.unique_id || '?').slice(0, 1).toUpperCase()}
                    </span>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-medium truncate text-sm">{g.nickname ?? '—'}</span>
                      <TikTokUserBadges identity={g.identity} />
                    </div>
                    {g.unique_id && (
                      <div className="text-[11px] text-gray-500 font-mono truncate">
                        @{g.unique_id}
                      </div>
                    )}
                  </div>
                </div>
                <div className="mt-2 pt-2 border-t border-gray-100 flex items-center gap-3 text-[11px] font-mono">
                  <span className="flex items-center gap-1">
                    <span className="text-amber-600">💎</span>
                    <span className="tabular-nums font-semibold text-gray-900">
                      {g.diamonds.toLocaleString()}
                    </span>
                  </span>
                  <span className="flex items-center gap-1 text-gray-600">
                    <span className="text-[10px] uppercase tracking-wider text-gray-400">gifts</span>
                    <span className="tabular-nums">{g.gifts.toLocaleString()}</span>
                  </span>
                  {g.comments > 0 ? (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectGifter({
                          userId: g.user_id,
                          uniqueId: g.unique_id,
                          nickname: g.nickname,
                          diamonds: g.diamonds,
                          gifts: g.gifts,
                          comments: g.comments,
                          tab: 'comments',
                        });
                      }}
                      className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded font-mono text-[10px] bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300 hover:bg-sky-100 dark:hover:bg-sky-500/20 transition-colors"
                      title="View this user's comments"
                    >
                      💬 {g.comments}
                    </button>
                  ) : (
                    <span className="ml-auto text-gray-300 text-[10px]">no comments</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Pagination + count line — render even when loading so layout is stable. */}
      {total > 0 && (
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
                {PAGE_SIZE_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() =>
                  setOffset((o) => Math.max(0, o - pageSize))
                }
                disabled={offset === 0 || loading}
                className="inline-flex items-center justify-center w-7 h-7 rounded border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                aria-label="Previous page"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
              <span className="font-mono text-gray-600 px-2">
                {currentPage} / {totalPages}
              </span>
              <button
                type="button"
                onClick={() =>
                  setOffset((o) =>
                    o + pageSize < total ? o + pageSize : o
                  )
                }
                disabled={offset + pageSize >= total || loading}
                className="inline-flex items-center justify-center w-7 h-7 rounded border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
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

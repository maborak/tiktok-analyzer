import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, Loader2, Network, Search, X } from 'lucide-react';

import { type TikTokCrossLiveGifter } from '@admin/services/tiktok';
import { useTikTokApi } from '@admin/contexts/TikTokApiContext';
import { useTikTokRuntimeConfig } from '@admin/contexts/TikTokRuntimeConfigContext';

interface Props {
  /** The host whose audience to cross-reference. The endpoint is
   *  host-scoped — pass the handle, not the room id. */
  handle: string;
  /** Bumped by the parent (refresh button, host change) to force a refetch. */
  refreshKey: number;
  /** Clicking a row hands the cross-host gifter's `user_id` up so the
   *  parent can open the unified `TikTokGifterDetailModal` on its
   *  Profile tab (the cross-host deep-dive). The string id is
   *  server-cast to JS-safe via the persistence layer. */
  onSelectCrossGifter: (userId: string) => void;
  /** Bubble the server-side total up — the parent's tab label uses it
   *  to render `Cross-live (N)`. */
  onTotalChange?: (total: number) => void;
}

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 10;

export function TikTokRoomCrossLiveGiftersTable({
  handle,
  refreshKey,
  onSelectCrossGifter,
  onTotalChange,
}: Props) {
  const tiktokApi = useTikTokApi();
  // The detail modal opened by `onSelectCrossGifter` calls
  // `/admin/tiktok/common-gifters/<id>/detail` — admin-only, no
  // public mirror exists. On the public mount we still show the
  // table (cross-live activity is useful info even read-only) but
  // disable row interaction so anonymous viewers don't trip a 401
  // when they click a row.
  const { audience } = useTikTokRuntimeConfig();
  const canOpenDetail = audience === 'admin';
  const [items, setItems] = useState<TikTokCrossLiveGifter[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);

  // Debounce typed search; reset paging when query changes.
  const [debouncedQ, setDebouncedQ] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  // Reset offset on input changes.
  useEffect(() => {
    setOffset(0);
  }, [handle, debouncedQ, refreshKey, pageSize]);

  useEffect(() => {
    if (!handle) {
      setItems([]);
      setTotal(0);
      onTotalChange?.(0);
      return;
    }
    let cancelled = false;
    setLoading(true);
    tiktokApi
      .getRoomCrossLiveGifters(handle, {
        q: debouncedQ || undefined,
        limit: pageSize,
        offset,
      })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
        onTotalChange?.(res.total);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
        onTotalChange?.(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle, debouncedQ, offset, pageSize, refreshKey]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + items.length, total);

  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-mono text-gray-500">
        <Network className="w-3.5 h-3.5 text-violet-500" />
        Viewers who gifted to <span className="text-gray-700">@{handle}</span> AND at least one other tracked live.
      </div>

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
          Loading cross-live gifters…
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-gray-500 py-4 text-center">
          {debouncedQ
            ? 'No cross-live gifters match that filter.'
            : 'No viewers have gifted across multiple tracked lives yet.'}
        </p>
      ) : (
        <>
          {/* Desktop: 5-column table (md+). */}
          <table className="hidden md:table w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-2 auth-mono-label w-10">#</th>
                <th className="text-left py-2 auth-mono-label">User</th>
                <th className="text-right py-2 auth-mono-label">Diamonds here</th>
                <th className="text-right py-2 auth-mono-label">Elsewhere</th>
                <th className="text-left py-2 auth-mono-label pl-3">Also active on</th>
              </tr>
            </thead>
            <tbody>
              {items.map((g, i) => (
                <tr
                  key={g.user_id ?? i}
                  className={
                    'border-b border-gray-100 transition-colors ' +
                    (canOpenDetail ? 'hover:bg-gray-50 cursor-pointer' : '')
                  }
                  onClick={canOpenDetail ? () => g.user_id && onSelectCrossGifter(g.user_id) : undefined}
                  title={canOpenDetail ? 'Click for cross-host breakdown' : 'Cross-host detail is admin-only'}
                >
                  <td className="py-2 font-mono text-xs text-gray-500 tabular-nums">
                    {offset + i + 1}
                  </td>
                  <td className="py-2">
                    <UserCell g={g} />
                  </td>
                  <td className="text-right py-2 font-mono tabular-nums">
                    <span className="font-semibold">{g.diamonds_here.toLocaleString()}</span>
                    <span className="ml-1 text-amber-600">💎</span>
                  </td>
                  <td className="text-right py-2 font-mono tabular-nums text-gray-600">
                    {g.diamonds_elsewhere.toLocaleString()}
                    <span className="ml-1 text-[10px] text-gray-400">
                      / {g.host_count - 1} {g.host_count - 1 === 1 ? 'live' : 'lives'}
                    </span>
                  </td>
                  <td className="py-2 pl-3">
                    <OtherHostsStrip
                      hosts={g.other_hosts}
                      max={4}
                      tone="violet"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Mobile: stacked cards (below md). */}
          <ul className="md:hidden flex flex-col gap-2">
            {items.map((g, i) => (
              <li
                key={g.user_id ?? i}
                className={
                  'rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 transition-colors ' +
                  (canOpenDetail ? 'cursor-pointer hover:bg-gray-50' : '')
                }
                onClick={canOpenDetail ? () => g.user_id && onSelectCrossGifter(g.user_id) : undefined}
                title={canOpenDetail ? 'Tap for cross-host breakdown' : 'Cross-host detail is admin-only'}
              >
                <div className="flex items-center gap-2 min-w-0 mb-2">
                  <span className="font-mono text-[10px] text-gray-500 tabular-nums shrink-0 w-6">
                    #{offset + i + 1}
                  </span>
                  <UserCell g={g} size="lg" />
                </div>
                <div className="pt-2 border-t border-gray-100 grid grid-cols-2 gap-2 text-[11px] font-mono mb-2">
                  <div className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wider text-gray-400">Here</span>
                    <span className="tabular-nums font-semibold text-gray-900">
                      {g.diamonds_here.toLocaleString()}
                      <span className="ml-1 text-amber-600">💎</span>
                    </span>
                  </div>
                  <div className="flex flex-col text-right">
                    <span className="text-[10px] uppercase tracking-wider text-gray-400">
                      Across {g.host_count - 1} other {g.host_count - 1 === 1 ? 'live' : 'lives'}
                    </span>
                    <span className="tabular-nums text-gray-700">
                      {g.diamonds_elsewhere.toLocaleString()}
                      <span className="ml-1 text-amber-600">💎</span>
                    </span>
                  </div>
                </div>
                <div className="pt-2 border-t border-gray-100">
                  <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">
                    Also active on
                  </div>
                  <OtherHostsStrip
                    hosts={g.other_hosts}
                    max={5}
                    tone="violet"
                  />
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Pagination + count line — same layout as TikTokRoomGiftersTable. */}
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
                onClick={() => setOffset((o) => Math.max(0, o - pageSize))}
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
                  setOffset((o) => (o + pageSize < total ? o + pageSize : o))
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

// ── helpers ─────────────────────────────────────────────────────────

function UserCell({ g, size = 'md' }: { g: TikTokCrossLiveGifter; size?: 'md' | 'lg' }) {
  const avatarSize = size === 'lg' ? 'w-8 h-8 text-xs' : 'w-6 h-6 text-[10px]';
  const initial = (g.nickname || g.unique_id || '?').slice(0, 1).toUpperCase();
  return (
    <div className="flex items-center gap-2 min-w-0 flex-1">
      {g.avatar_url ? (
        <img
          src={g.avatar_url}
          alt=""
          className={`${avatarSize} rounded-full object-cover flex-shrink-0 bg-gray-100`}
          loading="lazy"
        />
      ) : (
        <span
          aria-hidden
          className={`${avatarSize} rounded-full flex-shrink-0 bg-gray-100 inline-flex items-center justify-center font-mono text-gray-400`}
        >
          {initial}
        </span>
      )}
      <div className="min-w-0">
        <div className="font-medium truncate">{g.nickname ?? '—'}</div>
        {g.unique_id && (
          <div className="text-[11px] text-gray-500 font-mono truncate">
            @{g.unique_id}
          </div>
        )}
      </div>
    </div>
  );
}

function OtherHostsStrip({
  hosts,
  max,
  tone,
}: {
  hosts: { host: string; diamonds: number; gifts: number }[];
  max: number;
  tone: 'violet';
}) {
  const visible = hosts.slice(0, max);
  const overflow = Math.max(0, hosts.length - max);
  const pillCls =
    tone === 'violet'
      ? 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300'
      : '';
  return (
    <div className="flex flex-wrap items-center gap-1">
      {visible.map((h) => (
        <span
          key={h.host}
          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] ${pillCls}`}
          title={`${h.diamonds.toLocaleString()} 💎 · ${h.gifts.toLocaleString()} gifts on @${h.host}`}
        >
          @{h.host}
          <span className="tabular-nums opacity-70">
            {compact(h.diamonds)}💎
          </span>
        </span>
      ))}
      {overflow > 0 && (
        <span
          className="inline-flex items-center px-1.5 py-0.5 rounded font-mono text-[10px] bg-gray-100 text-gray-600 dark:bg-gray-100/30 dark:text-gray-300"
          title={`+${overflow} more: ${hosts.slice(max).map((h) => '@' + h.host).join(', ')}`}
        >
          +{overflow}
        </span>
      )}
    </div>
  );
}

function compact(n: number): string {
  if (n < 1000) return n.toString();
  if (n < 10_000) return `${(n / 1000).toFixed(1)}k`;
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

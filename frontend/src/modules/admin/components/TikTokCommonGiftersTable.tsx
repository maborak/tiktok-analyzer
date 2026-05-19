/**
 * Cross-creator gifter leaderboard.
 *
 * Backed by GET /admin/tiktok/common-gifters. Each row is a viewer who
 * has gifted to >= `min_hosts` distinct creators we track; the row
 * shows their identity, totals across all hosts, and a per-host pill
 * strip (links into each creator's live-detail page) so the user can
 * see WHICH creators they've bridged at a glance.
 *
 * Used as a tab on /admin/tiktok beside "Lives" / "Worker".
 */

import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from '@tanstack/react-router';
import { ChevronLeft, ChevronRight, Loader2, RefreshCw, Search, Users, X } from 'lucide-react';

import {
  type TikTokCommonGifter,
  type TikTokCommonGiftersPage,
  type TikTokWsEvent,
  openTikTokWebSocket,
  tiktokApi,
} from '@admin/services/tiktok';
import { SafeAvatar } from '@admin/components/SafeAvatar';
// Lazy-load the gifter modal so the echarts chunk it pulls in is
// only fetched when a row is actually clicked. Without this, every
// page that mounts this table (TikTokLives, TikTokLiveDetail) pays
// for the full modal bundle on first paint.
const TikTokGifterDetailModal = lazy(() =>
  import('@admin/components/TikTokGifterDetailModal')
    .then((m) => ({ default: m.TikTokGifterDetailModal })),
);

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 25;
const MIN_HOSTS_OPTIONS = [2, 3, 4, 5, 10] as const;

// localStorage key shared across (filter, page) combos. Holds the
// last successful response keyed by `${minHosts}|${q}|${pageSize}|${offset}`.
// Hydrating from this on mount makes the tab feel instant even on a
// cold load — the network refetch then swaps in the live data.
const LS_KEY = 'tiktok.common-gifters.cache.v1';

interface CacheBucket {
  ts: number;
  page: TikTokCommonGiftersPage;
}
type Cache = Record<string, CacheBucket>;

function readCache(): Cache {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Cache;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeCache(c: Cache): void {
  try {
    // Cap at 24 entries — common filter combos. LRU-ish eviction by
    // dropping the oldest when over capacity.
    const entries = Object.entries(c);
    if (entries.length > 24) {
      entries.sort((a, b) => b[1].ts - a[1].ts);
      const trimmed = Object.fromEntries(entries.slice(0, 24));
      localStorage.setItem(LS_KEY, JSON.stringify(trimmed));
    } else {
      localStorage.setItem(LS_KEY, JSON.stringify(c));
    }
  } catch {
    /* localStorage may be full / blocked — ignore */
  }
}

function cacheKey(
  minHosts: number, q: string, pageSize: number, offset: number,
): string {
  return `${minHosts}|${q}|${pageSize}|${offset}`;
}

function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}

interface Props {
  /** Bumped by the parent's refresh button to force a refetch without
   *  remounting the component (preserves search input + page state). */
  refreshKey?: number;
  /** "common" (default) → user-pickable min-hosts threshold (≥2 by
   *  default), the cross-host bridging leaderboard.
   *  "global" → fixed min_hosts=1, hides the threshold control;
   *  every viewer who has gifted to any tracked creator. Same row
   *  shape, same modal — just a different scope. */
  mode?: 'common' | 'global';
}

export function TikTokCommonGiftersTable({ refreshKey = 0, mode = 'common' }: Props) {
  const [items, setItems] = useState<TikTokCommonGifter[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  // In "global" mode the threshold is fixed at 1 (anyone who has
  // gifted at all). In "common" mode the user picks; default 2.
  const [minHosts, setMinHosts] = useState<number>(mode === 'global' ? 1 : 2);
  // Reset the threshold whenever mode flips so navigating tabs leaves
  // each in its expected state.
  useEffect(() => {
    setMinHosts(mode === 'global' ? 1 : 2);
  }, [mode]);
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Selected gifter for the deep-analysis modal. Carries the row's
  // identity so the modal can render the avatar/name immediately
  // without flashing "Loading…" while the detail fetch is in flight.
  const [selected, setSelected] = useState<TikTokCommonGifter | null>(null);
  // Number of new gift events the WS has pushed since the last
  // successful fetch. Drives the "(N new gifts) Refresh" chip;
  // reset to 0 on every refetch.
  const [pendingDelta, setPendingDelta] = useState(0);
  // Bumps to force the fetch effect to re-run (manual / ws-triggered
  // refresh), keeping the existing dep set as-is.
  const [manualRefreshTick, setManualRefreshTick] = useState(0);

  // Debounce the search; reset paging on either filter change.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    setOffset(0);
  }, [debouncedQ, pageSize, minHosts, refreshKey]);

  // Stale-while-revalidate: hydrate from localStorage cache the
  // moment the (filter, page) tuple matches a cached entry — so the
  // tab paints content instantly even on a cold open. Then the
  // network fetch below swaps in the live data when it lands.
  useEffect(() => {
    const k = cacheKey(minHosts, debouncedQ, pageSize, offset);
    const cache = readCache();
    const hit = cache[k];
    if (hit) {
      setItems(hit.page.items);
      setTotal(hit.page.total);
    }
    // No `else` — if there's no hit we let the network fetch render
    // the loading state below.
  }, [minHosts, debouncedQ, pageSize, offset]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    tiktokApi
      .getCommonGifters({
        min_hosts: minHosts,
        q: debouncedQ || undefined,
        limit: pageSize,
        offset,
      })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
        setPendingDelta(0);
        // Persist the freshest version for the next mount.
        const k = cacheKey(minHosts, debouncedQ, pageSize, offset);
        const cache = readCache();
        cache[k] = { ts: Date.now(), page: res };
        writeCache(cache);
      })
      .catch((e) => {
        if (cancelled) return;
        // Don't blank the UI on a transient error — keep whatever
        // hydrated cache we have and surface the error inline.
        setError((e as Error).message || 'Failed to load common gifters');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [minHosts, debouncedQ, offset, pageSize, refreshKey, manualRefreshTick]);

  // WS-driven invalidation: subscribe to gift events from every
  // tracked host while this tab is mounted and increment a counter
  // for each one. The user gets a "(N new gifts) Refresh" chip and
  // can click to refetch — or we can auto-refetch after a debounce
  // when activity is high. No polling.
  const pendingDeltaRef = useRef(0);
  useEffect(() => {
    pendingDeltaRef.current = pendingDelta;
  }, [pendingDelta]);
  useEffect(() => {
    const ws = openTikTokWebSocket(
      (msg: TikTokWsEvent) => {
        if (msg.type !== 'gift') return;
        // The summary table only counts gifts with a viewer + host;
        // a missing user_id wouldn't move the leaderboard. Guard so
        // we don't trigger a useless refetch.
        if (!msg.user_id) return;
        setPendingDelta((n) => n + 1);
      },
      undefined,
      { handles: '*' },
    );
    return () => {
      try { ws.close(); } catch { /* ignore */ }
    };
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + items.length, total);

  return (
    <div className="flex flex-col gap-3">
      {/* Filter row: search, min-hosts threshold, page size. */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by nickname or @unique_id"
            className="w-full pl-8 pr-8 py-2 rounded-md border border-gray-200 text-sm font-mono dark:bg-gray-100/5"
          />
          {q && (
            <button
              type="button"
              onClick={() => setQ('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700"
              aria-label="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        {mode === 'common' && (
          <label className="flex items-center gap-1.5 text-xs font-mono text-gray-600">
            Active across ≥
            <select
              value={minHosts}
              onChange={(e) => setMinHosts(Number(e.target.value))}
              className="px-2 py-1 rounded-md border border-gray-200 text-xs font-mono dark:bg-gray-100/5"
            >
              {MIN_HOSTS_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            hosts
          </label>
        )}
        <label className="flex items-center gap-1.5 text-xs font-mono text-gray-600">
          Per page
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="px-2 py-1 rounded-md border border-gray-200 text-xs font-mono dark:bg-gray-100/5"
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        {pendingDelta > 0 && (
          <button
            type="button"
            onClick={() => setManualRefreshTick((n) => n + 1)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-50 border border-amber-300 text-amber-800 hover:bg-amber-100 dark:bg-amber-500/15 dark:border-amber-500/30 dark:text-amber-200 text-xs font-mono"
            title="New gifts have arrived since this page was loaded. Click to pull the latest leaderboard from the live summary table."
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            {pendingDelta.toLocaleString()} new gift
            {pendingDelta === 1 ? '' : 's'} · Refresh
          </button>
        )}
      </div>

      {/* Results: empty / error / list. */}
      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 px-4 py-6 text-center text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      ) : loading && items.length === 0 ? (
        <div className="rounded-lg border border-gray-200 px-4 py-10 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
          Loading common gifters…
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-gray-200 px-4 py-10 text-center">
          <Users className="w-8 h-8 mx-auto mb-2 text-gray-300 dark:text-gray-100/40" />
          <p className="text-sm text-gray-700 dark:text-gray-300 font-medium">
            No bridging gifters yet
          </p>
          <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
            {debouncedQ
              ? `Nobody matching "${debouncedQ}" has gifted to ${minHosts}+ tracked creators.`
              : `Once a viewer gifts to at least ${minHosts} of your tracked creators, they'll show up here.`}
          </p>
        </div>
      ) : (
        <ul className="rounded-lg border border-gray-200 overflow-hidden divide-y divide-gray-200 dark:divide-gray-100/40 [&>li:nth-child(even)]:bg-gray-50/60 dark:[&>li:nth-child(even)]:bg-gray-100/[0.04]">
          {items.map((row) => (
            <CommonGifterRow
              key={row.user_id ?? row.unique_id ?? Math.random()}
              row={row}
              onSelect={() => setSelected(row)}
            />
          ))}
        </ul>
      )}

      <Suspense fallback={null}>
        {selected !== null && (
          <TikTokGifterDetailModal
            isOpen
            userId={selected.user_id ?? null}
            nickname={selected.nickname ?? null}
            uniqueId={selected.unique_id ?? null}
            avatarUrl={selected.avatar_url ?? null}
            isEnigma={selected.is_enigma}
            onClose={() => setSelected(null)}
            defaultTab="profile"
          />
        )}
      </Suspense>

      {/* Pagination footer — only when there's something to page. */}
      {items.length > 0 && (
        <div className="flex items-center justify-between gap-2 text-xs font-mono text-gray-500">
          <span>
            {showingFrom}–{showingTo} of {total.toLocaleString()}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={offset === 0 || loading}
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              className="inline-flex items-center px-2 py-1 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-gray-100/30"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <span className="px-2">
              Page {currentPage} / {totalPages}
            </span>
            <button
              type="button"
              disabled={offset + pageSize >= total || loading}
              onClick={() => setOffset(offset + pageSize)}
              className="inline-flex items-center px-2 py-1 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-gray-100/30"
              aria-label="Next page"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CommonGifterRow({
  row,
  onSelect,
}: {
  row: TikTokCommonGifter;
  onSelect: () => void;
}) {
  const display = row.nickname || row.unique_id || `user ${row.user_id ?? '?'}`;
  // Visible host pills cap so the row doesn't wrap insanely on
  // someone who's gifted to 20+ creators. The full list is in the
  // hover tooltip, and "+N more" leads the eye to the count.
  const VISIBLE_HOSTS = 6;
  const visibleHosts = useMemo(() => row.hosts.slice(0, VISIBLE_HOSTS), [row.hosts]);
  const overflow = row.hosts.length - visibleHosts.length;

  return (
    <li className="p-3 hover:bg-gray-50 dark:hover:bg-gray-100/10 transition-colors">
      <div className="flex items-start gap-3">
        {/* Identity + totals = clickable trigger for the deep-analysis
            modal. Host pills below are independent links and live
            outside this trigger so they don't double-fire. */}
        <button
          type="button"
          onClick={onSelect}
          className="flex-1 flex items-start gap-3 text-left min-w-0 group"
          aria-label="Open deep analysis"
        >
          <SafeAvatar
            src={row.avatar_url}
            size={40}
            className="ring-2 ring-gray-100 group-hover:ring-primary-200 transition-shadow shrink-0"
            fallback={
              <span className="font-mono text-sm text-gray-500">
                {(display[0] || '?').toUpperCase()}
              </span>
            }
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="font-medium text-gray-900 group-hover:text-primary-700 truncate">
                {display}
              </span>
              {row.unique_id && row.unique_id !== display && (
                <span className="text-xs font-mono text-gray-500 truncate">
                  @{row.unique_id}
                </span>
              )}
              <span
                className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-300 text-[10px] font-mono shrink-0"
                title={`Active across ${row.host_count} tracked creators`}
              >
                <Users className="w-3 h-3" />
                {row.host_count} hosts
              </span>
            </div>
            <div className="mt-0.5 flex items-center gap-3 flex-wrap text-xs font-mono text-gray-600">
              <span className="text-amber-700 dark:text-amber-300 tabular-nums">
                💎 {compactCount(row.diamonds)}
              </span>
              <span className="text-gray-500 tabular-nums">
                {compactCount(row.gifts)} gifts
              </span>
              {/* Hover hint — desktop only. The pixel-tight chevron
                  shows up on hover so the row visually telegraphs
                  that it opens a modal. Hidden on touch devices
                  since hover semantics aren't reliable there. */}
              <span className="hidden sm:inline ml-auto text-[10px] text-primary-600 dark:text-primary-300 opacity-0 group-hover:opacity-100 transition-opacity">
                Click for deep analysis →
              </span>
            </div>
          </div>
        </button>
      </div>
      {/* Per-host pills: independent links into each creator's live
          detail page. Sit below the clickable identity row so a click
          on a pill never opens the modal. The left-padding aligns
          them under the identity column (avatar 40px + gap 12px). */}
      <div className="mt-2 flex items-center gap-1.5 flex-wrap pl-[52px]">
        {visibleHosts.map((h) => (
          <Link
            key={h.host}
            to="/tiktok/$handle"
            params={{ handle: h.host }}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded font-mono text-[10px] border border-gray-200 hover:bg-gray-100 hover:border-primary-300 dark:hover:bg-gray-100/20 transition-colors"
            title={`@${h.host} · ${h.diamonds.toLocaleString()} 💎 · ${h.gifts.toLocaleString()} gifts`}
          >
            <span className="text-gray-700 dark:text-gray-300">@{h.host}</span>
            <span className="text-amber-700 dark:text-amber-300 tabular-nums">
              {compactCount(h.diamonds)}
            </span>
          </Link>
        ))}
        {overflow > 0 && (
          <span
            className="px-2 py-0.5 rounded font-mono text-[10px] text-gray-500 border border-dashed border-gray-200"
            title={row.hosts
              .slice(VISIBLE_HOSTS)
              .map((h) => `@${h.host} (${h.diamonds.toLocaleString()}💎)`)
              .join('\n')}
          >
            +{overflow} more
          </span>
        )}
      </div>
    </li>
  );
}

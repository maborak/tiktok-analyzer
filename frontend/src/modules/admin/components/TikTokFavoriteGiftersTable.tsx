/**
 * Favourites tab on /admin/tiktok.
 *
 * Lists the admin-curated favourite gifters (joined with summary
 * totals, same row shape as Common Gifters). Click a row → opens the
 * deep-analysis modal where the Favourite toggle lives. The modal's
 * Add/Remove fires `tiktok:favorites-changed` on `window`; we listen
 * here so the list refreshes without polling.
 *
 * Empty state explains how to add: "Click any gifter and use Add to
 * Favourites." — first-run discoverability.
 */

import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from '@tanstack/react-router';
import toast from 'react-hot-toast';
import { ChevronLeft, ChevronRight, Gift, Loader2, MessageSquare, RefreshCw, Search, Star, UserPlus, Users, X } from 'lucide-react';

import {
  type TikTokCommonGifter,
  type TikTokWsEvent,
  openTikTokWebSocket,
  tiktokApi,
} from '@admin/services/tiktok';
import { SafeAvatar } from '@admin/components/SafeAvatar';
// Lazy — see TikTokCommonGiftersTable for the same pattern. Keeps
// the echarts-heavy modal out of the lives-page first-paint bundle.
const TikTokGifterDetailModal = lazy(() =>
  import('@admin/components/TikTokGifterDetailModal')
    .then((m) => ({ default: m.TikTokGifterDetailModal })),
);

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 25;

function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}

interface FavoriteRow extends TikTokCommonGifter {
  note: string | null;
  added_at: string | null;
  notify_gift: boolean;
  notify_comment: boolean;
  notify_join: boolean;
}

interface Props {
  refreshKey?: number;
}

export function TikTokFavoriteGiftersTable({ refreshKey = 0 }: Props) {
  const [items, setItems] = useState<FavoriteRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<FavoriteRow | null>(null);
  const [pendingDelta, setPendingDelta] = useState(0);
  const [manualRefreshTick, setManualRefreshTick] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    setOffset(0);
  }, [debouncedQ, pageSize, refreshKey]);

  // Listen for favourite mutations from the detail modal — keeps the
  // list fresh without polling.
  useEffect(() => {
    const onChanged = () => setManualRefreshTick((n) => n + 1);
    window.addEventListener('tiktok:favorites-changed', onChanged);
    return () => window.removeEventListener('tiktok:favorites-changed', onChanged);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    tiktokApi
      .listFavoriteGifters({
        q: debouncedQ || undefined,
        limit: pageSize,
        offset,
      })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
        setPendingDelta(0);
      })
      .catch((e) => {
        if (cancelled) return;
        setError((e as Error).message || 'Failed to load favourites');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQ, offset, pageSize, refreshKey, manualRefreshTick]);

  // WS gift-delta — only counts gifts from a favourite user_id. Same
  // pattern as the Common Gifters tab so the "(N new) Refresh" chip
  // is consistent across the page.
  const favoriteIdSet = useMemo(
    () => new Set(items.map((r) => r.user_id ?? '').filter(Boolean) as string[]),
    [items],
  );
  const favoriteIdSetRef = useRef<Set<string>>(favoriteIdSet);
  useEffect(() => {
    favoriteIdSetRef.current = favoriteIdSet;
  }, [favoriteIdSet]);
  useEffect(() => {
    const ws = openTikTokWebSocket(
      (msg: TikTokWsEvent) => {
        if (msg.type !== 'gift') return;
        if (!msg.user_id) return;
        if (!favoriteIdSetRef.current.has(String(msg.user_id))) return;
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
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search favourites by nickname or @unique_id"
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
            title="A favourite gifter just sent a gift. Click to pull updated totals."
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            {pendingDelta} new gift{pendingDelta === 1 ? '' : 's'} · Refresh
          </button>
        )}
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 px-4 py-6 text-center text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      ) : loading && items.length === 0 ? (
        <div className="rounded-lg border border-gray-200 px-4 py-10 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
          Loading favourites…
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-gray-200 px-4 py-10 text-center">
          <Star className="w-8 h-8 mx-auto mb-2 text-gray-300 dark:text-gray-100/40" />
          <p className="text-sm text-gray-700 dark:text-gray-300 font-medium">
            No favourites yet
          </p>
          <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
            {debouncedQ
              ? `No favourites match "${debouncedQ}".`
              : 'Click any gifter (in Common, Global, or a creator\'s Top Gifters list) and use the "Add to Favourites" button. They\'ll show up here, and a live alert will fire whenever they gift in any tracked broadcast.'}
          </p>
        </div>
      ) : (
        <ul className="rounded-lg border border-gray-200 overflow-hidden divide-y divide-gray-200 dark:divide-gray-100/40 [&>li:nth-child(even)]:bg-gray-50/60 dark:[&>li:nth-child(even)]:bg-gray-100/[0.04]">
          {items.map((row) => (
            <FavoriteRowItem
              key={row.user_id ?? row.unique_id ?? Math.random()}
              row={row}
              onSelect={() => setSelected(row)}
              onToggleNotify={async (key, next) => {
                if (!row.user_id) return;
                // Optimistic: update local state immediately so the
                // checkbox flips without waiting for the round-trip.
                setItems((prev) =>
                  prev.map((r) =>
                    r.user_id === row.user_id ? { ...r, [key]: next } : r,
                  ),
                );
                try {
                  await tiktokApi.updateFavoriteGifter(row.user_id, {
                    [key]: next,
                  } as Record<string, boolean>);
                  // Tell the page-level watcher (and any other live
                  // listener) the notify config changed.
                  window.dispatchEvent(new CustomEvent('tiktok:favorites-changed'));
                } catch (e) {
                  // Roll back on failure.
                  setItems((prev) =>
                    prev.map((r) =>
                      r.user_id === row.user_id ? { ...r, [key]: !next } : r,
                    ),
                  );
                  toast.error((e as Error).message || 'Failed to update notification');
                }
              }}
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
            onClose={() => setSelected(null)}
            defaultTab="profile"
          />
        )}
      </Suspense>

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

function FavoriteRowItem({
  row,
  onSelect,
  onToggleNotify,
}: {
  row: FavoriteRow;
  onSelect: () => void;
  onToggleNotify: (
    key: 'notify_gift' | 'notify_comment' | 'notify_join',
    next: boolean,
  ) => void;
}) {
  const display = row.nickname || row.unique_id || `user ${row.user_id ?? '?'}`;
  const VISIBLE_HOSTS = 6;
  const visibleHosts = useMemo(() => row.hosts.slice(0, VISIBLE_HOSTS), [row.hosts]);
  const overflow = row.hosts.length - visibleHosts.length;

  return (
    <li className="p-3 hover:bg-gray-50 dark:hover:bg-gray-100/10 transition-colors">
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={onSelect}
          className="flex-1 flex items-start gap-3 text-left min-w-0 group"
          aria-label="Open deep analysis"
        >
          <SafeAvatar
            src={row.avatar_url}
            size={40}
            className="ring-2 ring-amber-100 group-hover:ring-amber-300 transition-shadow shrink-0"
            fallback={
              <span className="font-mono text-sm text-amber-600">
                {(display[0] || '?').toUpperCase()}
              </span>
            }
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2 flex-wrap">
              <Star className="w-3.5 h-3.5 text-amber-500 fill-amber-400 shrink-0" />
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
            <div className="mt-0.5 flex items-center gap-3 text-xs font-mono text-gray-600">
              <span className="text-amber-700 dark:text-amber-300 tabular-nums">
                💎 {compactCount(row.diamonds)}
              </span>
              <span className="text-gray-500 tabular-nums">
                {compactCount(row.gifts)} gifts
              </span>
              {row.note && (
                <span className="text-gray-500 italic truncate">“{row.note}”</span>
              )}
              <span className="hidden sm:inline ml-auto text-[10px] text-primary-600 dark:text-primary-300 opacity-0 group-hover:opacity-100 transition-opacity">
                Click for deep analysis →
              </span>
            </div>
          </div>
        </button>
      </div>
      {/* Notification toggles — per favourite, per event type. On
          mobile they wrap into multiple lines; on desktop they sit
          on a single row. Indented to line up with the identity
          column above. */}
      <div className="mt-2 flex items-center gap-x-3 gap-y-1 flex-wrap text-[11px] font-mono text-gray-600 pl-[52px]">
        <span className="text-[10px] uppercase tracking-wider text-gray-500">
          Alert on:
        </span>
        <NotifyToggle
          icon={<Gift className="w-3 h-3 text-amber-500" />}
          label="Gifts"
          checked={row.notify_gift}
          onChange={(v) => onToggleNotify('notify_gift', v)}
        />
        <NotifyToggle
          icon={<MessageSquare className="w-3 h-3 text-sky-500" />}
          label="Comments"
          checked={row.notify_comment}
          onChange={(v) => onToggleNotify('notify_comment', v)}
        />
        <NotifyToggle
          icon={<UserPlus className="w-3 h-3 text-emerald-500" />}
          label="Joins"
          checked={row.notify_join}
          onChange={(v) => onToggleNotify('notify_join', v)}
        />
      </div>

      {visibleHosts.length > 0 && (
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
      )}
    </li>
  );
}

function NotifyToggle({
  icon,
  label,
  checked,
  onChange,
}: {
  icon: React.ReactNode;
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-1 cursor-pointer select-none">
      <input
        type="checkbox"
        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {icon}
      <span className={checked ? 'text-gray-800 dark:text-gray-200' : 'text-gray-400'}>
        {label}
      </span>
    </label>
  );
}

/**
 * /admin/tiktok/enigmas — ledger of every viewer flagged `is_enigma=TRUE`.
 *
 * One row per user_id (NOT per Enigma alias — the aliases are the
 * masks; the row is the real person beneath them). Shows the real
 * name when we've deanonymised them and "Not captured yet" when we
 * only have the placeholder. Click a row → opens the same gifter
 * detail modal used everywhere else.
 *
 * Filters:
 *   - search   (substring on nickname / @handle / any alias)
 *   - status   (ALL / DISCOVERED / NOT CAPTURED)
 *   - sort     (last seen / first seen / most aliases)
 *
 * Pagination is server-side via limit+offset.
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Loader2, VenetianMask, Search, X } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { tiktokApi } from '@admin/services/tiktok';
import type { TikTokEnigmaViewer } from '@admin/services/tiktok';
import { SafeAvatar } from '@admin/components/SafeAvatar';

const TikTokGifterDetailModal = lazy(() =>
  import('@admin/components/TikTokGifterDetailModal').then((m) => ({
    default: m.TikTokGifterDetailModal,
  })),
);

const POLL_MS = 60_000;
const PAGE_SIZE = 25;

type Status = 'all' | 'discovered' | 'not_captured';
type Sort = 'last_seen' | 'first_seen' | 'aliases';

export function TikTokEnigmas() {
  const [items, setItems] = useState<TikTokEnigmaViewer[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<Status>('all');
  const [sort, setSort] = useState<Sort>('last_seen');
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<TikTokEnigmaViewer | null>(null);

  const refresh = useCallback(async () => {
    setErr(null);
    try {
      const data = await tiktokApi.listEnigmas({
        q: q || undefined,
        status,
        sort,
        limit: PAGE_SIZE,
        offset,
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'failed to load Enigma ledger');
    } finally {
      setLoading(false);
    }
  }, [q, status, sort, offset]);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  // Reset to page 0 when filters change so the user doesn't land
  // on an empty page after narrowing the result set.
  useEffect(() => {
    setOffset(0);
  }, [q, status, sort]);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  const counts = useMemo(() => {
    // Server provides the global `total`; for the filter chips we
    // surface that plus the running cohort breakdown derived from
    // the current page. A future enhancement could ship per-status
    // totals on the response so the chip count is always accurate.
    return { total };
  }, [total]);

  return (
    <PageShell>
      <PageHeader
        title="Enigmas"
        icon={<VenetianMask className="w-5 h-5" />}
        description={
          'Every viewer ever observed gifting under TikTok\'s anonymous (Enigma) mode. '
          + 'Real identity preserved when we\'ve seen the user under their real name in any tracked room; '
          + 'otherwise "Not captured yet" until we do.'
        }
      />

      {/* Filter strip */}
      <div className="card p-3 flex flex-wrap items-center gap-3 text-xs">
        {/* Search */}
        <div className="relative flex-1 min-w-[16rem] focus-within:ring-2 focus-within:ring-primary-500/30 rounded-md border border-gray-200 bg-white dark:bg-white/5">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by nickname, @handle, or any Enigma alias…"
            className="w-full pl-8 pr-8 py-2 rounded-md bg-transparent text-sm font-mono placeholder:text-gray-500 focus:outline-none"
          />
          {q && (
            <button
              type="button"
              onClick={() => setQ('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
              aria-label="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Status filter */}
        <div className="flex items-center gap-1.5 shrink-0">
          {(['all', 'discovered', 'not_captured'] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`px-3 py-1.5 rounded-full font-mono text-[10px] uppercase tracking-wider transition-colors ${
                status === s
                  ? 'bg-primary-100 text-primary-700 dark:bg-primary-500/20 dark:text-primary-300'
                  : 'bg-white text-gray-600 border border-gray-200 hover:border-gray-300 dark:bg-white/5'
              }`}
            >
              {s === 'all' ? 'All' : s === 'discovered' ? 'Discovered' : 'Not captured'}
            </button>
          ))}
        </div>

        {/* Sort selector */}
        <div className="flex items-center gap-1.5 shrink-0 text-[11px] font-mono text-gray-500">
          <span>Sort:</span>
          {(
            [
              { id: 'last_seen', label: 'Last seen' },
              { id: 'first_seen', label: 'First seen' },
              { id: 'aliases', label: 'Most masks' },
            ] as { id: Sort; label: string }[]
          ).map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => setSort(opt.id)}
              className={`px-2 py-0.5 rounded-full border transition-colors ${
                sort === opt.id
                  ? 'bg-primary-100 dark:bg-primary-500/20 border-primary-300 text-primary-700 dark:text-primary-300'
                  : 'bg-white dark:bg-white/5 border-gray-200 hover:border-gray-300'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Result count + page indicator */}
      <div className="flex items-center justify-between text-xs text-gray-500 font-mono">
        <span>
          {loading && items.length === 0 ? 'Loading…' : `${counts.total.toLocaleString()} total`}
        </span>
        {total > 0 && (
          <span>
            Page {page} of {pageCount}
          </span>
        )}
      </div>

      {err && (
        <div className="rounded-md border border-rose-200 bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-300 px-3 py-2 text-sm">
          {err}
        </div>
      )}

      {/* Rows */}
      {loading && items.length === 0 ? (
        <div className="card p-10 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
          Loading Enigma ledger…
        </div>
      ) : items.length === 0 ? (
        <div className="card p-10 text-center text-sm text-gray-500">
          No Enigma viewers match.
        </div>
      ) : (
        <ul className="card p-0 overflow-hidden divide-y divide-gray-100 dark:divide-white/[0.04]">
          {items.map((v) => (
            <EnigmaRow key={v.user_id} v={v} onClick={() => setSelected(v)} />
          ))}
        </ul>
      )}

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="secondary"
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={!hasPrev || loading}
          >
            <ChevronLeft className="w-4 h-4 mr-1" />
            Prev
          </Button>
          <Button
            variant="secondary"
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={!hasNext || loading}
          >
            Next
            <ChevronRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      )}

      <Suspense fallback={null}>
        {selected && (
          <TikTokGifterDetailModal
            isOpen
            userId={selected.user_id}
            uniqueId={selected.discovered ? selected.unique_id : null}
            nickname={selected.discovered ? selected.nickname : null}
            avatarUrl={selected.avatar_url}
            isEnigma={true}
            onClose={() => setSelected(null)}
            defaultTab="profile"
          />
        )}
      </Suspense>
    </PageShell>
  );
}

function EnigmaRow({
  v,
  onClick,
}: {
  v: TikTokEnigmaViewer;
  onClick: () => void;
}) {
  const displayName = v.discovered ? (v.nickname || v.unique_id || '—') : 'Not captured yet';
  const handle = v.discovered ? v.unique_id : null;
  const aliasCount = v.enigma_aliases.length;
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="w-full text-left flex items-start gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-white/[0.03] transition-colors"
      >
        <SafeAvatar
          src={v.discovered ? v.avatar_url : null}
          size={40}
          className="shrink-0"
          fallback={
            <span
              className="font-mono text-xs text-violet-700 dark:text-violet-300"
              title="Identity not captured yet"
            >
              ?
            </span>
          }
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`font-medium truncate ${
                v.discovered
                  ? 'text-gray-900'
                  : 'text-gray-500 italic'
              }`}
            >
              {displayName}
            </span>
            {handle && (
              <span className="text-xs font-mono text-gray-500 truncate">@{handle}</span>
            )}
            {!v.discovered && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full font-mono text-[9px] uppercase tracking-wider bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">
                pending
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[11px] font-mono text-gray-500 truncate">
            user_id: {v.user_id}
          </div>
          {/* Alias pills — truncated, full set in title attribute. */}
          {aliasCount > 0 && (
            <div
              className="mt-1.5 flex items-center gap-1 flex-wrap text-[10px] font-mono"
              title={v.enigma_aliases.join(', ')}
            >
              <span className="text-gray-500">
                Seen as ({aliasCount}):
              </span>
              {v.enigma_aliases.slice(0, 6).map((alias) => (
                <span
                  key={alias}
                  className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-700 ring-1 ring-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-500/30"
                >
                  {alias}
                </span>
              ))}
              {aliasCount > 6 && (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 ring-1 ring-violet-300 dark:bg-violet-500/20 dark:text-violet-200 dark:ring-violet-500/40">
                  +{aliasCount - 6} more
                </span>
              )}
            </div>
          )}
        </div>
        <div className="shrink-0 text-right text-[10px] font-mono text-gray-500 leading-tight">
          {v.last_seen_at && (
            <div title={`Last event: ${v.last_seen_at}`}>
              last {fmtRelTime(v.last_seen_at)}
            </div>
          )}
          {v.first_seen_at && (
            <div title={`First event: ${v.first_seen_at}`}>
              first {fmtRelTime(v.first_seen_at)}
            </div>
          )}
        </div>
      </button>
    </li>
  );
}

function fmtRelTime(iso: string): string {
  const d = new Date(iso);
  const diffSec = (Date.now() - d.getTime()) / 1000;
  if (diffSec < 60) return `${Math.floor(diffSec)}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 86400 * 30) return `${Math.floor(diffSec / 86400)}d ago`;
  return d.toLocaleDateString();
}

export default TikTokEnigmas;

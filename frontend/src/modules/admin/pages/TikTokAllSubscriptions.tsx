/**
 * TikTokAllSubscriptions — admin god-view datatable of every user's
 * monitored TikTok handles.
 *
 * Lives at `/admin/tiktok/all-subscriptions`. Distinct from
 * `/admin/tiktok` (which is the admin's OWN dashboard slice). This
 * one surfaces every row across every owner so the operator can:
 *
 *   - Search across handle / nickname / owner email.
 *   - Filter by public-opt-in, enabled state.
 *   - Sort by added_at, owner_email, follower_count.
 *   - Toggle "Make Public" per-row (the admin-only action that was
 *     previously sprinkled across user-facing surfaces — now lives
 *     here for clarity).
 *
 * Per the P5 cache audit, every row's data is per-handle, so the
 * existing service-level caches are reused without per-user-scoped
 * keys — the admin route layer is the auth gate.
 */

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from '@tanstack/react-router';
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Filter,
  RefreshCw,
  Search,
  Tv,
  Users,
} from 'lucide-react';
import toast from 'react-hot-toast';

import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { LoadingState } from '@/components/ui/LoadingState';
import { EmptyState } from '@/components/ui/EmptyState';
import {
  tiktokApi,
  type AdminAllSubscriptionsRow,
} from '../services/tiktok';

type SortKey = 'unique_id' | 'added_at' | 'owner_email' | 'follower_count';
type TristateFilter = 'all' | 'yes' | 'no';

function formatCount(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      dateStyle: 'medium',
    });
  } catch {
    return iso;
  }
}

function triToParam(t: TristateFilter): boolean | null {
  if (t === 'yes') return true;
  if (t === 'no') return false;
  return null;
}

export function TikTokAllSubscriptions() {
  const navigate = useNavigate();

  const [rows, setRows] = useState<AdminAllSubscriptionsRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [pubBusy, setPubBusy] = useState<string | null>(null);

  // Filters
  const [q, setQ] = useState('');
  const [searchActive, setSearchActive] = useState(''); // applied filter
  const [publicFilter, setPublicFilter] = useState<TristateFilter>('all');
  const [enabledFilter, setEnabledFilter] = useState<TristateFilter>('all');
  const [sort, setSort] = useState<SortKey>('unique_id');

  // Paging
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);

  const fetchPage = useCallback(async () => {
    setLoading(true);
    try {
      const res = await tiktokApi.listAllSubscriptions({
        q: searchActive || null,
        is_public: triToParam(publicFilter),
        enabled: triToParam(enabledFilter),
        sort,
        limit,
        offset,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (err) {
      console.error('Failed to load all subscriptions', err);
      toast.error('Could not load the all-subscriptions list.');
    } finally {
      setLoading(false);
    }
  }, [searchActive, publicFilter, enabledFilter, sort, limit, offset]);

  useEffect(() => {
    fetchPage();
  }, [fetchPage]);

  const applySearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearchActive(q.trim());
    setOffset(0);
  };

  const togglePublic = async (row: AdminAllSubscriptionsRow) => {
    setPubBusy(row.unique_id);
    try {
      await tiktokApi.setLivePublic(row.unique_id, !row.is_public);
      // Optimistic local flip — fetchPage will eventually reconcile.
      setRows((prev) =>
        prev.map((r) =>
          r.unique_id === row.unique_id
            ? { ...r, is_public: !row.is_public }
            : r,
        ),
      );
      toast.success(
        `@${row.unique_id} is now ${!row.is_public ? 'public' : 'private'}.`,
      );
    } catch {
      toast.error(`Could not flip public state for @${row.unique_id}.`);
    } finally {
      setPubBusy(null);
    }
  };

  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + rows.length, total);
  const pageCount = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.floor(offset / limit) + 1;
  const filterSummary = useMemo(() => {
    const parts: string[] = [];
    if (searchActive) parts.push(`"${searchActive}"`);
    if (publicFilter !== 'all')
      parts.push(`public=${publicFilter === 'yes' ? 'true' : 'false'}`);
    if (enabledFilter !== 'all')
      parts.push(`enabled=${enabledFilter === 'yes' ? 'true' : 'false'}`);
    return parts.length ? `filtered by ${parts.join(', ')}` : 'no filters';
  }, [searchActive, publicFilter, enabledFilter]);

  return (
    <PageShell>
      <PageHeader
        title="All Subscriptions"
        icon={<Tv className="w-5 h-5" />}
        description={`Every TikTok monitor on the install across all users (${filterSummary}).`}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchPage}
              disabled={loading}
              title="Refresh"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate({ to: '/admin/tiktok' })}
            >
              Back to my dashboard
            </Button>
          </div>
        }
      />

      {/* Filter strip */}
      <form
        onSubmit={applySearch}
        className="card mb-4 p-3 flex flex-wrap items-center gap-3"
      >
        <div className="flex-1 min-w-[240px] flex items-center gap-2">
          <Search className="h-4 w-4 text-gray-400 flex-shrink-0" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search handle, nickname, or owner email"
            autoComplete="off"
            spellCheck={false}
            className="flex-1"
          />
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="auth-mono-label text-[10px]">public</span>
          <select
            value={publicFilter}
            onChange={(e) => {
              setPublicFilter(e.target.value as TristateFilter);
              setOffset(0);
            }}
            className="border border-gray-200 rounded px-2 py-1 bg-white"
          >
            <option value="all">all</option>
            <option value="yes">yes</option>
            <option value="no">no</option>
          </select>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="auth-mono-label text-[10px]">enabled</span>
          <select
            value={enabledFilter}
            onChange={(e) => {
              setEnabledFilter(e.target.value as TristateFilter);
              setOffset(0);
            }}
            className="border border-gray-200 rounded px-2 py-1 bg-white"
          >
            <option value="all">all</option>
            <option value="yes">yes</option>
            <option value="no">no</option>
          </select>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="auth-mono-label text-[10px]">sort</span>
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as SortKey);
              setOffset(0);
            }}
            className="border border-gray-200 rounded px-2 py-1 bg-white"
          >
            <option value="unique_id">handle (A→Z)</option>
            <option value="added_at">added (newest)</option>
            <option value="owner_email">owner</option>
            <option value="follower_count">followers</option>
          </select>
        </div>

        <Button type="submit" size="sm">
          <Filter className="h-4 w-4 mr-1" /> Apply
        </Button>
      </form>

      {loading && rows.length === 0 ? (
        <LoadingState message="Loading subscriptions..." />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Tv className="w-12 h-12 text-gray-300" />}
          title="No subscriptions match"
          description="Clear the search/filters or check that any user has actually added a monitor."
        />
      ) : (
        <div className="card overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="auth-mono-label text-left p-3">handle</th>
                <th className="auth-mono-label text-left p-3">owner</th>
                <th className="auth-mono-label text-left p-3">added</th>
                <th className="auth-mono-label text-right p-3">followers</th>
                <th className="auth-mono-label text-center p-3">enabled</th>
                <th className="auth-mono-label text-center p-3">public</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.unique_id}
                  className="border-t border-gray-100 hover:bg-gray-50"
                >
                  <td className="p-3">
                    <div className="flex items-center gap-2">
                      {r.avatar_url ? (
                        <img
                          src={r.avatar_url}
                          alt={r.nickname ?? r.unique_id}
                          className="h-7 w-7 rounded-full object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <div className="h-7 w-7 rounded-full bg-gray-100" />
                      )}
                      <div className="min-w-0">
                        <div className="font-medium text-gray-900 truncate">
                          {r.nickname ?? r.unique_id}
                        </div>
                        <div className="font-mono text-[11px] text-gray-500 truncate">
                          @{r.unique_id}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="p-3 font-mono text-[12px] text-gray-700">
                    {r.owner_email ?? <span className="text-gray-400">—</span>}
                  </td>
                  <td className="p-3 font-mono text-[12px] text-gray-600">
                    {formatDate(r.added_at)}
                  </td>
                  <td className="p-3 font-mono text-right text-gray-700">
                    <span className="inline-flex items-center gap-1">
                      <Users className="h-3 w-3 text-gray-400" />
                      {formatCount(r.follower_count)}
                    </span>
                  </td>
                  <td className="p-3 text-center">
                    {r.enabled ? (
                      <span className="auth-mono-label text-[10px]">on</span>
                    ) : (
                      <span className="text-[10px] text-gray-400 font-mono">
                        off
                      </span>
                    )}
                  </td>
                  <td className="p-3 text-center">
                    <button
                      type="button"
                      onClick={() => togglePublic(r)}
                      disabled={pubBusy === r.unique_id}
                      title={
                        r.is_public
                          ? 'Currently public — click to make private'
                          : 'Currently private — click to make public'
                      }
                      className={
                        'inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors ' +
                        (r.is_public
                          ? 'bg-amber-50 text-amber-900 hover:bg-amber-100 dark:bg-amber-500/10'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200')
                      }
                    >
                      {r.is_public ? (
                        <>
                          <Eye className="h-3 w-3" /> public
                        </>
                      ) : (
                        <>
                          <EyeOff className="h-3 w-3" /> private
                        </>
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {total > limit && (
        <div className="mt-4 flex items-center justify-between text-xs text-gray-600">
          <span className="font-mono">
            {showingFrom}–{showingTo} of {total}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setOffset(Math.max(0, offset - limit))}
              disabled={offset === 0 || loading}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="font-mono">
              page {currentPage} / {pageCount}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setOffset(offset + limit)}
              disabled={offset + limit >= total || loading}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
            <select
              value={limit}
              onChange={(e) => {
                setLimit(Number(e.target.value));
                setOffset(0);
              }}
              className="border border-gray-200 rounded px-2 py-1 bg-white"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        </div>
      )}
    </PageShell>
  );
}

export default TikTokAllSubscriptions;

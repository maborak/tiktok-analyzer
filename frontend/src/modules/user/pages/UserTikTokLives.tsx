/**
 * UserTikTokLives — user-facing TikTok monitor dashboard.
 *
 * Lives at `/tiktok` (NOT `/admin/tiktok`). Any authenticated user
 * with credits can land here, see their monitored handles, add new
 * ones (costs 1 credit), and remove existing ones (refunds within
 * 24 h of the original add).
 *
 * Shape intentionally mirrors the admin Lives page so the visual
 * vocabulary is consistent — same card grid, same status pills, same
 * follower-count formatting. Operator-only fields (worker assignment,
 * Make-Public toggle, listener controls) are absent here; they live
 * in `/admin/tiktok/all-subscriptions` for the operator.
 */

import { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { Activity, Plus, Trash2, RefreshCw, Tv, Users, Wallet } from 'lucide-react';
import toast from 'react-hot-toast';

import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { Button } from '@/components/ui/Button';
import { LoadingState } from '@/components/ui/LoadingState';
import { EmptyState } from '@/components/ui/EmptyState';
import { userTikTokApi, type UserTikTokSubscription } from '../services/tiktok';
import { UserTikTokAddMonitorModal } from '../components/UserTikTokAddMonitorModal';

/** Compact "12.3K" / "1.4M" formatter — the lives page in admin uses
 *  the same idiom; keeping it inline here so the user page has zero
 *  cross-module imports beyond UI primitives. */
function formatCount(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function UserTikTokLives() {
  const navigate = useNavigate();
  const [subs, setSubs] = useState<UserTikTokSubscription[]>([]);
  const [balance, setBalance] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  const refreshAll = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([
        userTikTokApi.listMyLives(),
        userTikTokApi.getCredits(),
      ]);
      setSubs(s);
      setBalance(c.balance);
    } catch (err) {
      console.error('Failed to load my monitors', err);
      toast.error('Could not load your monitors. Try refreshing.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const handleRemove = useCallback(
    async (handle: string) => {
      if (
        !window.confirm(
          `Remove monitor for @${handle}? If you added it within the last 24 h, the 1 credit will be refunded.`,
        )
      ) {
        return;
      }
      setRemoving(handle);
      try {
        const res = await userTikTokApi.removeMonitor(handle);
        toast.success(
          res.refunded
            ? `Removed @${handle} — 1 credit refunded.`
            : `Removed @${handle}.`,
        );
        await refreshAll();
      } catch (err) {
        console.error('Failed to remove monitor', err);
        toast.error('Could not remove monitor. Try again.');
      } finally {
        setRemoving(null);
      }
    },
    [refreshAll],
  );

  const handleAdded = useCallback(() => {
    setAddOpen(false);
    refreshAll();
  }, [refreshAll]);

  const sortedSubs = useMemo(
    () =>
      [...subs].sort((a, b) => {
        // Live ones first, then by follower count, then by handle.
        if (a.is_live && !b.is_live) return -1;
        if (!a.is_live && b.is_live) return 1;
        const fa = a.follower_count ?? 0;
        const fb = b.follower_count ?? 0;
        if (fa !== fb) return fb - fa;
        return a.unique_id.localeCompare(b.unique_id);
      }),
    [subs],
  );

  const insufficientForAdd = balance != null && balance < 1;

  return (
    <PageShell>
      <PageHeader
        title="My TikTok Monitors"
        icon={<Tv className="w-5 h-5" />}
        description={
          subs.length === 0
            ? 'Track TikTok lives you care about. Each monitor costs 1 credit (refundable within 24 h of adding).'
            : `${subs.length} monitor${subs.length === 1 ? '' : 's'}.`
        }
        actions={
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5">
              <Wallet className="h-4 w-4 text-gray-500" aria-hidden />
              <span className="auth-mono-label text-[10px]">credits</span>
              <span className="font-mono text-sm font-semibold text-gray-900">
                {balance ?? '—'}
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={refreshAll}
              disabled={loading}
              title="Refresh list"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button
              onClick={() => setAddOpen(true)}
              disabled={insufficientForAdd}
              title={
                insufficientForAdd
                  ? 'You need at least 1 credit to add a monitor.'
                  : 'Add a TikTok handle to monitor (1 credit)'
              }
            >
              <Plus className="h-4 w-4 mr-1" /> Add monitor
            </Button>
          </div>
        }
      />

      {loading ? (
        <LoadingState message="Loading your monitors..." />
      ) : sortedSubs.length === 0 ? (
        <EmptyState
          icon={<Tv className="w-12 h-12 text-gray-300" />}
          title="No monitors yet"
          description="Add a TikTok handle to start tracking their lives, gifters, and PK battles. Each monitor costs 1 credit — refundable within 24 h."
          action={
            <Button
              onClick={() => setAddOpen(true)}
              disabled={insufficientForAdd}
            >
              <Plus className="h-4 w-4 mr-1" />
              {insufficientForAdd ? 'Need 1 credit to start' : 'Add your first monitor'}
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {sortedSubs.map((s) => (
            <button
              key={s.unique_id}
              type="button"
              onClick={() => navigate({ to: `/tiktok/${s.unique_id}` })}
              className="card text-left transition-all hover:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-400/40 p-4 flex gap-3 items-start"
            >
              {s.avatar_url ? (
                <img
                  src={s.avatar_url}
                  alt={s.nickname ?? s.unique_id}
                  className="h-12 w-12 rounded-full object-cover bg-gray-100"
                  loading="lazy"
                />
              ) : (
                <div className="h-12 w-12 rounded-full bg-gray-100 flex items-center justify-center">
                  <Tv className="h-5 w-5 text-gray-400" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="font-semibold text-gray-900 truncate">
                    {s.nickname ?? s.unique_id}
                  </span>
                  {s.is_live ? (
                    <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide text-rose-700 bg-rose-50 dark:bg-rose-500/10 px-1.5 py-0.5 rounded">
                      <Activity className="h-2.5 w-2.5" /> Live
                    </span>
                  ) : null}
                </div>
                <div className="font-mono text-xs text-gray-500 truncate">
                  @{s.unique_id}
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-600 mt-2">
                  <span className="inline-flex items-center gap-1">
                    <Users className="h-3 w-3" />
                    {formatCount(s.follower_count)}
                  </span>
                  {s.is_public ? (
                    <span className="auth-mono-label text-[10px]">public</span>
                  ) : null}
                </div>
              </div>
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  handleRemove(s.unique_id);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.stopPropagation();
                    handleRemove(s.unique_id);
                  }
                }}
                aria-label={`Remove monitor for ${s.unique_id}`}
                className="text-gray-400 hover:text-rose-600 transition-colors p-1 -m-1 rounded cursor-pointer"
                aria-disabled={removing === s.unique_id}
              >
                <Trash2 className="h-4 w-4" />
              </span>
            </button>
          ))}
        </div>
      )}

      {addOpen && (
        <UserTikTokAddMonitorModal
          balance={balance ?? 0}
          onClose={() => setAddOpen(false)}
          onAdded={handleAdded}
        />
      )}
    </PageShell>
  );
}

export default UserTikTokLives;

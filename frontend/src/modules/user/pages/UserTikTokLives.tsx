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
import {
  Activity, Plus, Trash2, RefreshCw, Tv, Users, Wallet,
  Eye, Gem,
} from 'lucide-react';
import toast from 'react-hot-toast';

import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { Button } from '@/components/ui/Button';
import { LoadingState } from '@/components/ui/LoadingState';
import { EmptyState } from '@/components/ui/EmptyState';
import { userTikTokApi } from '../services/tiktok';
import type { TikTokSubscription, TikTokLiveSummary } from '@admin';
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
  const [subs, setSubs] = useState<TikTokSubscription[]>([]);
  const [balance, setBalance] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  // Per-handle summary data from the bundle endpoint. Keyed by
  // lowercase handle so we can index into it from the card render.
  const [summary, setSummary] = useState<Record<string, TikTokLiveSummary>>({});

  const refreshAll = useCallback(async () => {
    try {
      // One bundle call (subs + summary) + credits in parallel.
      // The bundle endpoint is the user-scoped mirror of
      // /admin/tiktok/lives/bundle — same shape, ownership-filtered.
      const [bundle, c] = await Promise.all([
        userTikTokApi.getLivesBundle({
          tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
        userTikTokApi.getCredits(),
      ]);
      setSubs(bundle.subs);
      setSummary(bundle.summary ?? {});
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

  /** Authoritative live truth for a sub: prefer the summary's
   *  `active_room_id` (computed live by the backend bundle) over
   *  the sub's `is_live` flag, which can lag behind by a poll
   *  cycle. Mirrors the admin Lives page's heuristic.  */
  const isLiveFromSummary = useCallback(
    (sub: TikTokSubscription): boolean => {
      const slice = summary[sub.unique_id.toLowerCase()];
      if (!slice) return Boolean(sub.is_live);
      return (slice as { active_room_id?: unknown }).active_room_id != null;
    },
    [summary],
  );

  const sortedSubs = useMemo(
    () =>
      [...subs].sort((a, b) => {
        // Live ones first (using summary truth source), then by
        // follower count, then by handle.
        const al = isLiveFromSummary(a);
        const bl = isLiveFromSummary(b);
        if (al && !bl) return -1;
        if (!al && bl) return 1;
        const fa = a.follower_count ?? 0;
        const fb = b.follower_count ?? 0;
        if (fa !== fb) return fb - fa;
        return a.unique_id.localeCompare(b.unique_id);
      }),
    [subs, isLiveFromSummary],
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
          {sortedSubs.map((s) => {
            const slice = summary[s.unique_id.toLowerCase()] as
              | { viewer_count?: number; diamonds_session?: number }
              | undefined;
            const live = isLiveFromSummary(s);
            const viewers =
              slice && typeof slice.viewer_count === 'number'
                ? slice.viewer_count
                : null;
            const sessionDiamonds =
              slice && typeof slice.diamonds_session === 'number'
                ? slice.diamonds_session
                : null;
            return (
              <button
                key={s.unique_id}
                type="button"
                onClick={() => navigate({ to: `/tiktok/${s.unique_id}` })}
                className="card text-left transition-all hover:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-400/40 p-4 flex flex-col gap-3"
              >
                {/* Header row: avatar + identity + delete button */}
                <div className="flex gap-3 items-start">
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
                      {live ? (
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
                </div>

                {/* Live-only stat strip: viewer count + session diamonds.
                    Mirrors admin Lives' card scoreboard but trimmed to
                    the two numbers that matter to a regular operator. */}
                {live && (viewers != null || sessionDiamonds != null) ? (
                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-gray-100">
                    <div className="flex items-center gap-1.5 text-xs">
                      <Eye className="h-3 w-3 text-gray-400" />
                      <span className="font-mono font-semibold text-gray-900">
                        {viewers != null ? formatCount(viewers) : '—'}
                      </span>
                      <span className="auth-mono-label text-[9px]">viewers</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs">
                      <Gem className="h-3 w-3 text-amber-500" />
                      <span className="font-mono font-semibold text-gray-900">
                        {sessionDiamonds != null ? formatCount(sessionDiamonds) : '—'}
                      </span>
                      <span className="auth-mono-label text-[9px]">session</span>
                    </div>
                  </div>
                ) : null}
              </button>
            );
          })}
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

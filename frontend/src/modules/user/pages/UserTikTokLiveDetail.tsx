/**
 * UserTikTokLiveDetail — minimal per-handle detail view for the
 * user-facing monitoring product.
 *
 * Lives at `/tiktok/$handle`. Ownership-gated server-side: the user
 * gets a 404 if they query a handle they don't own. We surface that
 * as an empty/not-found state so the frontend doesn't crash.
 *
 * MVP feature scope (matches the backend endpoints from P3):
 *   - Profile header: avatar + handle + nickname + follower count.
 *   - Stats strip: added-at, current live status, room count.
 *   - Calendar strip: per-day broadcast counts for the past N weeks
 *     (compact, week-by-week — no heatmap colour-bucketing yet).
 *   - Rooms table: most recent N broadcasts.
 *
 * Operator-only surfaces (worker controls, public-toggle, listener
 * status, full PK detail) stay on the admin side — users get the
 * essentials and the credit-debit/refund loop.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from '@tanstack/react-router';
import { Activity, ArrowLeft, Calendar, Tv, Users, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';

import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { Button } from '@/components/ui/Button';
import { LoadingState } from '@/components/ui/LoadingState';
import { EmptyState } from '@/components/ui/EmptyState';
import {
  userTikTokApi,
  type UserTikTokSubscription,
} from '../services/tiktok';

interface CalendarDay {
  date: string;
  rooms: number;
  diamonds: number;
  duration_minutes: number;
  matches: number;
}

interface RoomRow {
  room_id: string | number;
  title?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  diamonds?: number | null;
  matches?: number | null;
  likes?: number | null;
}

function formatCount(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

export function UserTikTokLiveDetail() {
  const navigate = useNavigate();
  const { handle } = useParams({ strict: false }) as { handle?: string };
  const [sub, setSub] = useState<UserTikTokSubscription | null>(null);
  const [calendar, setCalendar] = useState<CalendarDay[]>([]);
  const [rooms, setRooms] = useState<RoomRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    if (!handle) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setNotFound(false);
      try {
        const detail = await userTikTokApi.getMyLive(handle);
        if (cancelled) return;
        setSub(detail.sub);
        // Fire calendar + rooms in parallel — neither blocks the
        // profile header rendering once `sub` is set.
        const [cal, rms] = await Promise.all([
          userTikTokApi
            .getMyLiveCalendar(handle, 12)
            .catch(() => [] as CalendarDay[]),
          userTikTokApi
            .getMyLiveRooms(handle, 25)
            .catch(() => [] as RoomRow[]),
        ]);
        if (cancelled) return;
        setCalendar(
          (cal as unknown as CalendarDay[] | { cells?: CalendarDay[] })
            ? Array.isArray(cal)
              ? (cal as CalendarDay[])
              : ((cal as { cells?: CalendarDay[] }).cells ?? [])
            : [],
        );
        setRooms(rms as RoomRow[]);
      } catch (err: any) {
        if (err?.response?.status === 404) {
          setNotFound(true);
        } else {
          console.error('Failed to load detail', err);
          toast.error('Could not load monitor detail.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [handle]);

  const handleRemove = async () => {
    if (!handle) return;
    if (
      !window.confirm(
        `Remove monitor for @${handle}? If you added it within the last 24 h, the 1 credit will be refunded.`,
      )
    ) {
      return;
    }
    setRemoving(true);
    try {
      const res = await userTikTokApi.removeMonitor(handle);
      toast.success(
        res.refunded
          ? `Removed @${handle} — 1 credit refunded.`
          : `Removed @${handle}.`,
      );
      navigate({ to: '/tiktok' });
    } catch {
      toast.error('Could not remove monitor.');
    } finally {
      setRemoving(false);
    }
  };

  // Bucket calendar days by ISO week-start for a compact strip.
  const calendarByWeek = useMemo(() => {
    const byWeek = new Map<string, CalendarDay[]>();
    for (const d of calendar) {
      // ISO week derived from the date string: Sunday-anchored
      // bucket is good enough for the strip; we're not rendering
      // a proper heatmap here.
      const date = new Date(d.date + 'T00:00:00Z');
      const week = `${date.getUTCFullYear()}-W${Math.ceil(
        (date.getUTCDate() + ((date.getUTCDay() + 6) % 7)) / 7,
      )}`;
      const arr = byWeek.get(week) ?? [];
      arr.push(d);
      byWeek.set(week, arr);
    }
    return Array.from(byWeek.entries())
      .map(([week, days]) => ({
        week,
        total_rooms: days.reduce((a, b) => a + (b.rooms ?? 0), 0),
        total_diamonds: days.reduce((a, b) => a + (b.diamonds ?? 0), 0),
      }))
      .slice(-12);
  }, [calendar]);

  if (!handle) {
    return (
      <PageShell>
        <EmptyState
          icon={<Tv className="w-12 h-12 text-gray-300" />}
          title="No handle in the URL"
          description="Open this page from /tiktok."
          action={
            <Button onClick={() => navigate({ to: '/tiktok' })}>
              <ArrowLeft className="h-4 w-4 mr-1" /> Back to monitors
            </Button>
          }
        />
      </PageShell>
    );
  }

  if (loading && !sub) return <LoadingState message={`Loading @${handle}...`} />;

  if (notFound || !sub) {
    return (
      <PageShell>
        <EmptyState
          icon={<Tv className="w-12 h-12 text-gray-300" />}
          title="Not in your monitors"
          description={`You don't have a monitor for @${handle}. Add one from your dashboard (1 credit).`}
          action={
            <Button onClick={() => navigate({ to: '/tiktok' })}>
              <ArrowLeft className="h-4 w-4 mr-1" /> Back to monitors
            </Button>
          }
        />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title={sub.nickname ?? `@${sub.unique_id}`}
        icon={<Tv className="w-5 h-5" />}
        description={`@${sub.unique_id}`}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate({ to: '/tiktok' })}
            >
              <ArrowLeft className="h-4 w-4 mr-1" /> Monitors
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRemove}
              disabled={removing}
              className="text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10"
            >
              {removing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                'Remove monitor'
              )}
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="card p-4 flex items-start gap-3">
          {sub.avatar_url ? (
            <img
              src={sub.avatar_url}
              alt={sub.nickname ?? sub.unique_id}
              className="h-14 w-14 rounded-full object-cover bg-gray-100"
            />
          ) : (
            <div className="h-14 w-14 rounded-full bg-gray-100 flex items-center justify-center">
              <Tv className="h-5 w-5 text-gray-400" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-semibold text-gray-900 truncate">
                {sub.nickname ?? sub.unique_id}
              </span>
              {sub.is_live ? (
                <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase text-rose-700 bg-rose-50 dark:bg-rose-500/10 px-1.5 py-0.5 rounded">
                  <Activity className="h-2.5 w-2.5" /> Live
                </span>
              ) : null}
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-600">
              <span className="inline-flex items-center gap-1">
                <Users className="h-3 w-3" />
                {formatCount(sub.follower_count)} followers
              </span>
              {sub.is_public ? (
                <span className="auth-mono-label text-[10px]">public</span>
              ) : null}
            </div>
            {sub.bio ? (
              <p className="mt-2 text-xs text-gray-600 line-clamp-2">{sub.bio}</p>
            ) : null}
          </div>
        </div>

        <div className="card p-4">
          <p className="auth-mono-label text-[10px]">added</p>
          <p className="font-mono text-sm text-gray-900 mt-1">
            {formatDate(sub.added_at)}
          </p>
          <p className="text-xs text-gray-500 mt-2">
            {sub.added_at &&
            new Date(sub.added_at).getTime() > Date.now() - 24 * 3600_000
              ? 'Within refund window'
              : 'Past 24 h — no refund on removal'}
          </p>
        </div>

        <div className="card p-4">
          <p className="auth-mono-label text-[10px]">recent broadcasts</p>
          <p className="font-mono text-2xl font-semibold text-gray-900 mt-1">
            {rooms.length}
          </p>
          <p className="text-xs text-gray-500 mt-1">past 25 rooms</p>
        </div>
      </div>

      <section className="mb-6">
        <h2 className="auth-mono-label text-[10px] mb-2">
          <Calendar className="inline h-3 w-3 mr-1" /> Last 12 weeks
        </h2>
        {calendarByWeek.length === 0 ? (
          <p className="text-sm text-gray-500">
            No broadcasts in the lookback window yet.
          </p>
        ) : (
          <div className="card p-3 overflow-x-auto">
            <div className="flex gap-2">
              {calendarByWeek.map((w) => (
                <div
                  key={w.week}
                  className="flex-1 min-w-[60px] rounded border border-gray-200 p-2 text-center"
                  title={`${w.week}: ${w.total_rooms} rooms / ${w.total_diamonds} diamonds`}
                >
                  <div className="font-mono text-[10px] text-gray-500">
                    {w.week}
                  </div>
                  <div className="font-mono text-sm font-semibold text-gray-900 mt-1">
                    {w.total_rooms}
                  </div>
                  <div className="font-mono text-[10px] text-gray-500">
                    {formatCount(w.total_diamonds)} 💎
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section>
        <h2 className="auth-mono-label text-[10px] mb-2">Recent broadcasts</h2>
        {rooms.length === 0 ? (
          <p className="text-sm text-gray-500">No rooms yet.</p>
        ) : (
          <div className="card overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="auth-mono-label text-left p-3">Started</th>
                  <th className="auth-mono-label text-left p-3">Ended</th>
                  <th className="auth-mono-label text-right p-3">Diamonds</th>
                  <th className="auth-mono-label text-right p-3">Matches</th>
                  <th className="auth-mono-label text-right p-3">Likes</th>
                </tr>
              </thead>
              <tbody>
                {rooms.map((r) => (
                  <tr
                    key={String(r.room_id)}
                    className="border-t border-gray-100"
                  >
                    <td className="p-3 font-mono text-xs">
                      {formatDate(r.started_at)}
                    </td>
                    <td className="p-3 font-mono text-xs text-gray-500">
                      {formatDate(r.ended_at)}
                    </td>
                    <td className="p-3 font-mono text-right">
                      {formatCount(r.diamonds)}
                    </td>
                    <td className="p-3 font-mono text-right">
                      {formatCount(r.matches)}
                    </td>
                    <td className="p-3 font-mono text-right">
                      {formatCount(r.likes)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </PageShell>
  );
}

export default UserTikTokLiveDetail;

/**
 * Deep-analysis modal for a single Common Gifter.
 *
 * Opened from the Common Gifters table row. Backed by GET
 * /admin/tiktok/common-gifters/{user_id}/detail. Shows:
 *   - Identity (avatar + nickname + @handle + identity badges)
 *   - Cross-host totals (💎, gifts, hosts, rooms, comments, first/last seen)
 *   - Per-host card stack:
 *      • header with host name + "View Host Live" link
 *      • host-scoped stats (💎, gifts, rooms, comments, first/last seen)
 *      • top gift kinds the user sent to that host
 *      • recent rooms with diamond/gift totals (clickable into the
 *        live-detail page)
 *
 * The per-host card is the analytical core — it's where the user
 * understands HOW a viewer bridges multiple creators.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from '@tanstack/react-router';
import toast from 'react-hot-toast';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactECharts from 'echarts-for-react/lib/core';
import {
  Activity,
  Award,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  Flame,
  Gem,
  Gift as GiftIcon,
  Loader2,
  MessageSquare,
  Radio,
  Search,
  Star,
  TrendingUp,
  Users,
  Zap,
} from 'lucide-react';

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

/** Echarts options use hex strings, not Tailwind classes. We derive
 *  theme-aware axis/grid/legend colors from a `useDarkMode` flag and
 *  recompute the chart option when the theme flips, so dark mode
 *  doesn't leave us with mid-gray axis labels on a black canvas. */
function useDarkMode(): boolean {
  const [isDark, setIsDark] = useState(() =>
    typeof document !== 'undefined'
      ? document.documentElement.classList.contains('dark')
      : false,
  );
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    const obs = new MutationObserver(() => {
      setIsDark(root.classList.contains('dark'));
    });
    obs.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => obs.disconnect();
  }, []);
  return isDark;
}

function chartTheme(isDark: boolean) {
  return {
    axisLabel: isDark ? '#a1a1aa' : '#737373',
    axisLine: isDark ? '#3f3f46' : '#d4d4d4',
    splitLine: isDark ? '#27272a' : '#e5e5e5',
    legendText: isDark ? '#d4d4d4' : '#404040',
  };
}

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import {
  type TikTokCommonGifterDetail,
  tiktokApi,
} from '@admin/services/tiktok';
import {
  TikTokUserBadges,
  type IdentityBlock,
} from '@admin/components/TikTokUserBadges';
import type { TikTokEvent } from '@admin/services/tiktok';
import {
  useTikTokTimezone,
  fmtMonthDayTime,
} from '@admin/contexts/TikTokTimezoneContext';

interface Props {
  isOpen: boolean;
  userId: string | null;
  /** Fallback identity when the detail is still loading — lets the
   *  header render the user's avatar + nickname immediately instead
   *  of flashing "Loading…". */
  initialNickname?: string | null;
  initialUniqueId?: string | null;
  initialAvatarUrl?: string | null;
  onClose: () => void;
}

function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}

/** Smart number formatter — compact past 10k, comma-separated below.
 *  The hero figure deserves the full number ("614,225"), but every
 *  inline reference past that should be compact ("614k") so we don't
 *  end up with two formats for the same data. */
function smartNumber(n: number): string {
  if (n >= 10_000) return compactCount(n);
  return n.toLocaleString();
}

function formatRelative(iso: string | null, tz: string): string {
  return fmtMonthDayTime(iso, tz);
}

/** Days since `iso`, or null if missing/invalid. */
function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return Math.floor(ms / 86_400_000);
}

/** Persona inferred from the user's event-type mix. The mix is what
 *  the audit recommended promoting — "Whale", "Chatter", "Engaged",
 *  "Lurker", "Mixed" — surfaced as a header subtitle so it's the
 *  first thing the eye lands on, instead of a 10px pill. */
function inferPersona(behavior: Record<string, number> | undefined): {
  label: string;
  hint: string;
  tone: 'amber' | 'sky' | 'primary' | 'gray' | 'emerald';
} {
  if (!behavior) return { label: 'Mixed', hint: '', tone: 'gray' };
  const total = Object.values(behavior).reduce((a, b) => a + b, 0);
  if (total === 0) return { label: 'Mixed', hint: '', tone: 'gray' };
  const giftRatio = (behavior['gift'] ?? 0) / total;
  const commentRatio = (behavior['comment'] ?? 0) / total;
  const giftPct = Math.round(giftRatio * 100);
  const commentPct = Math.round(commentRatio * 100);
  if (giftRatio >= 0.5)
    return { label: 'Whale', hint: `${giftPct}% of activity is gifting`, tone: 'amber' };
  if (commentRatio >= 0.5)
    return { label: 'Chatter', hint: `${commentPct}% of activity is comments`, tone: 'sky' };
  if (giftRatio >= 0.2 && commentRatio >= 0.2)
    return {
      label: 'Engaged',
      hint: `gifts (${giftPct}%) + comments (${commentPct}%)`,
      tone: 'primary',
    };
  if (giftRatio < 0.05 && commentRatio < 0.05)
    return { label: 'Lurker', hint: 'low gift + comment activity', tone: 'gray' };
  return {
    label: 'Mixed',
    hint: `gifts ${giftPct}% · comments ${commentPct}%`,
    tone: 'emerald',
  };
}

/** Dormancy state derived from `last_seen_at`. The audit's biggest
 *  callout: this signal must surface as a banner, not a small label. */
function inferDormancy(
  lastSeenIso: string | null,
): { label: string; tone: 'rose' | 'amber' | 'emerald'; days: number } | null {
  const d = daysSince(lastSeenIso);
  if (d == null) return null;
  if (d >= 30) return { label: 'Dormant', tone: 'rose', days: d };
  if (d >= 14) return { label: 'Cooling', tone: 'amber', days: d };
  if (d <= 1) return { label: 'Active', tone: 'emerald', days: d };
  return null; // 2–13 days: in the normal cadence band, no callout.
}

function durationMinutes(start: string | null, end: string | null): number | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return null;
  return Math.round(ms / 60_000);
}

type DeepTab = 'profile' | 'timeline' | 'hosts' | 'comments' | 'behavior' | 'network';

/** Seed for the Network tab's activity-feed filter handed off from
 *  another tab. `dow`/`hour` filter activity to that exact hour band
 *  (client-side post-filter on the refetched window). */
interface NetworkSeed {
  dow?: number;
  hour?: number;
  type?: string;
  hint?: string; // human label for the active-filter chip
}

const DEEP_TABS: { id: DeepTab; label: string; icon: React.ReactNode }[] = [
  { id: 'profile',  label: 'Profile',  icon: <Star className="w-3.5 h-3.5" /> },
  { id: 'timeline', label: 'Timeline', icon: <Activity className="w-3.5 h-3.5" /> },
  { id: 'hosts',    label: 'Hosts',    icon: <Radio className="w-3.5 h-3.5" /> },
  { id: 'comments', label: 'Comments', icon: <MessageSquare className="w-3.5 h-3.5" /> },
  { id: 'behavior', label: 'Behavior', icon: <Zap className="w-3.5 h-3.5" /> },
  { id: 'network',  label: 'Network',  icon: <Users className="w-3.5 h-3.5" /> },
];

export function TikTokCommonGifterDetailModal({
  isOpen,
  userId,
  initialNickname,
  initialUniqueId,
  initialAvatarUrl,
  onClose,
}: Props) {
  const { tz } = useTikTokTimezone();
  const [data, setData] = useState<TikTokCommonGifterDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Tab state is local-only (no URL sync). Modal lifetime is short
  // and there's no deep-link target that meaningfully needs a tab
  // hint. Reset to default on every open.
  const [activeTab, setActiveTab] = useState<DeepTab>('profile');
  // Cross-tab filter handoff. When a heatmap cell on the Timeline
  // tab is clicked, we want to (1) switch to the Network tab and
  // (2) seed its activity-feed filter with the picked hour band.
  // The Network tab reads this on mount and applies it once.
  const [networkSeed, setNetworkSeed] = useState<NetworkSeed | null>(null);
  // Favourite-toggle state. Lazy-loaded the moment the modal opens so
  // the star reflects the current truth without a flicker.
  const [isFavorite, setIsFavorite] = useState<boolean | null>(null);
  const [favoriteBusy, setFavoriteBusy] = useState(false);

  useEffect(() => {
    if (!isOpen || !userId) {
      setIsFavorite(null);
      return;
    }
    let cancelled = false;
    tiktokApi
      .isFavoriteGifter(userId)
      .then((r) => {
        if (!cancelled) setIsFavorite(r.is_favorite);
      })
      .catch(() => {
        if (!cancelled) setIsFavorite(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, userId]);

  const onToggleFavorite = async () => {
    if (!userId || favoriteBusy) return;
    setFavoriteBusy(true);
    try {
      if (isFavorite) {
        await tiktokApi.removeFavoriteGifter(userId);
        setIsFavorite(false);
        toast.success('Removed from favorites');
      } else {
        await tiktokApi.addFavoriteGifter(userId);
        setIsFavorite(true);
        toast.success('Added to favorites — alerts will fire when they gift');
      }
      // Notify any tab that's listening for favorites changes —
      // the Favorites tab and the WS-toast filter both refresh on
      // this custom event so the UI stays consistent without a poll.
      window.dispatchEvent(new CustomEvent('tiktok:favorites-changed'));
    } catch (e) {
      toast.error((e as Error).message || 'Favorite toggle failed');
    } finally {
      setFavoriteBusy(false);
    }
  };

  useEffect(() => {
    if (!isOpen || !userId) {
      setData(null);
      setError(null);
      return;
    }
    // Reset to the first tab on every open. This keeps "open the
    // modal" as a known starting point — if the user wants the
    // timeline they can still get there with one click.
    setActiveTab('profile');
    let cancelled = false;
    setLoading(true);
    setError(null);
    tiktokApi
      .getCommonGifterDetail(userId)
      .then((d) => {
        if (cancelled) return;
        setData(d);
      })
      .catch((e) => {
        if (cancelled) return;
        setError((e as Error).message || 'Failed to load gifter detail');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, userId]);

  const nickname = data?.nickname ?? initialNickname ?? null;
  const uniqueId = data?.unique_id ?? initialUniqueId ?? null;
  const avatarUrl = data?.avatar_url ?? initialAvatarUrl ?? null;
  const display = nickname || uniqueId || (userId ? `User ${userId}` : 'Viewer');

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Common gifter — deep analysis"
      className="max-w-4xl"
      footer={
        <div className="flex items-center justify-between gap-2 w-full">
          <span className="text-xs text-gray-500 font-mono">
            {data
              ? `${data.totals.host_count} hosts · ${data.totals.room_count} rooms · ${data.totals.gifts.toLocaleString()} gifts`
              : ' '}
          </span>
          <div className="flex items-center gap-2">
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
            <Button variant="ghost" onClick={onClose}>Close</Button>
          </div>
        </div>
      }
    >
      {/* Hero block — combines identity, the lifetime-diamonds
          headline, persona, dormancy callout, and rank/scale meta.
          The previous design had an 8-cell grid where every figure
          (lifetime diamonds, last_seen, rooms) had equal weight,
          which buried the actually-interesting facts. The audit
          recommended promoting persona + dormancy to header
          subtitles so the eye lands on the signal before the
          accounting. */}
      {(() => {
        const persona = inferPersona(data?.behavior);
        const dorm = data ? inferDormancy(data.totals.last_seen_at) : null;
        const personaToneClass = {
          amber:    'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200',
          sky:      'bg-sky-100 text-sky-800 dark:bg-sky-500/20 dark:text-sky-200',
          primary:  'bg-primary-100 text-primary-800 dark:bg-primary-500/20 dark:text-primary-200',
          gray:     'bg-gray-100 text-gray-700',
          emerald:  'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200',
        }[persona.tone];
        const dormToneClass = dorm
          ? {
              rose:    'bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-200 ring-rose-200 dark:ring-rose-500/40',
              amber:   'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200 ring-amber-200 dark:ring-amber-500/40',
              emerald: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200 ring-emerald-200 dark:ring-emerald-500/40',
            }[dorm.tone]
          : '';
        const avgPerGift = data && data.totals.gifts > 0
          ? Math.round(data.totals.diamonds / data.totals.gifts)
          : 0;
        return (
          <div className="mb-4 p-4 rounded-lg bg-gray-50 dark:bg-gray-100/[0.05] border border-gray-200">
            <div className="flex items-start gap-4">
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt=""
                  className="w-16 h-16 rounded-full object-cover ring-2 ring-white dark:ring-white/10 shadow-sm shrink-0"
                  referrerPolicy="no-referrer"
                  loading="lazy"
                />
              ) : (
                <div className="w-16 h-16 rounded-full bg-gray-100 dark:bg-white/5 text-gray-400 flex items-center justify-center text-xl font-bold shrink-0">
                  {(display[0] || '?').toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="text-lg font-bold text-gray-900 truncate">
                    {display}
                  </span>
                  {uniqueId && uniqueId !== display && (
                    <span className="text-xs font-mono text-gray-500">
                      @{uniqueId}
                    </span>
                  )}
                </div>
                {/* Persona + dormancy row — the audit's hierarchy ask. */}
                {data && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] font-mono">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full uppercase tracking-wider ${personaToneClass}`}>
                      {persona.label}
                    </span>
                    {persona.hint && (
                      <span className="text-gray-500 normal-case">
                        {persona.hint}
                      </span>
                    )}
                    {dorm && (
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full uppercase tracking-wider ring-1 ${dormToneClass}`}
                        title={`Last seen ${dorm.days} day${dorm.days === 1 ? '' : 's'} ago`}
                      >
                        {dorm.label}
                        <span className="normal-case opacity-80">
                          {dorm.days === 0
                            ? 'today'
                            : `${dorm.days}d ago`}
                        </span>
                      </span>
                    )}
                  </div>
                )}
                {data?.identity && (
                  <div className="mt-1.5">
                    <TikTokUserBadges identity={data.identity} />
                  </div>
                )}
                {userId && (
                  <div className="mt-1 text-[10px] font-mono text-gray-400">
                    ID: {userId}
                  </div>
                )}
              </div>
            </div>

            {/* Hero figures: diamonds is the headline; rank +
                scale (hosts × rooms) sits next to it; the rest
                falls into a thin meta strip below. */}
            {data && (
              <div className="mt-4 flex flex-wrap items-end gap-x-6 gap-y-2">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
                    Lifetime diamonds
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-3xl font-bold tabular-nums text-amber-700 dark:text-amber-300">
                      {data.totals.diamonds.toLocaleString()}
                    </span>
                    <Gem className="w-5 h-5 text-amber-500" />
                  </div>
                </div>
                {data.rank && data.rank.pool_size > 0 && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
                      Rank
                    </div>
                    <div className="text-base font-bold tabular-nums text-primary-700 dark:text-primary-300">
                      #{data.rank.by_diamonds.toLocaleString()}
                      <span className="text-gray-500 font-normal text-xs">
                        {' '}
                        of {data.rank.pool_size.toLocaleString()}
                      </span>
                    </div>
                  </div>
                )}
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
                    Across
                  </div>
                  <div className="text-base font-bold tabular-nums text-gray-900">
                    {data.totals.host_count} hosts
                    <span className="text-gray-500 font-normal text-xs">
                      {' · '}
                      {data.totals.room_count} rooms
                    </span>
                  </div>
                </div>
                {avgPerGift > 0 && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
                      Avg / gift
                    </div>
                    <div className="text-base font-bold tabular-nums text-amber-700 dark:text-amber-300">
                      {smartNumber(avgPerGift)}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Thin meta strip — accounting figures that no longer
                deserve hero weight but still belong in the header. */}
            {data && (
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] font-mono text-gray-500">
                <span className="inline-flex items-center gap-1">
                  <GiftIcon className="w-3 h-3 text-rose-500" />
                  {smartNumber(data.totals.gifts)} gifts
                </span>
                <span className="inline-flex items-center gap-1">
                  <MessageSquare className="w-3 h-3 text-sky-500" />
                  {smartNumber(data.totals.comment_count)} comments
                </span>
                <span className="inline-flex items-center gap-1">
                  <Calendar className="w-3 h-3" />
                  First {formatRelative(data.totals.first_seen_at, tz)}
                </span>
                <span className="inline-flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  Last {formatRelative(data.totals.last_seen_at, tz)}
                </span>
              </div>
            )}
          </div>
        );
      })()}

      {/* States */}
      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 px-4 py-6 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}
      {loading && !data && (
        <div className="py-10 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
          Loading deep analysis…
        </div>
      )}

      {/* Tab bar — only visible once data is loaded so the loading
          state stays clean. */}
      {data && (
        <div
          className="flex items-center gap-1 mb-3 border-b border-gray-200 overflow-x-auto whitespace-nowrap -mx-4 px-4 sm:mx-0 sm:px-0"
          role="tablist"
          aria-label="Deep analysis sections"
        >
          {DEEP_TABS.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                role="tab"
                aria-selected={active}
                onClick={() => setActiveTab(tab.id)}
                className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-2 text-xs font-mono uppercase tracking-wider border-b-2 -mb-px transition-colors ${
                  active
                    ? 'border-primary-500 text-primary-700 dark:text-primary-300'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.icon}
                {tab.label}
              </button>
            );
          })}
        </div>
      )}

      {/* Empty-state shared across tabs. */}
      {data && data.hosts.length === 0 && !loading && (
        <p className="text-sm text-gray-500 py-6 text-center">
          This viewer has no recorded gifts in any room we track.
        </p>
      )}

      {/* Tab bodies. Mounted only when active so charts don't pay
          their init cost until needed. */}
      {data && data.hosts.length > 0 && activeTab === 'profile' && (
        <ProfileTab data={data} />
      )}
      {data && data.hosts.length > 0 && activeTab === 'timeline' && (
        <TimelineTab
          data={data}
          tz={tz}
          onPickHour={(dow, hour) => {
            setNetworkSeed({
              dow,
              hour,
              type: 'gift',
              hint: `${DOW_LABELS[dow]} ${hour}:00 gifts`,
            });
            setActiveTab('network');
          }}
        />
      )}
      {data && data.hosts.length > 0 && activeTab === 'hosts' && (
        <HostsTab data={data} userId={userId} />
      )}
      {data && data.hosts.length > 0 && activeTab === 'comments' && (
        <CommentsTab data={data} userId={userId} tz={tz} />
      )}
      {data && data.hosts.length > 0 && activeTab === 'behavior' && (
        <BehaviorTab data={data} tz={tz} />
      )}
      {data && data.hosts.length > 0 && activeTab === 'network' && (
        <NetworkTab
          data={data}
          tz={tz}
          /* The detail's `data.user_id` is a JS Number — TikTok ids
             exceed Number.MAX_SAFE_INTEGER and lose precision in the
             trailing digits during JSON.parse. The `userId` prop is
             the original string handed in by the parent table — use
             that for any outbound call. */
          userId={userId}
          seed={networkSeed}
          onSeedConsumed={() => setNetworkSeed(null)}
        />
      )}
    </Modal>
  );
}

interface SummaryStatProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  accent?: 'amber' | 'sky' | 'primary' | 'rose';
}

function SummaryStat({ icon, label, value, accent }: SummaryStatProps) {
  // For accent values: emit BOTH light + dark variants since accents
  // (amber/sky/primary/rose) aren't part of the gray auto-inversion.
  // For neutral grey, use only the light-mode class — the framework
  // inverts it for free. Mixing in `dark:text-gray-100` would break
  // that inversion (per the project's dark-mode rules).
  const valueClass =
    accent === 'amber'
      ? 'text-amber-700 dark:text-amber-300'
      : accent === 'sky'
        ? 'text-sky-700 dark:text-sky-300'
        : accent === 'primary'
          ? 'text-primary-700 dark:text-primary-300'
          : accent === 'rose'
            ? 'text-rose-700 dark:text-rose-300'
            : 'text-gray-900';
  return (
    <div className="rounded-md border border-gray-200 bg-white dark:bg-gray-100/[0.05] px-2.5 py-1.5 shadow-sm">
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-500">
        {icon}
        {label}
      </div>
      <div className={`mt-0.5 font-bold tabular-nums ${valueClass}`}>{value}</div>
    </div>
  );
}

function HostCard({
  host,
  totalDiamonds,
  userId,
  messageQ = '',
}: {
  host: import('@admin/services/tiktok').TikTokCommonGifterDetailHost;
  /** Used to show the host's % of this viewer's overall diamonds. */
  totalDiamonds: number;
  /** Viewer (gifter) id — needed to query per-host messages. */
  userId: string | null;
  /** Free-text search applied to the per-host comments list. Empty
   *  string disables the filter (the messages query stays unscoped). */
  messageQ?: string;
}) {
  const { tz } = useTikTokTimezone();
  const pct = totalDiamonds > 0 ? (host.diamonds / totalDiamonds) * 100 : 0;
  return (
    <section className="rounded-lg border border-gray-200 overflow-hidden bg-white dark:bg-gray-100/[0.03] shadow-sm">
      {/* Header: host + "View Live" link + diamond share. The
          primary-tinted band makes the section header pop visually
          even on a dark surface. */}
      <header className="flex items-center justify-between gap-3 px-4 py-2 bg-primary-50/80 dark:bg-primary-500/[0.12] border-b border-primary-100 dark:border-primary-500/30">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Radio className="w-4 h-4 text-primary-600" />
            <span className="font-medium text-gray-900">
              @{host.host}
            </span>
            <span
              className="ml-1 inline-flex items-center px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-200 text-[10px] font-mono"
              title="Share of this viewer's total diamonds"
            >
              {pct.toFixed(1)}%
            </span>
          </div>
        </div>
        <Link
          to="/admin/tiktok/$handle"
          params={{ handle: host.host }}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-white border border-primary-200 text-primary-700 hover:bg-primary-50 hover:border-primary-300 dark:bg-white/5 dark:text-primary-300 text-xs font-medium"
          title="Open this host's live-detail page"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          View Host Live
        </Link>
      </header>

      <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Stats column */}
        <div className="flex flex-col gap-1.5 text-xs font-mono">
          <Row icon={<Gem className="w-3.5 h-3.5 text-amber-500" />} label="Diamonds">
            <span className="text-amber-700 dark:text-amber-300 tabular-nums">
              {host.diamonds.toLocaleString()}
            </span>
          </Row>
          <Row icon={<GiftIcon className="w-3.5 h-3.5 text-rose-500" />} label="Gifts">
            <span className="tabular-nums">{host.gifts.toLocaleString()}</span>
          </Row>
          <Row icon={<Radio className="w-3.5 h-3.5 text-emerald-500" />} label="Rooms">
            <span className="tabular-nums">{host.room_count.toLocaleString()}</span>
          </Row>
          <Row
            icon={<MessageSquare className="w-3.5 h-3.5 text-sky-500" />}
            label="Comments"
          >
            <span className="text-sky-700 dark:text-sky-300 tabular-nums">
              {host.comment_count.toLocaleString()}
            </span>
          </Row>
          <Row icon={<Calendar className="w-3.5 h-3.5 text-gray-500" />} label="First seen">
            <span className="text-gray-700">
              {formatRelative(host.first_seen_at, tz)}
            </span>
          </Row>
          <Row icon={<Clock className="w-3.5 h-3.5 text-gray-500" />} label="Last seen">
            <span className="text-gray-700">
              {formatRelative(host.last_seen_at, tz)}
            </span>
          </Row>
          {host.host_total_rooms != null && host.host_total_rooms > 0 && (
            <Row
              icon={<TrendingUp className="w-3.5 h-3.5 text-emerald-500" />}
              label="Attendance"
            >
              <span
                className="text-emerald-700 dark:text-emerald-300 tabular-nums"
                title={`Showed up in ${host.room_count} of @${host.host}'s ${host.host_total_rooms} broadcasts`}
              >
                {(host.attendance_pct ?? 0).toFixed(1)}%
                <span className="ml-1 text-gray-500">
                  ({host.room_count}/{host.host_total_rooms})
                </span>
              </span>
            </Row>
          )}
          {host.match_gifts != null && host.match_gifts > 0 && (
            <Row
              icon={<Zap className="w-3.5 h-3.5 text-purple-500" />}
              label="During PK"
            >
              <span
                className="text-purple-700 dark:text-purple-300 tabular-nums"
                title="Gifts sent while a battle was active"
              >
                {host.match_gifts.toLocaleString()} gifts
                <span className="ml-1 text-gray-500">
                  ({compactCount(host.match_diamonds ?? 0)})
                </span>
              </span>
            </Row>
          )}
        </div>

        {/* Top gift kinds */}
        <div>
          {host.signature_gift && (
            <div className="mb-2 px-2 py-1.5 rounded-md bg-rose-50 border border-rose-200 dark:bg-rose-500/10 dark:border-rose-500/30 text-[11px] font-mono text-rose-800 dark:text-rose-200">
              <span className="uppercase tracking-wider text-[10px] opacity-70">
                Signature
              </span>
              <span className="ml-1">
                {host.signature_gift.gift_name}{' '}
                <span className="opacity-70">
                  · {host.signature_gift.lift.toFixed(1)}× more vs baseline
                </span>
              </span>
            </div>
          )}
          <div className="auth-mono-label mb-1.5">
            Top gifts to @{host.host}
          </div>
          {host.top_gifts.length === 0 ? (
            <p className="text-xs text-gray-500">No gift breakdown available.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-xs font-mono">
              {host.top_gifts.map((g) => (
                <li
                  key={g.gift_name}
                  className="flex items-center justify-between gap-2 px-2 py-1 rounded bg-gray-100 dark:bg-gray-100/[0.08] border border-gray-200"
                >
                  <span className="truncate text-gray-700">
                    {g.gift_name}
                  </span>
                  <span className="flex items-center gap-2 shrink-0">
                    <span className="text-gray-500 tabular-nums">
                      ×{g.count.toLocaleString()}
                    </span>
                    <span className="text-amber-700 dark:text-amber-300 tabular-nums inline-flex items-center gap-0.5">
                      <Gem className="w-3 h-3" />
                      {compactCount(g.diamonds)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Recipient breakdown — only meaningful when the gifter
          targeted specific guests in this host's rooms (multi-guest
          / PK lives). For solo-only history, `recipients` is empty
          and we render nothing. */}
      {host.recipients && host.recipients.length > 0 && (
        <div className="border-t border-gray-200 dark:border-white/10 p-4">
          <div className="auth-mono-label mb-1.5">
            Specific recipients in @{host.host}'s rooms
            <span className="ml-1 text-gray-500 font-mono normal-case">
              (multi-guest / PK targets)
            </span>
          </div>
          <ul className="flex flex-col gap-1 text-xs font-mono">
            {host.recipients.map((r) => (
              <li
                key={r.unique_id || r.nickname || ''}
                className="flex items-center gap-2 px-2 py-1 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
              >
                {r.is_host ? (
                  <span
                    className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[10px] uppercase tracking-wider"
                    title="The gift recipient is the host themselves"
                  >
                    host
                  </span>
                ) : (
                  <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300 text-[10px] uppercase tracking-wider">
                    guest
                  </span>
                )}
                <span className="min-w-0 flex-1 truncate">
                  {r.nickname || r.unique_id || '—'}
                  {r.unique_id && r.unique_id !== r.nickname && (
                    <span className="ml-1 text-gray-500">@{r.unique_id}</span>
                  )}
                </span>
                <span className="shrink-0 text-gray-500 tabular-nums">
                  {r.gifts.toLocaleString()} gifts
                </span>
                <span className="shrink-0 text-amber-700 dark:text-amber-300 tabular-nums inline-flex items-baseline gap-0.5">
                  <Gem className="w-3 h-3 self-center" />
                  {compactCount(r.diamonds)}
                </span>
                {r.pk_gifts > 0 && (
                  <span className="shrink-0 text-purple-700 dark:text-purple-300 tabular-nums text-[10px]">
                    {r.pk_gifts}× in PK
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Per-host messages — collapsed by default; clicking the
          header expands and lazily loads the first page. */}
      {host.comment_count > 0 && userId && (
        <HostMessages
          userId={userId}
          host={host.host}
          commentCount={host.comment_count}
          tz={tz}
          messageQ={messageQ}
        />
      )}

      {/* Recent rooms */}
      {host.rooms.length > 0 && (
        <div className="border-t border-gray-200 dark:border-white/10 p-4">
          <div className="auth-mono-label mb-1.5">
            Recent rooms with gifts ({host.rooms.length} shown)
          </div>
          <ul className="flex flex-col gap-1.5 text-xs font-mono">
            {host.rooms.map((r) => {
              const dur = durationMinutes(r.started_at, r.ended_at);
              return (
                <li
                  key={r.room_id}
                  className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 sm:gap-2 px-2 py-1.5 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-gray-700 truncate">
                      {r.title || `Room ${r.room_id}`}
                    </div>
                    <div className="text-[10px] text-gray-500">
                      {formatRelative(r.started_at, tz)}
                      {r.ended_at ? ` · ${formatRelative(r.ended_at, tz)}` : ' · still going'}
                      {dur != null && ` · ${dur}m`}
                    </div>
                  </div>
                  <span className="flex items-center gap-2 shrink-0">
                    <span className="text-amber-700 dark:text-amber-300 tabular-nums inline-flex items-center gap-0.5">
                      <Gem className="w-3 h-3" />
                      {compactCount(r.diamonds)}
                    </span>
                    <span className="text-gray-500 tabular-nums">
                      {compactCount(r.gifts)} gifts
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

function HostMessages({
  userId,
  host,
  commentCount,
  tz,
  messageQ = '',
}: {
  userId: string;
  host: string;
  commentCount: number;
  tz: string;
  /** Substring filter passed straight through to the backend's `q`
   *  param. When non-empty, total + items both reflect the search;
   *  when empty, falls back to the unfiltered comment count from the
   *  parent (cheap, doesn't trigger a count query). */
  messageQ?: string;
}) {
  const PAGE_OPTIONS = [10, 25, 50, 100] as const;
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<import('@admin/services/tiktok').TikTokEvent[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState<number>(25);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-open the messages list when a search is active so the
  // results are visible without an extra click.
  useEffect(() => {
    if (messageQ.trim()) setOpen(true);
  }, [messageQ]);

  // Reset paging when the search query, page size, or host changes.
  useEffect(() => {
    if (!open) return;
    setOffset(0);
    setTotal(null); // force count refetch under new filter
  }, [host, userId, pageSize, open, messageQ]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const trimmed = messageQ.trim();
    Promise.all([
      tiktokApi.searchEvents({
        user_id: userId,
        handle: host,
        type: 'comment',
        limit: pageSize,
        offset,
        q: trimmed || undefined,
      }),
      total === null
        ? tiktokApi.countEvents({
            user_id: userId,
            handle: host,
            type: 'comment',
            q: trimmed || undefined,
          })
        : Promise.resolve({ total }),
    ])
      .then(([rows, t]) => {
        if (cancelled) return;
        setItems(rows);
        setTotal(t.total ?? null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError((e as Error).message || 'Failed to load messages');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, userId, host, offset, pageSize, messageQ]);

  const realTotal = total ?? commentCount;
  const totalPages = Math.max(1, Math.ceil(realTotal / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;

  return (
    <div className="border-t border-gray-200 dark:border-white/10 p-4 bg-gray-50/40 dark:bg-gray-100/[0.02]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="auth-mono-label flex items-center gap-1.5">
          <MessageSquare className="w-3.5 h-3.5 text-sky-500" />
          Messages to @{host}
          <span className="ml-1 text-gray-500 font-mono text-[11px]">
            ({commentCount.toLocaleString()})
          </span>
        </div>
        <span className="text-[11px] text-gray-500 font-mono">
          {open ? 'hide' : 'show'}
        </span>
      </button>

      {open && (
        <div className="mt-2 flex flex-col gap-2">
          {/* Page-size selector. */}
          <div className="flex items-center justify-between text-[11px] font-mono text-gray-500">
            <label className="flex items-center gap-1.5">
              Per page
              <select
                value={pageSize}
                onChange={(e) => setPageSize(Number(e.target.value))}
                className="px-1.5 py-0.5 rounded border border-gray-200 text-[11px] font-mono dark:bg-gray-100/5"
              >
                {PAGE_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <span>
              {realTotal === 0
                ? '0'
                : `${(offset + 1).toLocaleString()}–${Math.min(
                    offset + items.length,
                    realTotal,
                  ).toLocaleString()} of ${realTotal.toLocaleString()}`}
            </span>
          </div>

          {error ? (
            <div className="rounded border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
              {error}
            </div>
          ) : loading && items.length === 0 ? (
            <div className="text-xs text-gray-500 py-3 text-center">
              <Loader2 className="w-3.5 h-3.5 inline animate-spin mr-1.5" />
              Loading messages…
            </div>
          ) : items.length === 0 ? (
            <p className="text-xs text-gray-500 py-3 text-center">
              No comment events for this host.
            </p>
          ) : (
            <ol className="flex flex-col gap-1.5 text-xs font-mono">
              {items.map((e) => {
                const p = (e.payload || {}) as Record<string, unknown>;
                const text = String(p.text ?? '');
                return (
                  <li
                    key={e.id}
                    className="flex flex-col sm:flex-row items-start sm:items-baseline gap-x-2 gap-y-0.5 px-2 py-1.5 rounded border border-gray-200 bg-white dark:bg-gray-100/[0.06]"
                  >
                    {/* Timestamp shrinks tight on mobile (full row),
                        anchors to a fixed width on desktop so the
                        message column lines up nicely. */}
                    <span className="shrink-0 text-[10px] text-gray-500 tabular-nums sm:w-[7rem]">
                      {fmtMonthDayTime(e.ts, tz)}
                    </span>
                    <span className="text-gray-700 flex-1 min-w-0 break-words whitespace-pre-wrap">
                      {text || <span className="italic text-gray-400">(empty)</span>}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}

          {/* Pagination. */}
          {realTotal > pageSize && (
            <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-gray-500">
              <span>
                Page {currentPage} / {totalPages}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={offset === 0 || loading}
                  onClick={() => setOffset(Math.max(0, offset - pageSize))}
                  className="inline-flex items-center px-2 py-0.5 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
                  aria-label="Previous page"
                >
                  ‹ Prev
                </button>
                <button
                  type="button"
                  disabled={offset + pageSize >= realTotal || loading}
                  onClick={() => setOffset(offset + pageSize)}
                  className="inline-flex items-center px-2 py-0.5 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
                  aria-label="Next page"
                >
                  Next ›
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="flex items-center gap-1.5 text-gray-500">
        {icon}
        {label}
      </span>
      {children}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Tab: Profile & Signature — answers "WHO is this?" with rank,
// behavioral mix, and intensity stats.
// ────────────────────────────────────────────────────────────────────

function ProfileTab({ data }: { data: TikTokCommonGifterDetail }) {
  return (
    <div className="flex flex-col gap-4">
      {/* Two-column row: momentum (status pulse) + loyalty (concentration). */}
      {(data.momentum || data.loyalty) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {data.momentum && <MomentumPanel m={data.momentum} />}
          {data.loyalty && <LoyaltyPanel l={data.loyalty} hosts={data.hosts} />}
        </div>
      )}
      {data.tier_mix && data.tier_mix.length > 0 && (
        <TierMixPanel tiers={data.tier_mix} />
      )}
      {data.identity_progression && data.identity_progression.length > 0 && (
        <IdentityProgressionPanel rows={data.identity_progression} />
      )}
      {data.rank && data.rank.pool_size > 0 && <RankPanel rank={data.rank} />}
      {data.behavior && Object.keys(data.behavior).length > 0 && (
        <BehaviorPanel
          behavior={data.behavior}
          totalGifts={data.totals.gifts}
          totalDiamonds={data.totals.diamonds}
        />
      )}
      {data.intensity && Object.keys(data.intensity).length > 0 && (
        <IntensityPanel intensity={data.intensity} />
      )}
    </div>
  );
}

function MomentumPanel({
  m,
}: {
  m: NonNullable<TikTokCommonGifterDetail['momentum']>;
}) {
  const tone = {
    heating: 'bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-500/10 dark:border-rose-500/30 dark:text-rose-200',
    cooling: 'bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-500/10 dark:border-amber-500/30 dark:text-amber-200',
    steady:  'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-500/10 dark:border-emerald-500/30 dark:text-emerald-200',
    silent:  'bg-gray-100 border-gray-200 text-gray-700',
  }[m.label];
  const labelCopy = {
    heating: '🔥 Heating up',
    cooling: '❄ Cooling',
    steady:  '◯ Steady',
    silent:  '∅ Silent',
  }[m.label];
  return (
    <section className={`rounded-lg border p-4 ${tone}`}>
      <div className="auth-mono-label flex items-center gap-1.5 mb-2 normal-case opacity-70">
        7d vs 28d momentum
      </div>
      <div className="text-xl font-bold">{labelCopy}</div>
      <div className="mt-1 text-xs font-mono opacity-80">
        {m.diamonds_7d.toLocaleString()} 💎 / 7d
        <span className="opacity-60">
          {' '}
          ({m.ratio.toFixed(1)}× the 28d rate)
        </span>
      </div>
    </section>
  );
}

function LoyaltyPanel({
  l,
  hosts,
}: {
  l: NonNullable<TikTokCommonGifterDetail['loyalty']>;
  hosts: TikTokCommonGifterDetail['hosts'];
}) {
  const character =
    l.gini >= 0.7
      ? { label: 'Monogamist', color: 'text-rose-700 dark:text-rose-300' }
      : l.gini >= 0.4
        ? { label: 'Skewed', color: 'text-amber-700 dark:text-amber-300' }
        : { label: 'Spread', color: 'text-emerald-700 dark:text-emerald-300' };
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label mb-2">Loyalty concentration</div>
      <div className="flex items-baseline gap-2">
        <span className={`text-xl font-bold ${character.color}`}>
          {character.label}
        </span>
        <span className="text-xs font-mono text-gray-500">
          gini {l.gini.toFixed(2)}
        </span>
      </div>
      <div className="mt-1 text-xs font-mono text-gray-700">
        <span className="tabular-nums">{l.top1_pct.toFixed(0)}%</span> of diamonds to{' '}
        <Link
          to="/admin/tiktok/$handle"
          params={{ handle: l.top_host || '' }}
          className="text-primary-700 dark:text-primary-300 hover:underline"
        >
          @{l.top_host || '—'}
        </Link>
      </div>
      {/* Compact host-share bar — shows the spread visually. */}
      <div className="mt-2 h-2 w-full rounded-full overflow-hidden flex bg-gray-200 dark:bg-white/10">
        {hosts.map((h, i) => {
          const totalAll = hosts.reduce((a, b) => a + (b.diamonds || 0), 0) || 1;
          const pct = (h.diamonds / totalAll) * 100;
          if (pct < 0.2) return null;
          return (
            <div
              key={h.host}
              className="h-full"
              style={{
                width: `${pct}%`,
                backgroundColor: HOST_PALETTE[i % HOST_PALETTE.length],
              }}
              title={`@${h.host}: ${pct.toFixed(1)}%`}
            />
          );
        })}
      </div>
    </section>
  );
}

function TierMixPanel({
  tiers,
}: {
  tiers: NonNullable<TikTokCommonGifterDetail['tier_mix']>;
}) {
  const TIER_META: Record<string, { label: string; color: string; range: string }> = {
    tiny:   { label: 'Tiny',   color: 'bg-gray-400',   range: '1–9 💎' },
    small:  { label: 'Small',  color: 'bg-sky-500',    range: '10–99 💎' },
    medium: { label: 'Medium', color: 'bg-amber-500',  range: '100–999 💎' },
    large:  { label: 'Large',  color: 'bg-rose-500',   range: '1k+ 💎' },
  };
  const totalDiamonds = tiers.reduce((a, b) => a + b.diamonds, 0) || 1;
  const totalGifts = tiers.reduce((a, b) => a + b.gifts, 0) || 1;
  // Ordered tiers so the bar stack reads consistently.
  const order: ('tiny' | 'small' | 'medium' | 'large')[] = ['tiny', 'small', 'medium', 'large'];
  const ordered = order
    .map((t) => tiers.find((x) => x.tier === t))
    .filter((x): x is NonNullable<typeof x> => !!x);
  // Whale pattern: large tier carries >80% of diamonds. Sniper.
  // Grinder: tiny+small >50% of gift events. Spammer.
  const largeShare = (ordered.find((t) => t.tier === 'large')?.diamonds ?? 0) / totalDiamonds;
  const tinySmallGiftShare =
    ((ordered.find((t) => t.tier === 'tiny')?.gifts ?? 0)
      + (ordered.find((t) => t.tier === 'small')?.gifts ?? 0))
    / totalGifts;
  let pattern: string;
  if (largeShare >= 0.8) pattern = 'Sniper — diamonds concentrated in 1k+ gifts';
  else if (tinySmallGiftShare >= 0.7) pattern = 'Grinder — most gifts are sub-100 💎';
  else pattern = 'Mixed — gifts span the full price range';
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Gem className="w-3.5 h-3.5 text-amber-500" />
        Gift-tier mix
      </div>
      <div className="text-xs font-mono text-gray-700 mb-2">{pattern}</div>
      {/* Diamonds-stacked bar (top) — shows where the money actually went. */}
      <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1 font-mono">
        Diamond contribution
      </div>
      <div className="h-3 w-full rounded-full overflow-hidden flex bg-gray-200 dark:bg-white/10">
        {ordered.map((t) => {
          const pct = (t.diamonds / totalDiamonds) * 100;
          if (pct < 0.5) return null;
          return (
            <div
              key={t.tier}
              className={TIER_META[t.tier].color}
              style={{ width: `${pct}%` }}
              title={`${TIER_META[t.tier].label}: ${t.diamonds.toLocaleString()} 💎 (${pct.toFixed(1)}%)`}
            />
          );
        })}
      </div>
      {/* Gifts-stacked bar (bottom) — shows tile count distribution. */}
      <div className="text-[10px] uppercase tracking-wider text-gray-500 mt-2 mb-1 font-mono">
        Gift count
      </div>
      <div className="h-3 w-full rounded-full overflow-hidden flex bg-gray-200 dark:bg-white/10">
        {ordered.map((t) => {
          const pct = (t.gifts / totalGifts) * 100;
          if (pct < 0.5) return null;
          return (
            <div
              key={t.tier}
              className={TIER_META[t.tier].color}
              style={{ width: `${pct}%` }}
              title={`${TIER_META[t.tier].label}: ${t.gifts.toLocaleString()} gifts (${pct.toFixed(1)}%)`}
            />
          );
        })}
      </div>
      <ul className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
        {ordered.map((t) => {
          const dPct = (t.diamonds / totalDiamonds) * 100;
          const gPct = (t.gifts / totalGifts) * 100;
          return (
            <li
              key={t.tier}
              className="rounded-md border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06] px-2 py-1.5"
            >
              <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-500">
                <span className={`w-2 h-2 rounded-full ${TIER_META[t.tier].color}`} />
                {TIER_META[t.tier].label}
              </div>
              <div className="text-[10px] text-gray-400">{TIER_META[t.tier].range}</div>
              <div className="mt-0.5 tabular-nums text-amber-700 dark:text-amber-300">
                {compactCount(t.diamonds)}
                <span className="text-gray-500 font-normal"> ({dPct.toFixed(0)}%)</span>
              </div>
              <div className="text-[11px] text-gray-500 tabular-nums">
                {compactCount(t.gifts)} gifts ({gPct.toFixed(0)}%)
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function IdentityProgressionPanel({
  rows,
}: {
  rows: NonNullable<TikTokCommonGifterDetail['identity_progression']>;
}) {
  // Pivot per host so each line is one creator's member_level
  // trajectory. Member level is what TikTok surfaces as the gifter's
  // host-side fan rank — climbing means each diamond actually
  // produced measurable fan-rank lift.
  const { hosts, days, byHost } = useMemo(() => {
    const dayMap = new Map<string, true>();
    const hostMap = new Map<string, true>();
    for (const r of rows) {
      if (r.day) dayMap.set(r.day.slice(0, 10), true);
      if (r.host) hostMap.set(r.host, true);
    }
    const days = Array.from(dayMap.keys()).sort();
    const hosts = Array.from(hostMap.keys());
    const byHost = new Map<string, Map<string, number | null>>();
    for (const h of hosts) byHost.set(h, new Map());
    for (const r of rows) {
      const d = r.day?.slice(0, 10);
      if (!d || !r.host) continue;
      byHost.get(r.host)!.set(d, r.member_level);
    }
    return { hosts, days, byHost };
  }, [rows]);

  const isDark = useDarkMode();
  const t = chartTheme(isDark);

  const option = useMemo(() => {
    const series = hosts.map((h, i) => ({
      name: `@${h}`,
      type: 'line',
      symbol: 'circle',
      symbolSize: 6,
      step: 'end',
      connectNulls: true,
      lineStyle: { width: 2 },
      color: HOST_PALETTE[i % HOST_PALETTE.length],
      data: days.map((d) => byHost.get(h)?.get(d) ?? null),
    }));
    return {
      grid: { left: 36, right: 12, top: 36, bottom: 22 },
      tooltip: { trigger: 'axis' },
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: {
          fontSize: 10,
          fontFamily: 'JetBrains Mono Variable',
          color: t.legendText,
        },
        pageTextStyle: { color: t.legendText },
        pageIconColor: t.axisLabel,
      },
      xAxis: {
        type: 'category',
        data: days,
        axisLabel: { fontSize: 9, color: t.axisLabel },
        axisLine: { lineStyle: { color: t.axisLine } },
      },
      yAxis: {
        type: 'value',
        name: 'member level',
        nameTextStyle: { fontSize: 9, color: t.axisLabel },
        axisLabel: { fontSize: 9, color: t.axisLabel },
        splitLine: { lineStyle: { color: t.splitLine } },
      },
      series,
    };
  }, [hosts, days, byHost, t.axisLabel, t.axisLine, t.splitLine, t.legendText]);

  // Snapshot the latest member_level + fans_club state per host —
  // a numeric stat strip below the chart, since the chart is the
  // trajectory and the strip is "where they stand right now."
  const latestPerHost = useMemo(() => {
    const m = new Map<string, NonNullable<TikTokCommonGifterDetail['identity_progression']>[number]>();
    for (const r of rows) {
      const cur = m.get(r.host);
      if (!cur || (r.day && cur.day && r.day > cur.day)) m.set(r.host, r);
    }
    return Array.from(m.values()).sort(
      (a, b) => (b.member_level ?? 0) - (a.member_level ?? 0),
    );
  }, [rows]);

  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <TrendingUp className="w-3.5 h-3.5 text-primary-500" />
        Fan-rank trajectory per host
        <span className="ml-2 text-gray-500 font-mono normal-case">
          (member_level over time — did each diamond translate?)
        </span>
      </div>
      <ReactECharts
        echarts={echarts}
        option={option}
        style={{ height: 220, minHeight: 200 }}
        notMerge
        lazyUpdate
      />
      {/* Latest snapshot strip — fans-club name only when present. */}
      <ul className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5 text-xs font-mono">
        {latestPerHost.map((r, i) => (
          <li
            key={r.host}
            className="flex items-center gap-2 px-2 py-1 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
          >
            <span
              className="shrink-0 w-2 h-2 rounded-full"
              style={{ backgroundColor: HOST_PALETTE[i % HOST_PALETTE.length] }}
            />
            <Link
              to="/admin/tiktok/$handle"
              params={{ handle: r.host }}
              className="shrink-0 text-primary-700 dark:text-primary-300 hover:underline truncate max-w-[7rem]"
            >
              @{r.host}
            </Link>
            <span className="text-gray-500">lvl</span>
            <span className="tabular-nums font-bold text-gray-900">
              {r.member_level ?? '—'}
            </span>
            {r.fans_club_name && (
              <span
                className="ml-auto truncate inline-flex items-center px-1.5 py-0.5 rounded-full bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300 text-[10px]"
                title={`Fan club: ${r.fans_club_name}${r.fans_club_level ? ' L' + r.fans_club_level : ''}`}
              >
                {r.fans_club_name}
                {r.fans_club_level ? ` L${r.fans_club_level}` : ''}
              </span>
            )}
            {r.is_subscribe && (
              <span className="ml-auto inline-flex items-center px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300 text-[10px]">
                SUB
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────
// Tab: Behavior — how they gift (cadence, coupling, PK, anchor tier).
// ────────────────────────────────────────────────────────────────────

function BehaviorTab({
  data,
  tz: _tz,
}: {
  data: TikTokCommonGifterDetail;
  tz: string;
}) {
  return (
    <div className="flex flex-col gap-4">
      {data.coupling && data.coupling.gift_events > 0 && (
        <CouplingPanel c={data.coupling} />
      )}
      {data.streakiness && data.streakiness.total_gift_events > 0 && (
        <StreakinessPanel s={data.streakiness} />
      )}
      {data.ttfg && data.ttfg.rooms_with_both > 0 && (
        <TtfgPanel t={data.ttfg} />
      )}
      {data.whale_sessions && data.whale_sessions.length > 0 && (
        <WhaleSessionsPanel sessions={data.whale_sessions} />
      )}
      {/* PK partisanship — derived from existing match_gifts on host
          slices. Aggregates over all hosts so we can show "what
          % of total gifts were during PKs". */}
      <PkPanel hosts={data.hosts} totalGifts={data.totals.gifts} />
      {data.anchor_hist && data.anchor_hist.length > 0 && (
        <AnchorPanel hist={data.anchor_hist} />
      )}
    </div>
  );
}

function CouplingPanel({
  c,
}: {
  c: NonNullable<TikTokCommonGifterDetail['coupling']>;
}) {
  const character =
    c.coupling_pct >= 60
      ? { label: 'Hype-poster', tone: 'sky' as const, hint: 'comments while paying' }
      : c.coupling_pct >= 25
        ? { label: 'Vocal whale', tone: 'amber' as const, hint: 'sometimes follows gifts with a comment' }
        : { label: 'Silent whale', tone: 'rose' as const, hint: 'pays without saying much' };
  const accentText = {
    sky: 'text-sky-700 dark:text-sky-300',
    amber: 'text-amber-700 dark:text-amber-300',
    rose: 'text-rose-700 dark:text-rose-300',
  }[character.tone];
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <MessageSquare className="w-3.5 h-3.5 text-sky-500" />
        Comment-around-gift coupling
      </div>
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className={`text-2xl font-bold ${accentText}`}>
          {c.coupling_pct.toFixed(1)}%
        </span>
        <span className="text-xs font-mono text-gray-500">
          of {c.gift_events.toLocaleString()} gifts paired with a comment ±60s
        </span>
      </div>
      <div className="mt-1 text-sm">
        <span className={`font-semibold ${accentText}`}>{character.label}</span>
        <span className="text-gray-500"> — {character.hint}</span>
      </div>
    </section>
  );
}

function StreakinessPanel({
  s,
}: {
  s: NonNullable<TikTokCommonGifterDetail['streakiness']>;
}) {
  const character =
    s.streak_event_pct >= 30
      ? { label: 'Smasher', hint: 'lots of multi-hit combos' }
      : s.streak_event_pct >= 10
        ? { label: 'Mixed', hint: 'occasional combos' }
        : { label: 'Sniper', hint: 'one-and-done gifts' };
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Zap className="w-3.5 h-3.5 text-amber-500" />
        Streakiness
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
        <SummaryStat
          icon={<Activity className="w-3.5 h-3.5 text-amber-500" />}
          label="Avg ×"
          value={s.avg_repeat.toFixed(2)}
          accent="amber"
        />
        <SummaryStat
          icon={<TrendingUp className="w-3.5 h-3.5 text-rose-500" />}
          label="Max combo"
          value={`×${s.max_repeat.toLocaleString()}`}
          accent="rose"
        />
        <SummaryStat
          icon={<Gem className="w-3.5 h-3.5 text-sky-500" />}
          label="Combo events"
          value={`${s.streak_event_pct.toFixed(1)}%`}
          accent="sky"
        />
        <SummaryStat
          icon={<GiftIcon className="w-3.5 h-3.5 text-gray-500" />}
          label="Total gift events"
          value={s.total_gift_events.toLocaleString()}
        />
      </div>
      <div className="mt-2 text-xs">
        <span className="font-semibold text-gray-900">{character.label}</span>
        <span className="text-gray-500"> — {character.hint}</span>
      </div>
    </section>
  );
}

function TtfgPanel({
  t,
}: {
  t: NonNullable<TikTokCommonGifterDetail['ttfg']>;
}) {
  const fmtSec = (s: number): string => {
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.round(s / 60)}m`;
    return `${(s / 3600).toFixed(1)}h`;
  };
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Clock className="w-3.5 h-3.5 text-emerald-500" />
        Time to first gift after join
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
        <SummaryStat
          icon={<Clock className="w-3.5 h-3.5 text-emerald-500" />}
          label="Median"
          value={fmtSec(t.median_seconds)}
        />
        <SummaryStat
          icon={<Clock className="w-3.5 h-3.5 text-gray-500" />}
          label="Average"
          value={fmtSec(t.avg_seconds)}
        />
        <SummaryStat
          icon={<Zap className="w-3.5 h-3.5 text-amber-500" />}
          label="Fastest"
          value={fmtSec(t.min_seconds)}
          accent="amber"
        />
        <SummaryStat
          icon={<Radio className="w-3.5 h-3.5 text-primary-500" />}
          label="Rooms"
          value={t.rooms_with_both.toLocaleString()}
          accent="primary"
        />
      </div>
    </section>
  );
}

function WhaleSessionsPanel({
  sessions,
}: {
  sessions: NonNullable<TikTokCommonGifterDetail['whale_sessions']>;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Award className="w-3.5 h-3.5 text-amber-500" />
        Whale density (top sessions by share of room diamonds)
      </div>
      <ul className="flex flex-col gap-1.5 text-xs font-mono">
        {sessions.map((s) => (
          <li
            key={s.room_id || ''}
            className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 sm:gap-2 px-2 py-1.5 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
          >
            <div className="min-w-0 flex-1">
              <div className="text-gray-700 truncate">
                {s.title || `Room ${s.room_id || '—'}`}
              </div>
              <div className="text-[10px] text-gray-500">
                {s.host && (
                  <Link
                    to="/admin/tiktok/$handle"
                    params={{ handle: s.host }}
                    className="text-primary-700 dark:text-primary-300 hover:underline"
                  >
                    @{s.host}
                  </Link>
                )}
                {s.started_at && (
                  <span className="ml-1">{s.started_at.slice(0, 10)}</span>
                )}
              </div>
            </div>
            <span className="flex items-center gap-2 shrink-0">
              <span className="text-amber-700 dark:text-amber-300 tabular-nums font-bold">
                {s.share_pct.toFixed(1)}%
              </span>
              <span className="text-gray-500 tabular-nums">
                {compactCount(s.user_diamonds)} / {compactCount(s.room_diamonds)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function PkPanel({
  hosts,
  totalGifts,
}: {
  hosts: TikTokCommonGifterDetail['hosts'];
  totalGifts: number;
}) {
  const totalMatch = hosts.reduce((a, h) => a + (h.match_gifts ?? 0), 0);
  if (totalMatch === 0 || totalGifts === 0) {
    return (
      <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm text-xs text-gray-500">
        No gifts recorded during PK battles.
      </section>
    );
  }
  const matchPct = (totalMatch / totalGifts) * 100;
  // True partisanship requires `to_user` data — only available in
  // multi-guest / PK lives where TikTokLive populates it. Aggregate
  // the per-host rows that DO have partisanship data.
  const hostsWithPartisanship = hosts.filter((h) => h.pk_partisanship);
  const totalToHost = hostsWithPartisanship.reduce(
    (a, h) => a + (h.pk_partisanship?.to_host_gifts ?? 0), 0,
  );
  const totalToOthers = hostsWithPartisanship.reduce(
    (a, h) => a + (h.pk_partisanship?.to_others_gifts ?? 0), 0,
  );
  const partisanshipKnown = totalToHost + totalToOthers;
  const ranked = [...hosts]
    .filter((h) => (h.match_gifts ?? 0) > 0)
    .sort((a, b) => (b.match_gifts ?? 0) - (a.match_gifts ?? 0))
    .slice(0, 6);
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Zap className="w-3.5 h-3.5 text-purple-500" />
        PK partisanship
      </div>
      {/* Headline: % of all gifts that fired during a PK. */}
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="text-2xl font-bold tabular-nums text-purple-700 dark:text-purple-300">
          {matchPct.toFixed(1)}%
        </span>
        <span className="text-xs font-mono text-gray-500">
          of gifts went out during a PK ({totalMatch.toLocaleString()} of {totalGifts.toLocaleString()})
        </span>
      </div>
      {/* True host-vs-opponent split — only when we have to_user
          data. For solo-PK lives where the lib doesn't populate
          to_user, fall back to "recipient unknown" (silent). */}
      {partisanshipKnown > 0 && (
        <div className="mt-3">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono mb-1">
            Of {partisanshipKnown.toLocaleString()} PK gifts with known recipient
          </div>
          <div className="h-3 w-full rounded-full overflow-hidden flex bg-gray-200 dark:bg-white/10">
            <div
              className="bg-emerald-500"
              style={{ width: `${(totalToHost / partisanshipKnown) * 100}%` }}
              title={`Backed host: ${totalToHost} gifts`}
            />
            <div
              className="bg-rose-500"
              style={{ width: `${(totalToOthers / partisanshipKnown) * 100}%` }}
              title={`Defected to opponent: ${totalToOthers} gifts`}
            />
          </div>
          <div className="mt-1 flex justify-between text-[11px] font-mono">
            <span className="text-emerald-700 dark:text-emerald-300">
              Backed host{' '}
              <span className="tabular-nums">
                {((totalToHost / partisanshipKnown) * 100).toFixed(0)}%
              </span>
            </span>
            <span className="text-rose-700 dark:text-rose-300">
              <span className="tabular-nums">
                {((totalToOthers / partisanshipKnown) * 100).toFixed(0)}%
              </span>{' '}
              defected to opponent
            </span>
          </div>
        </div>
      )}
      {partisanshipKnown === 0 && totalMatch > 0 && (
        <div className="mt-2 text-[11px] font-mono text-gray-500">
          Recipient identity not surfaced by the lib for these PKs —
          host-vs-opponent split is unknown.
        </div>
      )}
      {/* Per-host PK gift volume. */}
      <div className="auth-mono-label mt-3 mb-1">By host</div>
      <ul className="flex flex-col gap-1 text-xs font-mono">
        {ranked.map((h) => {
          const share = totalMatch > 0 ? ((h.match_gifts ?? 0) / totalMatch) * 100 : 0;
          const p = h.pk_partisanship;
          return (
            <li
              key={h.host}
              className="flex flex-wrap items-center gap-x-2 gap-y-0.5 px-2 py-1 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
            >
              <Link
                to="/admin/tiktok/$handle"
                params={{ handle: h.host }}
                className="shrink-0 text-primary-700 dark:text-primary-300 hover:underline"
              >
                @{h.host}
              </Link>
              <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-white/10 overflow-hidden min-w-[60px]">
                <div className="h-full bg-purple-500" style={{ width: `${share}%` }} />
              </div>
              <span className="shrink-0 text-purple-700 dark:text-purple-300 tabular-nums">
                {(h.match_gifts ?? 0).toLocaleString()}
              </span>
              <span className="shrink-0 text-gray-500 tabular-nums w-12 text-right">
                {share.toFixed(0)}%
              </span>
              {p && (p.to_host_gifts + p.to_others_gifts) > 0 && (
                <span className="basis-full sm:basis-auto text-[10px] text-gray-500">
                  {p.to_host_pct.toFixed(0)}% host /{' '}
                  <span className="text-rose-600 dark:text-rose-400">
                    {p.to_others_pct.toFixed(0)}% opp
                  </span>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function AnchorPanel({
  hist,
}: {
  hist: NonNullable<TikTokCommonGifterDetail['anchor_hist']>;
}) {
  const max = Math.max(...hist.map((h) => h.gifts), 1);
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Award className="w-3.5 h-3.5 text-emerald-500" />
        Host tier (anchor_level) distribution
      </div>
      <ul className="flex flex-col gap-1 text-xs font-mono">
        {hist.map((b) => {
          const pct = (b.gifts / max) * 100;
          return (
            <li key={b.anchor_level} className="flex items-center gap-2">
              <span className="shrink-0 text-gray-500 w-10 tabular-nums text-right">
                lvl {b.anchor_level}
              </span>
              <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-white/10 overflow-hidden">
                <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
              </div>
              <span className="shrink-0 text-gray-700 tabular-nums w-16 text-right">
                {b.gifts.toLocaleString()}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function RankPanel({
  rank,
}: {
  rank: NonNullable<TikTokCommonGifterDetail['rank']>;
}) {
  // Percentile is "% of pool this user beats". rank=1 → 100%.
  const pct = (r: number) =>
    rank.pool_size > 1
      ? Math.max(0, Math.round((1 - (r - 1) / rank.pool_size) * 100))
      : 100;
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Award className="w-3.5 h-3.5 text-amber-500" />
        Rank among common gifters
        <span className="text-gray-500 font-mono normal-case">
          (pool of {rank.pool_size.toLocaleString()})
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs font-mono">
        <RankCell
          label="Diamonds"
          rank={rank.by_diamonds}
          pool={rank.pool_size}
          pct={pct(rank.by_diamonds)}
          accent="amber"
        />
        <RankCell
          label="Hosts"
          rank={rank.by_host_count}
          pool={rank.pool_size}
          pct={pct(rank.by_host_count)}
          accent="primary"
        />
        <RankCell
          label="Gifts"
          rank={rank.by_gifts}
          pool={rank.pool_size}
          pct={pct(rank.by_gifts)}
          accent="rose"
        />
      </div>
    </section>
  );
}

function RankCell({
  label,
  rank,
  pool,
  pct,
  accent,
}: {
  label: string;
  rank: number;
  pool: number;
  pct: number;
  accent: 'amber' | 'primary' | 'rose';
}) {
  const accentText =
    accent === 'amber'
      ? 'text-amber-700 dark:text-amber-300'
      : accent === 'primary'
        ? 'text-primary-700 dark:text-primary-300'
        : 'text-rose-700 dark:text-rose-300';
  const accentBar =
    accent === 'amber'
      ? 'bg-amber-500'
      : accent === 'primary'
        ? 'bg-primary-500'
        : 'bg-rose-500';
  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500">
        {label}
      </div>
      <div className={`mt-0.5 font-bold tabular-nums ${accentText}`}>
        #{rank.toLocaleString()}
        <span className="text-gray-500 font-normal text-[11px]">
          {' '}
          / {pool.toLocaleString()}
        </span>
      </div>
      <div className="mt-1 h-1 w-full rounded-full bg-gray-200 dark:bg-white/10 overflow-hidden">
        <div
          className={`h-full ${accentBar}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-0.5 text-[10px] text-gray-500 tabular-nums">
        Top {(100 - pct).toFixed(0)}%
      </div>
    </div>
  );
}

function BehaviorPanel({
  behavior,
  totalGifts,
  totalDiamonds,
}: {
  behavior: Record<string, number>;
  totalGifts: number;
  totalDiamonds: number;
}) {
  // Stable order across users so the bar reads consistently.
  const ORDER = [
    { key: 'gift', label: 'Gifts', color: 'bg-amber-500' },
    { key: 'comment', label: 'Comments', color: 'bg-sky-500' },
    { key: 'join', label: 'Joins', color: 'bg-emerald-500' },
    { key: 'like', label: 'Likes', color: 'bg-rose-500' },
    { key: 'share', label: 'Shares', color: 'bg-purple-500' },
    { key: 'follow', label: 'Follows', color: 'bg-pink-500' },
  ];
  const total = Object.values(behavior).reduce((a, b) => a + b, 0);
  const slices = ORDER.map((s) => ({
    ...s,
    n: behavior[s.key] ?? 0,
    pct: total > 0 ? ((behavior[s.key] ?? 0) / total) * 100 : 0,
  })).filter((s) => s.n > 0);
  const otherN = total - slices.reduce((a, s) => a + s.n, 0);
  if (otherN > 0) {
    slices.push({
      key: 'other',
      label: 'Other',
      color: 'bg-gray-400',
      n: otherN,
      pct: (otherN / total) * 100,
    });
  }
  const avgPerGift = totalGifts > 0 ? Math.round(totalDiamonds / totalGifts) : 0;

  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      {/* Persona pill removed — promoted to the hero header so the
          eye lands on it before any per-section chrome. */}
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Activity className="w-3.5 h-3.5 text-sky-500" />
        Behavioural mix
      </div>
      {/* Stacked horizontal bar — the persona at a glance. */}
      <div className="h-3 w-full rounded-full overflow-hidden flex bg-gray-200 dark:bg-white/10">
        {slices.map((s) => (
          <div
            key={s.key}
            className={s.color}
            style={{ width: `${s.pct}%` }}
            title={`${s.label}: ${s.n.toLocaleString()} (${s.pct.toFixed(1)}%)`}
          />
        ))}
      </div>
      {/* Legend rows. */}
      <ul className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-1 text-xs font-mono">
        {slices.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span className={`inline-block w-2 h-2 rounded-full ${s.color}`} />
            <span className="text-gray-500">{s.label}</span>
            <span className="ml-auto tabular-nums text-gray-700">
              {s.n.toLocaleString()}
            </span>
            <span className="text-[10px] text-gray-400 tabular-nums w-10 text-right">
              {s.pct.toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
      {avgPerGift > 0 && (
        <div className="mt-2 text-[11px] text-gray-500 font-mono">
          Avg{' '}
          <span className="text-amber-700 dark:text-amber-300 inline-flex items-baseline gap-0.5">
            <Gem className="w-3 h-3 self-center" />
            {avgPerGift.toLocaleString()}
          </span>{' '}
          per gift action.
        </div>
      )}
    </section>
  );
}

function IntensityPanel({
  intensity,
}: {
  intensity: NonNullable<TikTokCommonGifterDetail['intensity']>;
}) {
  const bs = intensity.biggest_session;
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-3">
        <Flame className="w-3.5 h-3.5 text-rose-500" />
        Spending intensity
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono mb-3">
        <SummaryStat
          icon={<Activity className="w-3.5 h-3.5 text-emerald-500" />}
          label="Active days"
          value={(intensity.active_days ?? 0).toLocaleString()}
        />
        <SummaryStat
          icon={<TrendingUp className="w-3.5 h-3.5 text-primary-500" />}
          label="Longest streak"
          value={`${intensity.longest_streak_days ?? 0}d`}
          accent="primary"
        />
        <SummaryStat
          icon={<Clock className="w-3.5 h-3.5 text-gray-500" />}
          label="Longest gap"
          value={`${intensity.longest_gap_days ?? 0}d`}
        />
        <SummaryStat
          icon={<Calendar className="w-3.5 h-3.5 text-gray-500" />}
          label="First active"
          value={
            intensity.first_active_day
              ? intensity.first_active_day.slice(0, 10)
              : '—'
          }
        />
      </div>
      {bs && bs.diamonds > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/30 px-3 py-2 text-xs font-mono">
          <div className="text-[10px] uppercase tracking-wider text-amber-700 dark:text-amber-300 mb-0.5">
            Biggest single-room session
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-gray-700">
              {bs.title || `Room ${bs.room_id ?? '—'}`}
              {bs.host && (
                <span className="ml-1 text-gray-500">@{bs.host}</span>
              )}
            </span>
            <span className="shrink-0 text-amber-700 dark:text-amber-300 tabular-nums font-bold inline-flex items-baseline gap-0.5">
              <Gem className="w-3.5 h-3.5 self-center" />
              {bs.diamonds.toLocaleString()}
              <span className="ml-1 text-gray-500 font-normal">
                · {bs.gifts.toLocaleString()} gifts
              </span>
            </span>
          </div>
        </div>
      )}
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────
// Tab: Hosts — list of host cards with a small toolbar for search /
// sort / filter (purely client-side over the already-loaded array).
// ────────────────────────────────────────────────────────────────────

type HostsSort = 'diamonds' | 'gifts' | 'recent' | 'attendance' | 'comments';

function HostsTab({
  data,
  userId,
}: {
  data: TikTokCommonGifterDetail;
  userId: string | null;
}) {
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<HostsSort>('diamonds');
  const [withCommentsOnly, setWithCommentsOnly] = useState(false);
  const [messageQ, setMessageQ] = useState('');

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let arr = data.hosts.slice();
    if (needle) arr = arr.filter((h) => h.host.toLowerCase().includes(needle));
    if (withCommentsOnly) arr = arr.filter((h) => h.comment_count > 0);
    arr.sort((a, b) => {
      switch (sort) {
        case 'gifts':      return b.gifts - a.gifts;
        case 'comments':   return b.comment_count - a.comment_count;
        case 'attendance': return (b.attendance_pct ?? 0) - (a.attendance_pct ?? 0);
        case 'recent': {
          const at = a.last_seen_at ? new Date(a.last_seen_at).getTime() : 0;
          const bt = b.last_seen_at ? new Date(b.last_seen_at).getTime() : 0;
          return bt - at;
        }
        case 'diamonds':
        default:           return b.diamonds - a.diamonds;
      }
    });
    return arr;
  }, [data.hosts, q, sort, withCommentsOnly]);

  return (
    <div className="flex flex-col gap-3">
      {/* Toolbar — only renders when there are 3+ hosts. With 1–2
          hosts, search/sort is noise. */}
      {data.hosts.length >= 3 && (
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter hosts…"
            className="px-2.5 py-1 text-xs font-mono rounded border border-gray-200 bg-white dark:bg-white/5 placeholder:text-gray-400"
          />
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as HostsSort)}
            className="px-2 py-1 text-xs font-mono rounded border border-gray-200 bg-white dark:bg-white/5"
            title="Sort hosts by…"
          >
            <option value="diamonds">Sort: Diamonds</option>
            <option value="gifts">Sort: Gifts</option>
            <option value="comments">Sort: Comments</option>
            <option value="attendance">Sort: Attendance %</option>
            <option value="recent">Sort: Recent activity</option>
          </select>
          <label className="inline-flex items-center gap-1.5 text-[11px] font-mono text-gray-700 cursor-pointer">
            <input
              type="checkbox"
              checked={withCommentsOnly}
              onChange={(e) => setWithCommentsOnly(e.target.checked)}
              className="accent-primary-500"
            />
            With comments only
          </label>
          <input
            type="text"
            value={messageQ}
            onChange={(e) => setMessageQ(e.target.value)}
            placeholder="Search messages…"
            className="ml-auto px-2.5 py-1 text-xs font-mono rounded border border-gray-200 bg-white dark:bg-white/5 placeholder:text-gray-400 w-full sm:w-56"
            title="Search across this user's comments to any host. Applied per-host card when expanded."
          />
        </div>
      )}
      {filtered.length === 0 ? (
        <p className="text-xs text-gray-500 py-3 text-center">
          No hosts match the current filters.
        </p>
      ) : (
        filtered.map((h) => (
          <HostCard
            key={h.host}
            host={h}
            totalDiamonds={data.totals.diamonds}
            userId={userId}
            messageQ={messageQ}
          />
        ))
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Tab: Activity Timeline — answers "WHEN do they show up?" with a
// hour×dow heatmap, a stacked daily area, and a cumulative line.
// ────────────────────────────────────────────────────────────────────

function TimelineTab({
  data,
  tz,
  onPickHour,
}: {
  data: TikTokCommonGifterDetail;
  tz: string;
  /** Heatmap-cell click handler — passes (dow, hour) up to the modal
   *  which jumps to the Network tab with a pre-applied filter. */
  onPickHour?: (dow: number, hour: number) => void;
}) {
  // Hosts the user has chosen to hide from the three panels. Pure
  // client-side filter — the data is already loaded.
  const [hiddenHosts, setHiddenHosts] = useState<Set<string>>(() => new Set());

  const hostsInData = useMemo(() => {
    const set = new Set<string>();
    if (data.daily_series) {
      for (const p of data.daily_series) if (p.host) set.add(p.host);
    }
    return Array.from(set);
  }, [data.daily_series]);

  const filteredSeries = useMemo(() => {
    if (!data.daily_series) return undefined;
    if (hiddenHosts.size === 0) return data.daily_series;
    return data.daily_series.filter((p) => !hiddenHosts.has(p.host));
  }, [data.daily_series, hiddenHosts]);

  const toggleHost = (h: string) =>
    setHiddenHosts((prev) => {
      const next = new Set(prev);
      if (next.has(h)) next.delete(h);
      else next.add(h);
      return next;
    });

  return (
    <div className="flex flex-col gap-4">
      {hostsInData.length >= 2 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[10px] uppercase tracking-wider text-gray-500 font-mono self-center mr-1">
            Show:
          </span>
          {hostsInData.map((h, i) => {
            const hidden = hiddenHosts.has(h);
            const color = HOST_PALETTE[i % HOST_PALETTE.length];
            return (
              <button
                key={h}
                type="button"
                onClick={() => toggleHost(h)}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono border transition-colors ${
                  hidden
                    ? 'border-gray-200 text-gray-400 line-through opacity-50 hover:opacity-80'
                    : 'border-gray-300 text-gray-700 hover:border-gray-400'
                }`}
                title={hidden ? `Show @${h}` : `Hide @${h}`}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: color }}
                />
                @{h}
              </button>
            );
          })}
        </div>
      )}
      {data.heatmap && data.heatmap.length > 0 && (
        <HeatmapPanel cells={data.heatmap} onPickHour={onPickHour} />
      )}
      {filteredSeries && filteredSeries.length > 0 && (
        <DailyStackPanel points={filteredSeries} tz={tz} />
      )}
      {filteredSeries && filteredSeries.length > 0 && (
        <CumulativePanel points={filteredSeries} />
      )}
    </div>
  );
}

const DOW_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function HeatmapPanel({
  cells,
  onPickHour,
}: {
  cells: NonNullable<TikTokCommonGifterDetail['heatmap']>;
  onPickHour?: (dow: number, hour: number) => void;
}) {
  // Index cells by (dow, hour) for quick lookup.
  const byKey = useMemo(() => {
    const m = new Map<string, { gifts: number; diamonds: number }>();
    for (const c of cells) m.set(`${c.dow}:${c.hour}`, c);
    return m;
  }, [cells]);
  const maxDiamonds = useMemo(
    () => Math.max(0, ...cells.map((c) => c.diamonds)),
    [cells],
  );

  // Bucket the diamonds into 5 intensity levels (gray for 0; amber
  // ramp 1–5). Logarithmic-ish via square root so a few large values
  // don't wash out the rest.
  const levelFor = (d: number): number => {
    if (d <= 0) return 0;
    if (maxDiamonds <= 0) return 0;
    const ratio = Math.sqrt(d / maxDiamonds);
    if (ratio >= 0.85) return 5;
    if (ratio >= 0.6) return 4;
    if (ratio >= 0.4) return 3;
    if (ratio >= 0.2) return 2;
    return 1;
  };
  // Monotonically darker/more-saturated as the level increases. The
  // dark-mode opacities used to *decrease* between level 4 and 5
  // because the higher level switched to amber-400 base — that
  // inverts the gradient. Now both modes step up cleanly.
  const LEVEL_COLOR = [
    'bg-gray-100 dark:bg-white/[0.04]',
    'bg-amber-100 dark:bg-amber-500/[0.20]',
    'bg-amber-200 dark:bg-amber-500/[0.40]',
    'bg-amber-300 dark:bg-amber-500/[0.60]',
    'bg-amber-500 dark:bg-amber-500/[0.80]',
    'bg-amber-600 dark:bg-amber-400',
  ];

  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-3">
        <Clock className="w-3.5 h-3.5 text-amber-500" />
        When do they gift? (hour × day-of-week)
      </div>
      {/* 7 rows × 24 cols, ~14px squares. Pull the scroll container
          to the section's edges with negative margins so it escapes
          the `p-4` padding on narrow viewports — otherwise the grid
          gets clipped by the inner padding instead of becoming
          horizontally scrollable. */}
      <div className="-mx-4 px-4 overflow-x-auto">
        <div className="inline-grid gap-[2px]"
             style={{ gridTemplateColumns: 'auto repeat(24, 14px)' }}>
          {/* Header row: hour numbers. */}
          <div />
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={`h-${h}`}
              className="text-[8px] text-gray-400 font-mono text-center"
            >
              {h % 6 === 0 ? h : ''}
            </div>
          ))}
          {/* 7 rows. */}
          {DOW_LABELS.map((label, dow) => (
            <RowFragment
              key={label}
              dow={dow}
              label={label}
              byKey={byKey}
              levelFor={levelFor}
              LEVEL_COLOR={LEVEL_COLOR}
              onPickHour={onPickHour}
            />
          ))}
        </div>
      </div>
      {/* Legend. */}
      <div className="mt-2 flex items-center gap-1.5 text-[10px] font-mono text-gray-500">
        <span>Less</span>
        {LEVEL_COLOR.map((c, i) => (
          <span key={i} className={`w-3 h-3 rounded-sm ${c} border border-gray-200 dark:border-white/10`} />
        ))}
        <span>More</span>
      </div>
    </section>
  );
}

// React doesn't allow returning a Fragment containing siblings inline
// in a grid template without a wrapper-keyed parent — broken into a
// small component so each cell row keeps its own key namespace.
function RowFragment({
  dow,
  label,
  byKey,
  levelFor,
  LEVEL_COLOR,
  onPickHour,
}: {
  dow: number;
  label: string;
  byKey: Map<string, { gifts: number; diamonds: number }>;
  levelFor: (d: number) => number;
  LEVEL_COLOR: string[];
  onPickHour?: (dow: number, hour: number) => void;
}) {
  return (
    <>
      <div className="text-[10px] text-gray-500 font-mono pr-1.5 self-center">
        {label}
      </div>
      {Array.from({ length: 24 }, (_, h) => {
        const cell = byKey.get(`${dow}:${h}`);
        const lvl = cell ? levelFor(cell.diamonds) : 0;
        const title = cell
          ? `${label} ${h}:00 — ${cell.gifts} gifts · ${cell.diamonds.toLocaleString()} 💎\nClick to drill into Network feed`
          : `${label} ${h}:00 — no activity`;
        const hasActivity = !!cell;
        // Cells with activity are clickable: hand the (dow, hour)
        // pair up so the modal can pivot to the Network tab pre-
        // filtered to that hour band. Empty cells stay non-clickable
        // so we don't trap the user in a "no events" state.
        return hasActivity && onPickHour ? (
          <button
            type="button"
            key={`c-${dow}-${h}`}
            onClick={() => onPickHour(dow, h)}
            className={`w-[14px] h-[14px] rounded-[2px] ${LEVEL_COLOR[lvl]} border border-gray-200/60 dark:border-white/10 hover:ring-2 hover:ring-primary-400 transition-shadow cursor-pointer`}
            title={title}
            aria-label={title}
          />
        ) : (
          <div
            key={`c-${dow}-${h}`}
            className={`w-[14px] h-[14px] rounded-[2px] ${LEVEL_COLOR[lvl]} border border-gray-200/60 dark:border-white/10`}
            title={title}
          />
        );
      })}
    </>
  );
}

const HOST_PALETTE = [
  '#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6',
  '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16',
];

function DailyStackPanel({
  points,
  tz: _tz,
}: {
  points: NonNullable<TikTokCommonGifterDetail['daily_series']>;
  tz: string;
}) {
  const isDark = useDarkMode();
  const t = chartTheme(isDark);
  // Pivot into per-host series indexed by day.
  const { days, hosts, byHost } = useMemo(() => {
    const dayMap = new Map<string, true>();
    const hostMap = new Map<string, true>();
    for (const p of points) {
      if (p.day) dayMap.set(p.day.slice(0, 10), true);
      if (p.host) hostMap.set(p.host, true);
    }
    const days = Array.from(dayMap.keys()).sort();
    const hosts = Array.from(hostMap.keys());
    const byHost = new Map<string, Map<string, number>>();
    for (const h of hosts) byHost.set(h, new Map());
    for (const p of points) {
      const d = p.day?.slice(0, 10);
      if (!d || !p.host) continue;
      byHost.get(p.host)!.set(d, p.diamonds);
    }
    return { days, hosts, byHost };
  }, [points]);

  const option = useMemo(() => {
    const series = hosts.map((h, i) => ({
      name: `@${h}`,
      type: 'line',
      stack: 'total',
      areaStyle: { opacity: 0.7 },
      symbol: 'none',
      smooth: true,
      lineStyle: { width: 1 },
      color: HOST_PALETTE[i % HOST_PALETTE.length],
      data: days.map((d) => byHost.get(h)?.get(d) ?? 0),
    }));
    return {
      grid: { left: 48, right: 12, top: 36, bottom: 22 },
      tooltip: { trigger: 'axis' },
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: {
          fontSize: 10,
          fontFamily: 'JetBrains Mono Variable',
          color: t.legendText,
        },
        pageTextStyle: { color: t.legendText },
        pageIconColor: t.axisLabel,
      },
      xAxis: {
        type: 'category',
        data: days,
        axisLabel: { fontSize: 9, color: t.axisLabel },
        axisLine: { lineStyle: { color: t.axisLine } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontSize: 9,
          color: t.axisLabel,
          formatter: (v: number) => v.toLocaleString(),
        },
        splitLine: { lineStyle: { color: t.splitLine } },
      },
      series,
    };
  }, [days, hosts, byHost, t.axisLabel, t.axisLine, t.splitLine, t.legendText]);

  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <TrendingUp className="w-3.5 h-3.5 text-emerald-500" />
        Daily diamonds (last 90 days, stacked by host)
      </div>
      <ReactECharts
        echarts={echarts}
        option={option}
        style={{ height: 280, minHeight: 240 }}
        notMerge
        lazyUpdate
      />
    </section>
  );
}

function CumulativePanel({
  points,
}: {
  points: NonNullable<TikTokCommonGifterDetail['daily_series']>;
}) {
  const isDark = useDarkMode();
  const t = chartTheme(isDark);
  const { days, hosts, cumByHost } = useMemo(() => {
    const dayMap = new Map<string, true>();
    const hostMap = new Map<string, true>();
    for (const p of points) {
      if (p.day) dayMap.set(p.day.slice(0, 10), true);
      if (p.host) hostMap.set(p.host, true);
    }
    const days = Array.from(dayMap.keys()).sort();
    const hosts = Array.from(hostMap.keys());
    const byHost = new Map<string, Map<string, number>>();
    for (const h of hosts) byHost.set(h, new Map());
    for (const p of points) {
      const d = p.day?.slice(0, 10);
      if (!d || !p.host) continue;
      byHost.get(p.host)!.set(d, p.diamonds);
    }
    // Build running totals per host.
    const cumByHost = new Map<string, number[]>();
    for (const h of hosts) {
      const arr: number[] = [];
      let running = 0;
      for (const d of days) {
        running += byHost.get(h)?.get(d) ?? 0;
        arr.push(running);
      }
      cumByHost.set(h, arr);
    }
    return { days, hosts, cumByHost };
  }, [points]);

  const option = useMemo(() => {
    const series = hosts.map((h, i) => ({
      name: `@${h}`,
      type: 'line',
      symbol: 'none',
      smooth: true,
      lineStyle: { width: 1.5 },
      color: HOST_PALETTE[i % HOST_PALETTE.length],
      data: cumByHost.get(h) ?? [],
    }));
    return {
      grid: { left: 48, right: 12, top: 36, bottom: 22 },
      tooltip: { trigger: 'axis' },
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: {
          fontSize: 10,
          fontFamily: 'JetBrains Mono Variable',
          color: t.legendText,
        },
        pageTextStyle: { color: t.legendText },
        pageIconColor: t.axisLabel,
      },
      xAxis: {
        type: 'category',
        data: days,
        axisLabel: { fontSize: 9, color: t.axisLabel },
        axisLine: { lineStyle: { color: t.axisLine } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontSize: 9,
          color: t.axisLabel,
          formatter: (v: number) => v.toLocaleString(),
        },
        splitLine: { lineStyle: { color: t.splitLine } },
      },
      series,
    };
  }, [days, hosts, cumByHost, t.axisLabel, t.axisLine, t.splitLine, t.legendText]);

  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Activity className="w-3.5 h-3.5 text-primary-500" />
        Cumulative diamonds per host
        <span className="ml-2 text-gray-500 font-mono normal-case">
          (when did they "lock in" to each creator?)
        </span>
      </div>
      <ReactECharts
        echarts={echarts}
        option={option}
        style={{ height: 260, minHeight: 220 }}
        notMerge
        lazyUpdate
      />
    </section>
  );
}

// ────────────────────────────────────────────────────────────────────
// Tab: Comments — every comment this user has made across every host.
// Per-host comment lists already exist on the Hosts tab; this is the
// global view with full text, search, host scope, and pagination.
// ────────────────────────────────────────────────────────────────────

function CommentsTab({
  data,
  userId,
  tz,
}: {
  data: TikTokCommonGifterDetail;
  userId: string | null;
  tz: string;
}) {
  const PAGE_SIZES = [25, 50, 100, 250];
  const [hostFilter, setHostFilter] = useState<string>('all');
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<TikTokEvent[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  // Debounce free-text → 250ms.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  // Reset paging on filter change.
  useEffect(() => {
    setPage(0);
    setTotal(null);
  }, [hostFilter, debouncedQ, pageSize, userId]);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    setLoading(true);
    const handle = hostFilter !== 'all' ? hostFilter : undefined;
    Promise.all([
      tiktokApi.searchEvents({
        user_id: userId,
        type: 'comment',
        handle,
        q: debouncedQ || undefined,
        limit: pageSize,
        offset: page * pageSize,
      }),
      total === null
        ? tiktokApi.countEvents({
            user_id: userId,
            type: 'comment',
            handle,
            q: debouncedQ || undefined,
          })
        : Promise.resolve({ total }),
    ])
      .then(([rows, c]) => {
        if (cancelled) return;
        setItems(rows);
        setTotal(c.total ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, hostFilter, debouncedQ, pageSize, page]);

  // Distinct hosts the user has commented on, derived from the
  // already-loaded host list. Drives the host-filter chips.
  const hostOptions = useMemo(
    () => data.hosts.filter((h) => h.comment_count > 0),
    [data.hosts],
  );

  const realTotal = total ?? 0;
  const totalPages = Math.max(1, Math.ceil(realTotal / pageSize));
  const offset = page * pageSize;
  const showingFrom = realTotal === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + items.length, realTotal);

  return (
    <div className="flex flex-col gap-3">
      {/* Filter toolbar — host scope + free-text + page size. */}
      <div className="flex flex-col gap-2">
        {hostOptions.length >= 2 && (
          <div className="flex flex-wrap items-center gap-1">
            <button
              type="button"
              onClick={() => setHostFilter('all')}
              className={`shrink-0 inline-flex items-center px-2 py-1 rounded-full text-[11px] font-mono transition-colors border ${
                hostFilter === 'all'
                  ? 'bg-primary-100 dark:bg-primary-500/20 border-primary-300 text-primary-700 dark:text-primary-300'
                  : 'bg-white dark:bg-white/5 border-gray-200 text-gray-700 hover:border-gray-300'
              }`}
            >
              All hosts
              <span className="ml-1 opacity-70 tabular-nums">
                {data.totals.comment_count.toLocaleString()}
              </span>
            </button>
            {hostOptions.map((h) => (
              <button
                key={h.host}
                type="button"
                onClick={() => setHostFilter(h.host)}
                className={`shrink-0 inline-flex items-center px-2 py-1 rounded-full text-[11px] font-mono transition-colors border ${
                  hostFilter === h.host
                    ? 'bg-primary-100 dark:bg-primary-500/20 border-primary-300 text-primary-700 dark:text-primary-300'
                    : 'bg-white dark:bg-white/5 border-gray-200 text-gray-700 hover:border-gray-300'
                }`}
              >
                @{h.host}
                <span className="ml-1 opacity-70 tabular-nums">
                  {h.comment_count.toLocaleString()}
                </span>
              </button>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search comment text…"
              className="w-full pl-8 pr-2 py-1.5 text-sm rounded border border-gray-200 bg-white focus:outline-none focus:ring-1 focus:ring-sky-400 focus:border-sky-400"
            />
          </div>
          <label className="text-[11px] font-mono text-gray-500 inline-flex items-center gap-1.5">
            Page size
            <select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="font-mono text-[11px] py-0.5 pl-1 pr-1 rounded border border-gray-200 bg-white"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <span className="text-[11px] font-mono text-gray-500 tabular-nums">
            {loading ? (
              <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
            ) : null}
            {realTotal === 0
              ? '0 comments'
              : `${showingFrom.toLocaleString()}–${showingTo.toLocaleString()} of ${realTotal.toLocaleString()}`}
          </span>
        </div>
      </div>

      {/* Comment list. Full text, no clamp — that's the whole point
          of having a dedicated tab. */}
      {items.length === 0 && !loading ? (
        <p className="py-6 text-center text-xs text-gray-500">
          {debouncedQ
            ? 'No comments match that search.'
            : hostFilter !== 'all'
              ? `No comments to @${hostFilter} yet.`
              : 'No comments captured yet.'}
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {items.map((e) => {
            const p = (e.payload || {}) as Record<string, unknown>;
            const text = String(p.text ?? '');
            const userBlob = (p.user as Record<string, unknown> | undefined) || {};
            const identity = (userBlob.identity as IdentityBlock | undefined) || null;
            // Resolve the host for this comment from the already-
            // loaded hosts list — `e.room_id` is what we have, and
            // we can match against host_total_rooms or fall back
            // to the active host filter.
            const host = hostFilter !== 'all' ? hostFilter : null;
            return (
              <li
                key={e.id}
                className="px-3 py-2 rounded border border-gray-200 bg-white dark:bg-white/[0.02]"
              >
                <div className="flex items-baseline gap-2 flex-wrap mb-1">
                  <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded font-mono text-[9px] uppercase tracking-wider bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300">
                    <MessageSquare className="w-2.5 h-2.5 mr-0.5" />
                    Comment
                  </span>
                  {host && (
                    <Link
                      to="/admin/tiktok/$handle"
                      params={{ handle: host }}
                      className="text-[11px] font-mono text-primary-700 dark:text-primary-300 hover:underline"
                      title={`Open @${host}`}
                    >
                      @{host}
                    </Link>
                  )}
                  {identity && (
                    <TikTokUserBadges identity={identity} />
                  )}
                  <span className="ml-auto text-[10px] font-mono text-gray-400 tabular-nums">
                    {fmtMonthDayTime(e.ts, tz)}
                  </span>
                </div>
                <p className="text-sm text-gray-700 break-words whitespace-pre-wrap">
                  {text || (
                    <span className="italic text-gray-400">(empty)</span>
                  )}
                </p>
              </li>
            );
          })}
        </ul>
      )}

      {/* Pagination strip. */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-gray-500">
          <span>
            Page {page + 1} / {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={page === 0 || loading}
              onClick={() => setPage(0)}
              className="inline-flex items-center justify-center w-7 h-7 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
              aria-label="First page"
            >
              ‹‹
            </button>
            <button
              type="button"
              disabled={page === 0 || loading}
              onClick={() => setPage(page - 1)}
              className="inline-flex items-center justify-center w-7 h-7 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              disabled={page >= totalPages - 1 || loading}
              onClick={() => setPage(page + 1)}
              className="inline-flex items-center justify-center w-7 h-7 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
              aria-label="Next page"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              disabled={page >= totalPages - 1 || loading}
              onClick={() => setPage(totalPages - 1)}
              className="inline-flex items-center justify-center w-7 h-7 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
              aria-label="Last page"
            >
              ››
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Tab: Network & Feed — co-gifters and recent activity feed.
// ────────────────────────────────────────────────────────────────────

function NetworkTab({
  data,
  tz,
  userId,
  seed,
  onSeedConsumed,
}: {
  data: TikTokCommonGifterDetail;
  tz: string;
  /** Precision-preserved user_id string. `data.user_id` is a JS
   *  Number that lost trailing digits — never send that one out to
   *  the API. */
  userId: string | null;
  /** Optional handoff from another tab (e.g. heatmap-cell click).
   *  Applied once on mount or when the seed changes; cleared via
   *  `onSeedConsumed` so re-renders don't re-apply. */
  seed?: NetworkSeed | null;
  onSeedConsumed?: () => void;
}) {
  // Filter state for the activity feed. When all chips are inactive
  // and `q` is empty, we render the 100 events that came on the
  // detail payload (free, no extra round-trip). Any active filter
  // triggers a refetch via searchEvents.
  const ALL_TYPES: { id: string; label: string }[] = [
    { id: 'gift', label: 'gift' },
    { id: 'comment', label: 'comment' },
    { id: 'join', label: 'join' },
    { id: 'like', label: 'like' },
    { id: 'share', label: 'share' },
    { id: 'follow', label: 'follow' },
  ];
  const [activeTypes, setActiveTypes] = useState<Set<string>>(() =>
    seed?.type ? new Set([seed.type]) : new Set(),
  );
  const [hostFilter, setHostFilter] = useState<string>('');
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  // Hour-band post-filter applied client-side after the searchEvents
  // round-trip — backend has no `dow`/`hour` param. Stays null when
  // no seed is active.
  const [hourBand, setHourBand] = useState<{ dow: number; hour: number } | null>(
    seed && seed.dow != null && seed.hour != null
      ? { dow: seed.dow, hour: seed.hour }
      : null,
  );

  // Apply seed once when it arrives. The parent clears it via
  // `onSeedConsumed` so a stale seed doesn't override user-driven
  // filter changes.
  useEffect(() => {
    if (!seed) return;
    if (seed.type) setActiveTypes(new Set([seed.type]));
    if (seed.dow != null && seed.hour != null) {
      setHourBand({ dow: seed.dow, hour: seed.hour });
    }
    onSeedConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  // Debounce free-text → 250ms.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const filtersActive =
    activeTypes.size > 0 ||
    hostFilter !== '' ||
    debouncedQ !== '' ||
    hourBand !== null;

  const [filteredItems, setFilteredItems] = useState<
    TikTokCommonGifterDetail['recent_activity'] | null
  >(null);
  const [filteredTotal, setFilteredTotal] = useState<number | null>(null);
  const [filterLoading, setFilterLoading] = useState(false);
  // Paged view for the filtered list. `searchEvents` doesn't return
  // host inline (we resolve it via `roomHostMap` below); we use its
  // `offset` param to walk pages of 50.
  const PAGE_SIZE = 50;
  const [page, setPage] = useState(0);

  // Reset back to page 1 whenever the filter inputs change. Without
  // this, switching filters can leave the user stranded on page 8
  // of a different result set.
  useEffect(() => {
    setPage(0);
  }, [activeTypes, hostFilter, debouncedQ, hourBand]);

  // Room → host map. `searchEvents` returns `room_id` but not
  // `host_unique_id`, so we'd render the per-gift "@host" link as
  // null on every filtered row. The detail payload already lists
  // each host's rooms, so we have everything needed for a cheap
  // client-side resolution.
  const roomHostMap = useMemo<Map<string, string>>(() => {
    const m = new Map<string, string>();
    for (const h of data.hosts) {
      for (const r of h.rooms) {
        m.set(String(r.room_id), h.host);
      }
    }
    return m;
  }, [data]);

  useEffect(() => {
    if (!filtersActive) {
      setFilteredItems(null);
      setFilteredTotal(null);
      return;
    }
    let cancelled = false;
    setFilterLoading(true);
    const typeStr = activeTypes.size === 1 ? Array.from(activeTypes)[0] : undefined;
    // Hour-band needs a wide window because the heatmap's (dow, hour)
    // pair is filtered client-side after the fetch; without enough
    // raw rows, an older bucket wouldn't surface. We still paginate
    // through that wider set 50 rows at a time, so the network cost
    // is bounded by `PAGE_SIZE` regardless.
    const hourBandActive = hourBand !== null;
    const since = hourBandActive
      ? new Date(Date.now() - 90 * 86_400_000).toISOString()
      : undefined;
    // For non-hour-band filters: paginate cleanly via offset. For
    // hour-band: fetch a single broader window once and client-page
    // (post-filter discards most rows, so server offset is meaningless).
    const fetchLimit = hourBandActive ? 2000 : PAGE_SIZE;
    const offset = hourBandActive ? 0 : page * PAGE_SIZE;
    Promise.all([
      tiktokApi.searchEvents({
        user_id: userId ?? String(data.user_id),
        handle: hostFilter || undefined,
        type: typeStr,
        q: debouncedQ || undefined,
        since,
        limit: fetchLimit,
        offset,
      }),
      tiktokApi.countEvents({
        user_id: userId ?? String(data.user_id),
        handle: hostFilter || undefined,
        type: typeStr,
        q: debouncedQ || undefined,
        since,
      }),
    ])
      .then(([rows, c]) => {
        if (cancelled) return;
        // Multi-type filter: backend only takes one `type` per query,
        // so when multiple chips are picked we filter client-side.
        // Hour-band filter is also client-side (the backend has no
        // dow/hour predicate).
        const accept = (row: { type: string; ts: string | null }) => {
          if (activeTypes.size > 0 && !activeTypes.has(row.type)) return false;
          if (hourBand && row.ts) {
            const d = new Date(row.ts);
            if (d.getUTCDay() !== hourBand.dow || d.getUTCHours() !== hourBand.hour)
              return false;
          }
          return true;
        };
        const acceptedRows = rows.filter(accept);
        // Hour-band post-filter discards most of the fetched rows, so
        // we paginate the survivors client-side. For the standard
        // case we trust the server's offset/limit.
        const pagedRows = hourBandActive
          ? acceptedRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
          : acceptedRows;
        // Effective total for the pager: server count for the
        // standard case, accepted row count for hour-band where the
        // server can't predicate by (dow, hour).
        const effectiveTotal = hourBandActive
          ? acceptedRows.length
          : (c.total ?? null);
        const mapped: TikTokCommonGifterDetail['recent_activity'] = pagedRows
          .map((r) => ({
            id: r.id,
            ts: r.ts,
            type: r.type,
            // `searchEvents` doesn't return host_unique_id inline —
            // resolve it from the detail payload's host-room map so
            // every gift row keeps its "@host" link even when filtered.
            host: r.room_id != null ? (roomHostMap.get(String(r.room_id)) ?? null) : null,
            room_id: r.room_id != null ? String(r.room_id) : null,
            gift_name:
              ((r.payload as Record<string, unknown> | undefined)?.['gift_name'] as
                | string
                | undefined) ??
              null,
            repeat_count:
              ((r.payload as Record<string, unknown> | undefined)?.['repeat_count'] as
                | number
                | undefined) ??
              null,
            diamond_count:
              ((r.payload as Record<string, unknown> | undefined)?.['diamond_count'] as
                | number
                | undefined) ??
              null,
            text:
              (r.payload as Record<string, unknown> | undefined)?.['text'] as
                | string
                | undefined,
          }));
        setFilteredItems(mapped);
        setFilteredTotal(effectiveTotal);
      })
      .catch(() => {
        if (cancelled) return;
        setFilteredItems([]);
        setFilteredTotal(0);
      })
      .finally(() => {
        if (!cancelled) setFilterLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filtersActive, activeTypes, hostFilter, debouncedQ, hourBand, userId, data.user_id, page, roomHostMap]);

  const items = filteredItems ?? data.recent_activity ?? [];
  const baselineTotal = data.recent_activity?.length ?? 0;
  const total = filteredTotal ?? baselineTotal;

  const toggleType = (id: string) =>
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const TYPE_TONE: Record<string, string> = {
    gift: 'border-amber-300 text-amber-700 dark:text-amber-300',
    comment: 'border-sky-300 text-sky-700 dark:text-sky-300',
    join: 'border-emerald-300 text-emerald-700 dark:text-emerald-300',
    like: 'border-rose-300 text-rose-700 dark:text-rose-300',
    share: 'border-purple-300 text-purple-700 dark:text-purple-300',
    follow: 'border-pink-300 text-pink-700 dark:text-pink-300',
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Active hour-band chip — shown when the user clicked into
          this tab from a heatmap cell. Removable. */}
      {hourBand && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-md border border-primary-200 bg-primary-50 dark:bg-primary-500/10 dark:border-primary-500/30 text-xs font-mono">
          <span className="uppercase tracking-wider text-[10px] text-primary-700 dark:text-primary-300 opacity-70">
            Filter from heatmap
          </span>
          <span className="text-primary-700 dark:text-primary-300 font-bold">
            {DOW_LABELS[hourBand.dow]} {hourBand.hour}:00–{hourBand.hour + 1}:00
          </span>
          <button
            type="button"
            onClick={() => setHourBand(null)}
            className="ml-auto text-[11px] text-primary-700 dark:text-primary-300 hover:underline"
          >
            Clear
          </button>
        </div>
      )}
      {/* Filter toolbar — shown only when there's enough activity to
          warrant filtering. */}
      {(data.recent_activity?.length ?? 0) > 10 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-wider text-gray-500 font-mono mr-1">
              Type:
            </span>
            {ALL_TYPES.map((t) => {
              const active = activeTypes.has(t.id);
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => toggleType(t.id)}
                  className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-mono uppercase tracking-wider border ${
                    active
                      ? `bg-primary-100 dark:bg-primary-500/20 border-primary-300 text-primary-700 dark:text-primary-300`
                      : `bg-white dark:bg-white/5 ${TYPE_TONE[t.id] || 'border-gray-200 text-gray-500'}`
                  }`}
                >
                  {t.label}
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={hostFilter}
              onChange={(e) => setHostFilter(e.target.value)}
              className="px-2 py-1 text-xs font-mono rounded border border-gray-200 bg-white dark:bg-white/5"
            >
              <option value="">All hosts</option>
              {data.hosts.map((h) => (
                <option key={h.host} value={h.host}>
                  @{h.host}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search activity payload (text)…"
              className="flex-1 min-w-[200px] px-2.5 py-1 text-xs font-mono rounded border border-gray-200 bg-white dark:bg-white/5 placeholder:text-gray-400"
            />
            <span className="text-[11px] font-mono text-gray-500 tabular-nums">
              {filterLoading ? (
                <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
              ) : null}
              {filtersActive
                ? `${items.length.toLocaleString()} of ${total.toLocaleString()} matching`
                : `${items.length.toLocaleString()} most recent`}
            </span>
          </div>
        </div>
      )}
      {items.length > 0 ? (
        <RecentActivityPanel items={items} tz={tz} />
      ) : filtersActive ? (
        <p className="text-xs text-gray-500 text-center py-3">
          No events match the current filters.
        </p>
      ) : null}
      {/* Pagination — only when filters are active (the unfiltered
          view is a static "last 100" snapshot from the detail payload).
          `filteredTotal` is server-counted in the standard case and
          locally-counted in the hour-band case. */}
      {filtersActive && filteredTotal != null && filteredTotal > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-3 text-[11px] font-mono text-gray-500">
          <span className="tabular-nums">
            {(page * PAGE_SIZE + 1).toLocaleString()}–
            {Math.min((page + 1) * PAGE_SIZE, filteredTotal).toLocaleString()}
            {' of '}
            {filteredTotal.toLocaleString()}
          </span>
          <div className="inline-flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || filterLoading}
              className="inline-flex items-center px-1.5 py-0.5 rounded hover:bg-gray-100 disabled:opacity-30"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-3 h-3" />
            </button>
            <span className="tabular-nums px-1">
              {page + 1} / {Math.max(1, Math.ceil(filteredTotal / PAGE_SIZE))}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(
                Math.max(0, Math.ceil(filteredTotal / PAGE_SIZE) - 1),
                p + 1,
              ))}
              disabled={
                filterLoading ||
                (page + 1) * PAGE_SIZE >= filteredTotal
              }
              className="inline-flex items-center px-1.5 py-0.5 rounded hover:bg-gray-100 disabled:opacity-30"
              aria-label="Next page"
            >
              <ChevronRight className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}
      {data.co_gifters && data.co_gifters.length > 0 && (
        <CoGiftersPanel
          coGifters={data.co_gifters}
          poolHostCount={data.totals.host_count}
        />
      )}
      {(!data.co_gifters || data.co_gifters.length === 0) && (
        <p className="text-xs text-gray-500 text-center py-3">
          No overlap with other gifters yet — needs ≥3 shared rooms with another viewer.
        </p>
      )}
    </div>
  );
}

function RecentActivityPanel({
  items,
  tz,
}: {
  items: NonNullable<TikTokCommonGifterDetail['recent_activity']>;
  tz: string;
}) {
  const TYPE_STYLE: Record<string, string> = {
    gift: 'bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300',
    comment: 'bg-sky-100 dark:bg-sky-500/15 text-sky-700 dark:text-sky-300',
    join: 'bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
    like: 'bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300',
    share: 'bg-purple-100 dark:bg-purple-500/15 text-purple-700 dark:text-purple-300',
    follow: 'bg-pink-100 dark:bg-pink-500/15 text-pink-700 dark:text-pink-300',
  };
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Activity className="w-3.5 h-3.5 text-primary-500" />
        Recent activity feed
        <span className="text-gray-500 font-mono normal-case ml-1">
          (last {items.length})
        </span>
      </div>
      <ol className="flex flex-col gap-1 text-xs font-mono sm:max-h-[420px] sm:overflow-y-auto sm:pr-1">
        {items.map((it) => {
          const style =
            TYPE_STYLE[it.type] ||
            'bg-gray-100 dark:bg-gray-100/[0.10] text-gray-700';
          let body: React.ReactNode = null;
          if (it.type === 'gift') {
            const repeat = it.repeat_count ?? 1;
            const diamonds = (it.diamond_count ?? 0) * repeat;
            body = (
              <>
                <span className="text-gray-700">
                  {it.gift_name || 'a gift'}
                </span>
                {repeat > 1 && (
                  <span className="text-gray-500"> ×{repeat}</span>
                )}
                <span className="text-amber-700 dark:text-amber-300 ml-1">
                  ({diamonds.toLocaleString()}💎)
                </span>
              </>
            );
          } else if (it.type === 'comment') {
            body = (
              <span className="text-gray-700 break-words whitespace-pre-wrap">
                {it.text || <span className="italic text-gray-400">(empty)</span>}
              </span>
            );
          } else {
            body = <span className="text-gray-500">{it.type}</span>;
          }
          return (
            <li
              key={it.id}
              className="px-2 py-1 rounded border border-gray-200 bg-gray-50/60 dark:bg-gray-100/[0.04]"
            >
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span
                  className={`shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider ${style}`}
                >
                  {it.type}
                </span>
                {it.host ? (
                  <Link
                    to="/admin/tiktok/$handle"
                    params={{ handle: it.host }}
                    className="shrink-0 text-primary-700 dark:text-primary-300 hover:underline truncate max-w-[8rem]"
                    title={`Open @${it.host}`}
                  >
                    @{it.host}
                  </Link>
                ) : null}
                <span className="min-w-0 flex-1 break-words">{body}</span>
                <span className="shrink-0 text-[10px] text-gray-500 tabular-nums">
                  {fmtMonthDayTime(it.ts, tz)}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function CoGiftersPanel({
  coGifters,
  poolHostCount,
}: {
  coGifters: NonNullable<TikTokCommonGifterDetail['co_gifters']>;
  poolHostCount: number;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Users className="w-3.5 h-3.5 text-primary-500" />
        Co-gifters
        <span className="text-gray-500 font-mono normal-case ml-1">
          (other viewers in ≥3 of the same rooms)
        </span>
      </div>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {coGifters.map((c) => {
          const display = c.nickname || c.unique_id || `User ${c.user_id}`;
          return (
            <li
              key={c.user_id}
              className="flex items-center gap-2.5 px-2.5 py-1.5 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
            >
              {c.avatar_url ? (
                <img
                  src={c.avatar_url}
                  alt=""
                  className="w-8 h-8 rounded-full object-cover ring-1 ring-gray-200 dark:ring-white/10 shrink-0"
                  referrerPolicy="no-referrer"
                  loading="lazy"
                />
              ) : (
                <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-100/[0.15] flex items-center justify-center text-xs font-bold text-gray-500 shrink-0">
                  {(display[0] || '?').toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-gray-900">{display}</div>
                {c.unique_id && c.unique_id !== display && (
                  <div className="truncate text-[10px] font-mono text-gray-500">
                    @{c.unique_id}
                  </div>
                )}
              </div>
              <div className="shrink-0 text-right text-[10px] font-mono">
                <div className="text-primary-700 dark:text-primary-300 tabular-nums">
                  {c.shared_rooms} rooms
                  {poolHostCount > 0 && (
                    <span className="ml-1 text-gray-500 font-normal">
                      ({Math.round((c.shared_rooms / Math.max(1, poolHostCount)) * 100)}% overlap)
                    </span>
                  )}
                </div>
                <div className="text-amber-700 dark:text-amber-300 tabular-nums inline-flex items-baseline gap-0.5">
                  <Gem className="w-3 h-3 self-center" />
                  {c.diamonds_in_overlap.toLocaleString()}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}


/**
 * Match (PK battle) detail dashboard.
 *
 * Five tabs: Overview / Score Timeline / Gifters / Activity / Head-to-Head.
 * The audit flagged the previous 2-tab modal as too thin for a real
 * battle dashboard — buried winner, no score chart, no host-vs-opponent
 * split, no proper search/pagination. This rewrite addresses all of
 * that, plus dedupes the three hand-rolled pill components into one
 * `Pill` primitive and uses a theme-aware echarts color palette.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from '@tanstack/react-router';
import toast from 'react-hot-toast';
import * as echarts from 'echarts/core';
import { LineChart, BarChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  DataZoomComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import ReactECharts from 'echarts-for-react/lib/core';
import {
  Activity,
  Award,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Crown,
  Flame,
  Gem,
  Gift as GiftIcon,
  Heart,
  ListMinus,
  Loader2,
  MessageSquare,
  Search,
  Share2,
  Sparkles,
  Swords,
  TrendingUp,
  Trophy,
  UserPlus,
  Users,
} from 'lucide-react';

import { AnimatedScore } from '@admin/components/AnimatedScore';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import {
  useTikTokTimezone,
  partsInZone,
} from '@admin/contexts/TikTokTimezoneContext';
import {
  type TikTokEvent,
  type TikTokMatch,
  type TikTokMatchOpponent,
  type TikTokMatchScoreFrame,
  type TikTokMatchGiftersBySide,
  type TikTokMatchSideGifter,
  type TikTokMatchHeadToHeadRow,
  type TikTokH2HCommonGifter,
  tiktokApi,
} from '@admin/services/tiktok';
import { TikTokAddLiveModal } from '@admin/components/TikTokAddLiveModal';

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

// ─── Theme helpers (same pattern as the common-gifter modal) ───────

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
    axisLine:  isDark ? '#3f3f46' : '#d4d4d4',
    splitLine: isDark ? '#27272a' : '#e5e5e5',
    legendText:isDark ? '#d4d4d4' : '#404040',
  };
}

// ─── Event-type registry — one source of truth for icon, tone, label.
// Audit flagged TYPE_ICON / TYPE_TONE as parallel maps; collapsed.

interface EventMeta {
  icon: React.ReactNode;
  tone: string;
  /** Human-cased label shown to users — was raw snake_case before. */
  label: string;
}

const EVENT_META: Record<string, EventMeta> = {
  comment:      { icon: <MessageSquare className="w-3.5 h-3.5" />, tone: 'text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-500/15',           label: 'Comment' },
  gift:         { icon: <GiftIcon      className="w-3.5 h-3.5" />, tone: 'text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-500/15',   label: 'Gift' },
  like:         { icon: <Heart         className="w-3.5 h-3.5" />, tone: 'text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-500/15',       label: 'Like' },
  join:         { icon: <Users         className="w-3.5 h-3.5" />, tone: 'text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-500/15', label: 'Join' },
  follow:       { icon: <UserPlus      className="w-3.5 h-3.5" />, tone: 'text-violet-700 dark:text-violet-300 bg-violet-50 dark:bg-violet-500/15',label: 'Follow' },
  share:        { icon: <Share2        className="w-3.5 h-3.5" />, tone: 'text-pink-700 dark:text-pink-300 bg-pink-50 dark:bg-pink-500/15',       label: 'Share' },
  match_start:  { icon: <Swords        className="w-3.5 h-3.5" />, tone: 'text-rose-700 dark:text-rose-300 bg-rose-100 dark:bg-rose-500/20',      label: 'Battle start' },
  match_update: { icon: <Swords        className="w-3.5 h-3.5" />, tone: 'text-rose-700 dark:text-rose-300 bg-rose-100 dark:bg-rose-500/20',      label: 'Score update' },
  match_end:    { icon: <Swords        className="w-3.5 h-3.5" />, tone: 'text-rose-700 dark:text-rose-300 bg-rose-100 dark:bg-rose-500/20',      label: 'Battle end' },
};

function metaFor(type: string): EventMeta {
  return EVENT_META[type] ?? {
    icon: <Sparkles className="w-3.5 h-3.5" />,
    tone: 'text-gray-700 bg-gray-100',
    label: type.replace(/_/g, ' '),
  };
}

// ─── Modal props ────────────────────────────────────────────────────

interface MatchEventsModalProps {
  isOpen: boolean;
  onClose: () => void;
  match: TikTokMatch | null;
  hostHandle: string;
  /** Optional: when a Top Gifter row is clicked, the parent receives
   *  the user context so it can open the shared gifter modal. The
   *  match window (`since`/`until`) is forwarded so the gifter modal
   *  can scope its searchEvents calls to ONLY this battle. */
  onSelectGifter?: (g: {
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
    diamonds: number;
    gifts: number;
    comments: number;
    tab: 'gifts' | 'comments';
    since?: string | null;
    until?: string | null;
    windowLabel?: string;
  }) => void;
  /** Optional: swap the modal's current match. Used by the H2H tab
   *  and the Marquee Battles cards to drill into a related battle
   *  without closing → reopening. The parent owns the
   *  `selectedMatch` state that drives this modal. */
  onSelectMatch?: (m: TikTokMatch) => void;
}

type Tab = 'overview' | 'timeline' | 'gifters' | 'activity' | 'h2h';

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview',     icon: <BarChart3 className="w-3.5 h-3.5" /> },
  { id: 'timeline', label: 'Score',        icon: <Activity  className="w-3.5 h-3.5" /> },
  { id: 'gifters',  label: 'Gifters',      icon: <Users     className="w-3.5 h-3.5" /> },
  { id: 'activity', label: 'Activity',     icon: <ListMinus className="w-3.5 h-3.5" /> },
  { id: 'h2h',      label: 'Head-to-head', icon: <Swords    className="w-3.5 h-3.5" /> },
];

// ─── Main modal ─────────────────────────────────────────────────────

export function TikTokMatchEventsModal({
  isOpen,
  onClose,
  match,
  hostHandle,
  onSelectGifter,
  onSelectMatch,
}: MatchEventsModalProps) {
  const [tab, setTab] = useState<Tab>('overview');
  // Lowercased handles already in `tiktok_subscriptions`. Drives the
  // "✓ Monitoring" vs "+ Add to monitor" affordance on each opponent
  // card. Refetched on every modal open since a new live could have
  // been added since the last open.
  const [subscribedSet, setSubscribedSet] = useState<Set<string>>(() => new Set());
  // Pending "Add to monitor" confirmation. We hand the opponent's
  // handle off to the canonical `TikTokAddLiveModal` so the preview
  // (avatar, follower count, live state, bio, warnings) is identical
  // to the Add-Live flow on /admin/tiktok.
  const [addCandidate, setAddCandidate] = useState<TikTokMatchOpponent | null>(null);

  useEffect(() => {
    if (isOpen) setTab('overview');
  }, [isOpen, match?.id]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    tiktokApi
      .listLives()
      .then((rows) => {
        if (cancelled) return;
        const set = new Set<string>();
        for (const r of rows) {
          if (r.unique_id) set.add(r.unique_id.toLowerCase());
        }
        setSubscribedSet(set);
      })
      .catch(() => {
        // Silent — worst case the cards default to "+ Add to monitor"
        // and the backend's createLive guards against dupes anyway.
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const confirmAdd = async () => {
    if (!addCandidate?.unique_id) return;
    const handle = addCandidate.unique_id;
    try {
      await tiktokApi.createLive(handle, true);
      // Optimistic local update so the opponent cell flips to
      // "✓ Monitoring" without waiting for the next listLives
      // round-trip.
      setSubscribedSet((prev) => {
        const next = new Set(prev);
        next.add(handle.toLowerCase());
        return next;
      });
      toast.success(`Now monitoring @${handle}`);
      setAddCandidate(null);
    } catch (e) {
      toast.error(
        (e as Error).message || `Failed to add @${handle} to monitor`,
      );
      throw e; // let TikTokAddLiveModal know the create failed
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        match
          ? `Battle #${match.id} · @${hostHandle} ${summarizeOpponents(match, hostHandle)}`
          : 'Battle'
      }
      className="max-w-6xl"
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      }
    >
      {match && (
        <MatchHeader
          match={match}
          hostHandle={hostHandle}
          subscribedSet={subscribedSet}
          onAddRequested={setAddCandidate}
        />
      )}

      {/* Add-to-monitor — same modal flow as /admin/tiktok's Add Live
          so the operator sees identical preview data (avatar,
          followers, live state, bio, warnings, already-subscribed
          banner). */}
      <TikTokAddLiveModal
        isOpen={addCandidate !== null}
        handle={addCandidate?.unique_id ?? ''}
        onCancel={() => setAddCandidate(null)}
        onConfirm={confirmAdd}
      />

      {/* Tab bar — overflow scroll on narrow viewports so the 5 tabs
          don't wrap and break the underline alignment. */}
      <div
        className="flex items-center gap-1 mt-4 mb-3 border-b border-gray-200 overflow-x-auto whitespace-nowrap -mx-4 px-4 sm:mx-0 sm:px-0"
        role="tablist"
      >
        {TABS.map((t) => (
          <Pill
            key={t.id}
            kind="tab"
            active={tab === t.id}
            onClick={() => setTab(t.id)}
          >
            {t.icon}
            {t.label}
          </Pill>
        ))}
      </div>

      {match && tab === 'overview' && (
        <OverviewTab
          match={match}
          hostHandle={hostHandle}
          onSelectGifter={onSelectGifter}
        />
      )}
      {match && tab === 'timeline' && (
        <ScoreTimelineTab match={match} hostHandle={hostHandle} />
      )}
      {match && tab === 'gifters' && (
        <GiftersTab
          match={match}
          hostHandle={hostHandle}
          onSelectGifter={onSelectGifter}
        />
      )}
      {match && tab === 'activity' && (
        <ActivityTab match={match} hostHandle={hostHandle} />
      )}
      {match && tab === 'h2h' && (
        <HeadToHeadTab
          match={match}
          hostHandle={hostHandle}
          onOpenMatch={async (id) => {
            try {
              const next = await tiktokApi.getMatch(id);
              // Bubble up to the parent so it owns the swap. The
              // parent's `selectedMatch` state already drives this
              // modal's `match` prop, so reassigning it instantly
              // re-renders against the new battle.
              onSelectMatch?.(next);
            } catch (e) {
              // Silent fail — clicked-row UX shouldn't blow up the
              // tab if the fetch races.
              // eslint-disable-next-line no-console
              console.warn('Failed to open match', id, e);
            }
          }}
        />
      )}
    </Modal>
  );
}

// ─── Header ─────────────────────────────────────────────────────────

function MatchHeader({
  match,
  hostHandle,
  subscribedSet,
  onAddRequested,
}: {
  match: TikTokMatch;
  hostHandle: string;
  /** Lowercased handles already in `tiktok_subscriptions`. */
  subscribedSet: Set<string>;
  /** Called when the user clicks "Add to monitor" on an opponent
   *  card — the modal opens a confirmation dialog with the full
   *  opponent record (avatar, score, etc.). */
  onAddRequested: (o: TikTokMatchOpponent) => void;
}) {
  const { tz } = useTikTokTimezone();
  // The TS type says `opponents: TikTokMatchOpponent[]`, but the
  // backend column is `JSONB NULL` — historical rows can come back
  // as `null` and an unguarded `.filter` would crash the entire
  // modal (silent React error → empty body).
  const matchOpponents = match.opponents ?? [];
  const opponents = matchOpponents.filter(
    (o) => (o.unique_id || o.nickname) && o.unique_id !== hostHandle,
  );
  const result = match.result;
  // Score resolution falls back to `opponents[].score` when
  // `match.scores` is empty (TikTok sometimes ships scores only
  // through the per-anchor list, not the `match_update.scores` map).
  const { hostScore, oppScore } = resolveScores(match, hostHandle);
  const hasScores = hostScore != null && oppScore != null;
  const margin = hasScores ? Math.abs(hostScore - oppScore) : 0;
  const durationMin =
    match.started_at && (match.ended_at || match.last_seen_at)
      ? Math.max(
          0,
          Math.round(
            (new Date(match.ended_at || match.last_seen_at!).getTime() -
              new Date(match.started_at).getTime()) /
              60000,
          ),
        )
      : null;
  const battleClock = match.settings?.duration_seconds
    ? `${Math.floor(match.settings.duration_seconds / 60)}:${pad(match.settings.duration_seconds % 60)}`
    : null;
  const resultClass = {
    won:     'bg-emerald-100 dark:bg-emerald-500/20 text-emerald-800 dark:text-emerald-200 ring-emerald-300 dark:ring-emerald-500/40',
    lost:    'bg-rose-100 dark:bg-rose-500/20 text-rose-800 dark:text-rose-200 ring-rose-300 dark:ring-rose-500/40',
    draw:    'bg-amber-100 dark:bg-amber-500/20 text-amber-800 dark:text-amber-200 ring-amber-300 dark:ring-amber-500/40',
    ongoing: 'bg-sky-100 dark:bg-sky-500/20 text-sky-800 dark:text-sky-200 ring-sky-300 dark:ring-sky-500/40',
    ended:   'bg-gray-100 text-gray-700 ring-gray-200',
  }[result] ?? 'bg-gray-100 text-gray-700 ring-gray-200';
  const resultLabel = {
    won:     'Won',
    lost:    'Lost',
    draw:    'Draw',
    ongoing: 'Live',
    ended:   'Ended',
  }[result] ?? 'Ended';
  return (
    <section className="rounded-lg bg-gray-50 dark:bg-gray-100/[0.05] border border-gray-200 p-4">
      {/* ID strip — copy-friendly. Match id is the autoincrement
          on `tiktok_matches.id` (use this in the debug opener);
          battle_id is TikTok's own bigint. Surfaced at the top of
          the header so any "this match is wrong" report can carry
          the exact identifier. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-3 text-[11px] font-mono text-gray-500">
        <span
          className="inline-flex items-center gap-1 select-all"
          title="Internal match id (use with the debug opener)"
        >
          <span className="opacity-70">match</span>
          <span className="text-gray-900 font-bold">#{match.id}</span>
        </span>
        <span
          className="inline-flex items-center gap-1 select-all"
          title="TikTok's battle_id (BigInt, opaque to us)"
        >
          <span className="opacity-70">battle</span>
          <span className="truncate max-w-[14rem]">{match.battle_id}</span>
        </span>
        <span
          className="inline-flex items-center gap-1 select-all"
          title="Room id (broadcast)"
        >
          <span className="opacity-70">room</span>
          <span className="truncate max-w-[14rem]">{match.room_id}</span>
        </span>
      </div>
      {/* Two-column body: stats on the left, opponents box on the
          right. The stats column gets a 4-cell wrap (outcome,
          diamonds, margin, duration/started) so the space isn't
          wasted when there's a tall opponents stack on the right. */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-4">
        {/* Stats — left column. */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3">
          {/* Outcome pill — promoted to a 1st-class header chip. */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
              Outcome
            </div>
            <div
              className={`mt-1 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-bold ring-1 ${resultClass}`}
            >
              {result === 'won' && <Trophy className="w-4 h-4" />}
              {resultLabel}
              {hasScores && (
                <span className="ml-1 tabular-nums font-mono">
                  {compact(hostScore!)}–{compact(oppScore!)}
                </span>
              )}
            </div>
          </div>
          {/* Diamonds — hero number; promoted from the old 4-pair grid. */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
              Diamonds
            </div>
            <div className="mt-1 flex items-baseline gap-1.5">
              <span className="text-2xl font-bold tabular-nums text-amber-700 dark:text-amber-300">
                {(match.diamonds_total ?? 0).toLocaleString()}
              </span>
              <Gem className="w-4 h-4 text-amber-500" />
            </div>
          </div>
          {/* Margin — fills the cell that used to be empty whitespace
              when stats moved to a narrower column. Signed delta
              (host's perspective) + decisive % classification. */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
              Margin
            </div>
            {hasScores ? (() => {
              const delta = (hostScore ?? 0) - (oppScore ?? 0);
              const top = Math.max(hostScore ?? 0, oppScore ?? 0);
              const decisivePct = top > 0 ? (margin / top) * 100 : 0;
              const tone =
                delta > 0
                  ? 'text-emerald-700 dark:text-emerald-300'
                  : delta < 0
                    ? 'text-rose-700 dark:text-rose-300'
                    : 'text-gray-500';
              const charBadge =
                decisivePct >= 50
                  ? { label: 'decisive',    cls: 'bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300' }
                  : decisivePct >= 20
                    ? { label: 'comfortable', cls: 'bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300' }
                    : { label: 'close',     cls: 'bg-sky-100 dark:bg-sky-500/15 text-sky-700 dark:text-sky-300' };
              return (
                <div className="mt-1 flex items-baseline gap-2 flex-wrap">
                  <span className={`text-base font-bold tabular-nums ${tone}`}>
                    {delta > 0 ? '+' : delta < 0 ? '−' : ''}
                    {compact(Math.abs(delta))}
                  </span>
                  {decisivePct > 0 && (
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider ${charBadge.cls}`}>
                      {charBadge.label}
                    </span>
                  )}
                </div>
              );
            })() : (
              <div className="mt-1 text-sm text-gray-400 font-mono">—</div>
            )}
          </div>
          {/* Duration. */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
              Duration
            </div>
            <div className="mt-1 text-sm font-bold tabular-nums">
              {durationMin != null ? `${durationMin} min` : '—'}
              {battleClock && (
                <span className="text-gray-500 font-normal text-xs">
                  {' '}
                  · clock {battleClock}
                </span>
              )}
            </div>
          </div>
          {/* Started / Ended split — 6th cell fills the third row of
              the 3-col grid so the left column doesn't have a hanging
              empty slot. The ID strip up top already carries
              battle_id, so duplicating it here would be noise. */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
              Started
            </div>
            <div className="mt-1 text-sm font-mono tabular-nums text-gray-700">
              {fmtTs(match.started_at, tz)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
              Ended
            </div>
            <div className="mt-1 text-sm font-mono tabular-nums text-gray-700">
              {fmtTs(match.ended_at, tz)}
            </div>
          </div>
        </div>

        {/* Opponents box — right column. */}
        {opponents.length > 0 ? (
          <div className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.02] p-3">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono mb-2">
              {opponents.length === 1 ? 'Opponent' : 'Opponents'}
              <span className="ml-1 text-gray-400 normal-case">
                ({opponents.length})
              </span>
            </div>
            <div className="flex flex-col gap-2">
              {opponents.map((o) => (
                <OpponentCell
                  key={o.user_id || o.unique_id || o.nickname || ''}
                  o={o}
                  isMonitored={
                    o.unique_id
                      ? subscribedSet.has(o.unique_id.toLowerCase())
                      : false
                  }
                  onAddRequested={onAddRequested}
                />
              ))}
            </div>
          </div>
        ) : (
          // Keep the column placeholder so the left-side stats don't
          // expand and reflow on solo matches with no captured
          // opponents.
          <div />
        )}
      </div>
    </section>
  );
}

function OpponentCell({
  o,
  isMonitored,
  onAddRequested,
}: {
  o: TikTokMatchOpponent;
  isMonitored: boolean;
  onAddRequested: (o: TikTokMatchOpponent) => void;
}) {
  const handle = o.unique_id || '';
  const display = o.nickname || handle || '—';
  const seed = (display[0] || '?').toUpperCase();
  const url = (o as { avatar_url?: string }).avatar_url;
  return (
    <div className="flex items-center gap-2.5 rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2 min-w-[220px]">
      {url ? (
        <img
          src={url}
          alt=""
          className="w-9 h-9 rounded-full object-cover ring-1 ring-gray-200 dark:ring-white/10 shrink-0"
          referrerPolicy="no-referrer"
          loading="lazy"
        />
      ) : (
        <div className="w-9 h-9 rounded-full bg-gray-100 dark:bg-white/10 text-gray-500 flex items-center justify-center text-xs font-bold shrink-0">
          {seed}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-gray-900">
          {display}
        </div>
        {handle && (
          <div className="truncate text-[11px] font-mono text-gray-500">
            @{handle}
          </div>
        )}
      </div>
      {!handle ? (
        <span className="shrink-0 text-[10px] font-mono text-gray-400 italic">
          no handle
        </span>
      ) : isMonitored ? (
        <Link
          to="/admin/tiktok/$handle"
          params={{ handle }}
          className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono uppercase tracking-wider bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30 hover:bg-emerald-200 dark:hover:bg-emerald-500/25 transition-colors"
          title="Open this creator's live page — already monitored"
        >
          ✓ Monitoring
        </Link>
      ) : (
        <button
          type="button"
          onClick={() => onAddRequested(o)}
          className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono uppercase tracking-wider bg-primary-100 dark:bg-primary-500/15 text-primary-700 dark:text-primary-300 border border-primary-200 dark:border-primary-500/30 hover:bg-primary-200 dark:hover:bg-primary-500/25 transition-colors"
          title="Start monitoring this creator's lives"
        >
          + Add to monitor
        </button>
      )}
    </div>
  );
}

// ─── Tab: Overview ──────────────────────────────────────────────────

function OverviewTab({
  match,
  hostHandle,
  onSelectGifter,
}: {
  match: TikTokMatch;
  hostHandle: string;
  onSelectGifter?: MatchEventsModalProps['onSelectGifter'];
}) {
  const [sides, setSides] = useState<TikTokMatchGiftersBySide | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    tiktokApi
      .getMatchGiftersBySide(match.id)
      .then((s) => {
        if (!cancelled) setSides(s);
      })
      .catch(() => {
        if (!cancelled) setSides(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [match.id]);

  return (
    <div className="flex flex-col gap-4">
      {/* Side-balance bar — instantly tells you who funded each side. */}
      {sides && <SideBalanceBar sides={sides} hostHandle={hostHandle} match={match} />}
      {sides && <SideTopGifters
        sides={sides}
        match={match}
        onSelectGifter={onSelectGifter}
      />}
      {/* Unified "who paid into this match" ranking — combines both
          sides (and unknown-recipient gifts) sorted purely by diamonds.
          Answers "who's the biggest donor of THIS match regardless of
          who they backed", separate from the side-split view above. */}
      {sides && (
        <MatchTopDonors
          sides={sides}
          match={match}
          hostHandle={hostHandle}
          onSelectGifter={onSelectGifter}
        />
      )}
      {loading && !sides && (
        <div className="py-8 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
          Loading match overview…
        </div>
      )}
    </div>
  );
}

/** Single ranked table of every donor in this match, sorted by
 *  diamonds. Side affiliation (host / opponent / unknown) shown as a
 *  tone dot so the operator can see "the top whale backed the
 *  opponent" without needing the split view above.
 *
 *  Clicking a row opens the gifter modal scoped to the battle window
 *  — same flow as SideTopGifters' picker. */
function MatchTopDonors({
  sides,
  match,
  hostHandle,
  onSelectGifter,
}: {
  sides: TikTokMatchGiftersBySide;
  match: TikTokMatch;
  hostHandle: string;
  onSelectGifter?: MatchEventsModalProps['onSelectGifter'];
}) {
  type Row = TikTokMatchSideGifter & { side: 'host' | 'opponent' | 'unknown' };
  const rows: Row[] = [
    ...sides.host.map((g) => ({ ...g, side: 'host' as const })),
    ...sides.opponent.map((g) => ({ ...g, side: 'opponent' as const })),
    ...sides.unknown.map((g) => ({ ...g, side: 'unknown' as const })),
  ].sort((a, b) => b.diamonds - a.diamonds);

  if (rows.length === 0) return null;

  const total = rows.reduce((acc, r) => acc + r.diamonds, 0) || 1;
  const since = match.started_at;
  const until = match.ended_at ?? match.last_seen_at;
  const pick = (r: Row) => {
    if (!onSelectGifter) return;
    onSelectGifter({
      userId: r.user_id,
      uniqueId: r.unique_id,
      nickname: r.nickname,
      diamonds: r.diamonds,
      gifts: r.gifts,
      comments: 0,
      tab: 'gifts',
      since,
      until,
      windowLabel: 'This battle',
    });
  };
  const sideTone = (s: Row['side']) => {
    if (s === 'host') return { dot: 'bg-emerald-500', label: `@${hostHandle}` };
    if (s === 'opponent') return { dot: 'bg-rose-500', label: 'opponent' };
    return { dot: 'bg-gray-400 dark:bg-white/30', label: 'unknown' };
  };

  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-3 shadow-sm">
      <div className="auth-mono-label flex items-center justify-between gap-1.5 mb-2">
        <span className="inline-flex items-center gap-1.5">
          <Crown className="w-3.5 h-3.5 text-amber-500" />
          Top donors · this battle
        </span>
        <span className="text-[10px] font-mono text-gray-500 normal-case tracking-normal">
          {rows.length} donor{rows.length === 1 ? '' : 's'} · {total.toLocaleString()} 💎
        </span>
      </div>
      <ol className="flex flex-col gap-1 text-xs font-mono">
        {rows.slice(0, 12).map((r, i) => {
          const display = r.nickname || r.unique_id || '—';
          const pct = (r.diamonds / total) * 100;
          const tone = sideTone(r.side);
          return (
            <li key={r.user_id}>
              <button
                type="button"
                onClick={() => pick(r)}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06] hover:bg-gray-100 dark:hover:bg-white/10 transition-colors text-left"
                title="Open this gifter's full history scoped to this battle"
              >
                <span className="shrink-0 w-5 text-center text-gray-400 tabular-nums">
                  #{i + 1}
                </span>
                {r.avatar_url ? (
                  <img
                    src={r.avatar_url}
                    alt=""
                    className="w-7 h-7 rounded-full object-cover shrink-0"
                    referrerPolicy="no-referrer"
                    loading="lazy"
                  />
                ) : (
                  <div className="w-7 h-7 rounded-full bg-gray-200 dark:bg-white/10 text-gray-500 flex items-center justify-center text-[10px] font-bold shrink-0">
                    {display[0]?.toUpperCase()}
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-gray-900">{display}</div>
                  {r.unique_id && r.unique_id !== display && (
                    <div className="truncate text-[10px] text-gray-500">
                      @{r.unique_id}
                    </div>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <div className="tabular-nums font-bold text-amber-700 dark:text-amber-300">
                    {r.diamonds.toLocaleString()} 💎
                  </div>
                  <div className="text-[10px] text-gray-500 tabular-nums">
                    {r.gifts} gift{r.gifts === 1 ? '' : 's'} · {pct.toFixed(1)}%
                  </div>
                </div>
                <span
                  className={`shrink-0 inline-flex items-center gap-1 ml-1 text-[9px] uppercase tracking-wider text-gray-500`}
                  title={`Backed ${tone.label}`}
                >
                  <span className={`inline-block w-2 h-2 rounded-full ${tone.dot}`} />
                  <span className="truncate max-w-[80px]">{tone.label}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function SideBalanceBar({
  sides,
  hostHandle,
  match,
}: {
  sides: TikTokMatchGiftersBySide;
  hostHandle: string;
  match: TikTokMatch;
}) {
  const t = sides.totals;
  const total = t.host_diamonds + t.opponent_diamonds + t.unknown_diamonds;
  // PK scores from match_update or opponents[].score — see
  // `resolveScores` for why both paths matter.
  const { hostScore, oppScore } = resolveScores(match, hostHandle);
  // If the gifters-by-side query returns *some* opponent diamonds
  // (multi-guest case), and we ALSO know the opponent's PK score,
  // the gap between the two is the slice TikTok's protocol attributed
  // to the opponent that we don't have line-item data for.
  const oppMissing =
    oppScore != null && oppScore > t.opponent_diamonds
      ? oppScore - t.opponent_diamonds
      : 0;
  if (total === 0 && (oppScore ?? 0) === 0) return null;
  const hostPct = total > 0 ? (t.host_diamonds / total) * 100 : 0;
  const oppPct  = total > 0 ? (t.opponent_diamonds / total) * 100 : 0;
  const unkPct  = total > 0 ? (t.unknown_diamonds / total) * 100 : 0;
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="flex items-baseline justify-between mb-2 gap-2">
        <h3 className="auth-mono-label flex items-center gap-1.5">
          <Award className="w-3.5 h-3.5 text-amber-500" />
          Diamond split by side
        </h3>
        <span className="text-[11px] font-mono text-gray-500 tabular-nums inline-flex items-baseline gap-1.5">
          <span>{total.toLocaleString()} 💎 ingested</span>
          {hostScore != null && oppScore != null && (
            <>
              <span>·</span>
              <span>score</span>
              <AnimatedScore
                value={hostScore}
                display={compact(hostScore)}
                tone="emerald"
                className="font-bold text-emerald-700 dark:text-emerald-300"
              />
              <span>–</span>
              <AnimatedScore
                value={oppScore}
                display={compact(oppScore)}
                tone="rose"
                className="font-bold text-rose-700 dark:text-rose-300"
              />
            </>
          )}
        </span>
      </div>
      <div className="h-4 w-full rounded-full overflow-hidden flex bg-gray-200 dark:bg-white/10">
        {hostPct > 0 && (
          <div
            className="bg-emerald-500"
            style={{ width: `${hostPct}%` }}
            title={`Backed @${hostHandle}: ${t.host_diamonds.toLocaleString()} 💎 (${hostPct.toFixed(1)}%)`}
          />
        )}
        {oppPct > 0 && (
          <div
            className="bg-rose-500"
            style={{ width: `${oppPct}%` }}
            title={`To opponent: ${t.opponent_diamonds.toLocaleString()} 💎 (${oppPct.toFixed(1)}%)`}
          />
        )}
        {unkPct > 0 && (
          <div
            className="bg-gray-400 dark:bg-white/20"
            style={{ width: `${unkPct}%` }}
            title={`Recipient unknown: ${t.unknown_diamonds.toLocaleString()} 💎 (${unkPct.toFixed(1)}%)`}
          />
        )}
      </div>
      <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs font-mono">
        <SideStat
          tone="emerald"
          label={`Backed @${hostHandle}`}
          gifters={t.host_gifters}
          gifts={t.host_gifts}
          diamonds={t.host_diamonds}
          subline={
            hostScore != null && hostScore !== t.host_diamonds
              ? `PK score ${compact(hostScore)} (TikTok's tally)`
              : undefined
          }
        />
        <SideStat
          tone="rose"
          label="Backed opponent"
          gifters={t.opponent_gifters}
          gifts={t.opponent_gifts}
          diamonds={t.opponent_diamonds}
          subline={
            oppScore != null
              ? `PK score ${compact(oppScore)}${oppMissing > 0 ? ` · +${compact(oppMissing)} from opponent's stream (not ingested)` : ''}`
              : undefined
          }
        />
        {t.unknown_diamonds > 0 ? (
          <SideStat
            tone="gray"
            label="Unknown recipient"
            gifters={null}
            gifts={null}
            diamonds={t.unknown_diamonds}
            hint="Recipient handle present but didn't match host or any known opponent."
          />
        ) : (
          <div />
        )}
      </div>
      {/* Honest caption — the audit's "save evidence when inferring"
          rule. Without this, an operator would think the system
          missed the opponent's gifts; in fact those happen in the
          opponent's separate broadcast. */}
      {oppScore != null && oppScore > 0 && t.opponent_diamonds < oppScore && (
        <p className="mt-2 text-[11px] text-gray-500 font-mono leading-relaxed">
          Opponent's PK score reflects gifts sent in their own broadcast — we
          only subscribe to <span className="text-emerald-700 dark:text-emerald-300">@{hostHandle}</span>'s
          stream, so opponent-side gifters and per-event diamond breakdowns
          aren't available. The score chip above carries TikTok's authoritative
          tally for that side.
        </p>
      )}
    </section>
  );
}

function SideStat({
  tone,
  label,
  gifters,
  gifts,
  diamonds,
  hint,
  subline,
}: {
  tone: 'emerald' | 'rose' | 'gray';
  label: string;
  gifters: number | null;
  gifts: number | null;
  diamonds: number;
  hint?: string;
  /** Optional second line below the count breakdown — used to surface
   *  the opponent's authoritative PK score even when our diamond
   *  count is 0 (we don't ingest opponent's broadcast). */
  subline?: string;
}) {
  const text = {
    emerald: 'text-emerald-700 dark:text-emerald-300',
    rose:    'text-rose-700 dark:text-rose-300',
    gray:    'text-gray-600',
  }[tone];
  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06] px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-gray-500" title={hint}>
        {label}
      </div>
      <div className={`mt-0.5 font-bold tabular-nums ${text}`}>
        {diamonds.toLocaleString()}
        <span className="text-gray-500 font-normal text-[11px]"> 💎</span>
      </div>
      <div className="text-[10px] text-gray-500 tabular-nums">
        {gifts != null && `${gifts.toLocaleString()} gifts`}
        {gifters != null && ` · ${gifters.toLocaleString()} gifters`}
      </div>
      {subline && (
        <div className="text-[10px] text-gray-500 mt-0.5 leading-tight">
          {subline}
        </div>
      )}
    </div>
  );
}

function SideTopGifters({
  sides,
  match,
  onSelectGifter,
}: {
  sides: TikTokMatchGiftersBySide;
  match: TikTokMatch;
  onSelectGifter?: MatchEventsModalProps['onSelectGifter'];
}) {
  const since = match.started_at;
  const until = match.ended_at ?? match.last_seen_at;
  const pickGifter = (g: TikTokMatchSideGifter) => {
    if (!onSelectGifter) return;
    onSelectGifter({
      userId: g.user_id,
      uniqueId: g.unique_id,
      nickname: g.nickname,
      diamonds: g.diamonds,
      gifts: g.gifts,
      comments: 0,
      tab: 'gifts',
      since,
      until,
      windowLabel: 'This battle',
    });
  };
  return (
    <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <SideGiftersList
        title="Top gifters · backed host"
        accent="emerald"
        items={sides.host.slice(0, 8)}
        onPick={pickGifter}
      />
      <SideGiftersList
        title="Top gifters · backed opponent"
        accent="rose"
        items={sides.opponent.slice(0, 8)}
        onPick={pickGifter}
      />
    </section>
  );
}

function SideGiftersList({
  title,
  accent,
  items,
  onPick,
}: {
  title: string;
  accent: 'emerald' | 'rose';
  items: TikTokMatchSideGifter[];
  onPick: (g: TikTokMatchSideGifter) => void;
}) {
  const accentDot = accent === 'emerald' ? 'bg-emerald-500' : 'bg-rose-500';
  return (
    <div className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-3 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <span className={`inline-block w-2 h-2 rounded-full ${accentDot}`} />
        {title}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-gray-500 text-center py-3">
          No gifters classified to this side.
        </p>
      ) : (
        <ol className="flex flex-col gap-1 text-xs font-mono">
          {items.map((g, i) => {
            const display = g.nickname || g.unique_id || '—';
            return (
              <li key={g.user_id}>
                <button
                  type="button"
                  onClick={() => onPick(g)}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06] hover:bg-gray-100 dark:hover:bg-white/10 transition-colors text-left"
                  title="Open this gifter's full history"
                >
                  <span className="shrink-0 w-5 text-center text-gray-400 tabular-nums">
                    #{i + 1}
                  </span>
                  {g.avatar_url ? (
                    <img
                      src={g.avatar_url}
                      alt=""
                      className="w-7 h-7 rounded-full object-cover shrink-0"
                      referrerPolicy="no-referrer"
                      loading="lazy"
                    />
                  ) : (
                    <div className="w-7 h-7 rounded-full bg-gray-200 dark:bg-white/10 text-gray-500 flex items-center justify-center text-[10px] font-bold shrink-0">
                      {display[0]?.toUpperCase()}
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-gray-900">{display}</div>
                    {g.unique_id && g.unique_id !== display && (
                      <div className="truncate text-[10px] text-gray-500">
                        @{g.unique_id}
                      </div>
                    )}
                  </div>
                  <span className="shrink-0 text-amber-700 dark:text-amber-300 tabular-nums font-bold">
                    {g.diamonds.toLocaleString()}
                  </span>
                  <span className="shrink-0 text-gray-500 tabular-nums w-12 text-right">
                    {g.gifts}×
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

// ─── Tab: Score timeline ────────────────────────────────────────────

function ScoreTimelineTab({
  match,
  hostHandle,
}: {
  match: TikTokMatch;
  hostHandle: string;
}) {
  const [frames, setFrames] = useState<TikTokMatchScoreFrame[] | null>(null);
  const [loading, setLoading] = useState(false);
  const isDark = useDarkMode();
  const t = chartTheme(isDark);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    tiktokApi
      .getMatchScoreTimeline(match.id)
      .then((rows) => {
        if (!cancelled) setFrames(rows);
      })
      .catch(() => {
        if (!cancelled) setFrames([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [match.id]);

  // The score keys on each frame can be either team_ids (older
  // payload shape) or user_ids (newer 1v1 shape). Build BOTH
  // identifier sets so we can classify either way without caring
  // which TikTok protocol version the lib decoded from.
  const { oppKeySet, hostKeySet } = useMemo(() => {
    const opp = new Set<string>();
    const host = new Set<string>();
    for (const o of match.opponents ?? []) {
      const isOpp = (o.unique_id || o.nickname) !== hostHandle;
      if (o.team_id != null) (isOpp ? opp : host).add(String(o.team_id));
      if (o.user_id != null) (isOpp ? opp : host).add(String(o.user_id));
    }
    return { oppKeySet: opp, hostKeySet: host };
  }, [match.opponents, hostHandle]);

  const { hostSeries, oppSeries, momentumHost, momentumOpp, xLabels, leadFlips } = useMemo(() => {
    const empty = {
      hostSeries: [] as number[],
      oppSeries: [] as number[],
      momentumHost: [] as number[],
      momentumOpp: [] as number[],
      xLabels: [] as string[],
      leadFlips: [] as { idx: number; ts: string }[],
    };
    if (!frames || frames.length === 0) return empty;
    // Walk frames and classify each score key. A key is "host" if
    // it's in `hostKeySet` OR it isn't in `oppKeySet` (and there's
    // at least one opp key in the frame to anchor against).
    let hostKey: string | null = null;
    let oppKey: string | null = null;
    for (const f of frames) {
      for (const k of Object.keys(f.scores)) {
        if (hostKeySet.has(k)) {
          if (!hostKey) hostKey = k;
        } else if (oppKeySet.has(k)) {
          if (!oppKey) oppKey = k;
        }
      }
      if (hostKey && oppKey) break;
    }
    // Fallback when we can't disambiguate via opponents list (rare —
    // happens when opponents JSON is missing user_id AND team_id).
    // Stable arbitrary assignment by sorted key.
    if ((!hostKey || !oppKey) && frames[0]) {
      const keys = Object.keys(frames[0].scores).sort();
      if (keys.length >= 2) {
        hostKey = hostKey ?? keys[0];
        oppKey  = oppKey  ?? keys[1];
      }
    }
    const hostTid = hostKey;
    const oppTid  = oppKey;
    const hostSeries: number[] = [];
    const oppSeries: number[] = [];
    const xLabels: string[] = [];
    for (const f of frames) {
      hostSeries.push(hostTid ? Number(f.scores[hostTid] ?? 0) : 0);
      oppSeries .push(oppTid  ? Number(f.scores[oppTid]  ?? 0) : 0);
      const d = f.ts ? new Date(f.ts) : null;
      xLabels.push(d ? `${pad(d.getMinutes())}:${pad(d.getSeconds())}` : '');
    }
    // Δ-per-frame momentum.
    const momentumHost: number[] = [0];
    const momentumOpp: number[] = [0];
    for (let i = 1; i < hostSeries.length; i++) {
      momentumHost.push(hostSeries[i] - hostSeries[i - 1]);
      momentumOpp .push(oppSeries[i]  - oppSeries[i - 1]);
    }
    // Lead-flip detection — the most actionable signal. The leader
    // changes when sign of (host - opp) flips between consecutive
    // frames.
    const leadFlips: { idx: number; ts: string }[] = [];
    for (let i = 1; i < hostSeries.length; i++) {
      const prev = Math.sign(hostSeries[i - 1] - oppSeries[i - 1]);
      const cur  = Math.sign(hostSeries[i]     - oppSeries[i]);
      if (prev !== 0 && cur !== 0 && prev !== cur) {
        leadFlips.push({ idx: i, ts: frames[i].ts ?? '' });
      }
    }
    return { hostSeries, oppSeries, momentumHost, momentumOpp, xLabels, leadFlips };
  }, [frames, hostKeySet, oppKeySet]);

  const scoreOption = useMemo(() => {
    if (!frames || frames.length === 0) return null;
    return {
      grid: { left: 56, right: 12, top: 36, bottom: 22 },
      tooltip: { trigger: 'axis' },
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: { fontSize: 10, fontFamily: 'JetBrains Mono Variable', color: t.legendText },
      },
      xAxis: {
        type: 'category',
        data: xLabels,
        axisLabel: { fontSize: 9, color: t.axisLabel },
        axisLine: { lineStyle: { color: t.axisLine } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 9, color: t.axisLabel, formatter: (v: number) => compact(v) },
        splitLine: { lineStyle: { color: t.splitLine } },
      },
      series: [
        {
          name: `@${hostHandle}`,
          type: 'line',
          smooth: true,
          symbol: 'none',
          color: '#10b981',
          lineStyle: { width: 2 },
          data: hostSeries,
          markLine:
            leadFlips.length > 0
              ? {
                  symbol: 'none',
                  lineStyle: { color: '#a855f7', type: 'dashed', width: 1 },
                  label: { show: false },
                  data: leadFlips.map((lf) => ({ xAxis: xLabels[lf.idx] })),
                }
              : undefined,
        },
        {
          name: 'Opponent',
          type: 'line',
          smooth: true,
          symbol: 'none',
          color: '#f43f5e',
          lineStyle: { width: 2 },
          data: oppSeries,
        },
      ],
    };
  }, [frames, xLabels, hostSeries, oppSeries, leadFlips, hostHandle, t.axisLabel, t.axisLine, t.splitLine, t.legendText]);

  const momentumOption = useMemo(() => {
    if (!frames || frames.length === 0) return null;
    return {
      grid: { left: 56, right: 12, top: 28, bottom: 22 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: xLabels,
        axisLabel: { fontSize: 9, color: t.axisLabel },
        axisLine: { lineStyle: { color: t.axisLine } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { fontSize: 9, color: t.axisLabel, formatter: (v: number) => compact(v) },
        splitLine: { lineStyle: { color: t.splitLine } },
      },
      series: [
        {
          name: `@${hostHandle} Δ`,
          type: 'bar',
          stack: 'momentum',
          color: '#10b981',
          data: momentumHost,
        },
        {
          // Negate opponent so it drops below the zero line — a
          // divergent bar instead of a stack.
          name: 'Opp Δ',
          type: 'bar',
          stack: 'momentum',
          color: '#f43f5e',
          data: momentumOpp.map((v) => -v),
        },
      ],
    };
  }, [frames, xLabels, momentumHost, momentumOpp, hostHandle, t.axisLabel, t.axisLine, t.splitLine]);

  if (loading && !frames) {
    return (
      <div className="py-8 text-center text-sm text-gray-500">
        <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
        Loading score timeline…
      </div>
    );
  }
  if (!frames || frames.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-gray-500">
        No `match_update` events captured for this battle — score timeline unavailable.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
        <div className="auth-mono-label flex items-center gap-1.5 mb-2">
          <Activity className="w-3.5 h-3.5 text-emerald-500" />
          Score over time
          {leadFlips.length > 0 && (
            <span className="ml-2 text-purple-700 dark:text-purple-300 font-mono normal-case text-[11px]">
              {leadFlips.length} lead flip{leadFlips.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
        {scoreOption && (
          <ReactECharts
            echarts={echarts}
            option={scoreOption}
            style={{ height: 280, minHeight: 240 }}
            notMerge
            lazyUpdate
          />
        )}
      </section>
      <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
        <div className="auth-mono-label flex items-center gap-1.5 mb-2">
          <TrendingUp className="w-3.5 h-3.5 text-rose-500" />
          Per-frame Δ (rallies)
          <span className="ml-2 text-gray-500 font-mono normal-case text-[11px]">
            host above zero, opponent below
          </span>
        </div>
        {momentumOption && (
          <ReactECharts
            echarts={echarts}
            option={momentumOption}
            style={{ height: 200, minHeight: 160 }}
            notMerge
            lazyUpdate
          />
        )}
      </section>
      {leadFlips.length > 0 && (
        <CriticalMomentsList flips={leadFlips} hostHandle={hostHandle} />
      )}
    </div>
  );
}

function CriticalMomentsList({
  flips,
  hostHandle,
}: {
  flips: { idx: number; ts: string }[];
  hostHandle: string;
}) {
  const { tz } = useTikTokTimezone();
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Flame className="w-3.5 h-3.5 text-purple-500" />
        Critical moments — lead flips
      </div>
      <ol className="flex flex-col gap-1 text-xs font-mono">
        {flips.map((f, i) => (
          <li
            key={`${f.idx}-${f.ts}`}
            className="flex items-center gap-2 px-2 py-1 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
          >
            <span className="text-purple-700 dark:text-purple-300 tabular-nums w-6 text-right">
              #{i + 1}
            </span>
            <span className="text-gray-500 tabular-nums">
              {fmtTs(f.ts, tz) || '—'}
            </span>
            <span className="text-gray-700">
              the lead changed —{' '}
              {i % 2 === 0
                ? `opponent overtook @${hostHandle}`
                : `@${hostHandle} retook the lead`}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

// ─── Tab: Gifters (full split with sort + search) ───────────────────

type GifterSort = 'diamonds' | 'gifts' | 'largest_single';
type GifterSide = 'all' | 'host' | 'opponent' | 'unknown';

function GiftersTab({
  match,
  hostHandle,
  onSelectGifter,
}: {
  match: TikTokMatch;
  hostHandle: string;
  onSelectGifter?: MatchEventsModalProps['onSelectGifter'];
}) {
  const GIFTER_PAGE_SIZES = [25, 50, 100, 250] as const;

  const [sides, setSides] = useState<TikTokMatchGiftersBySide | null>(null);
  const [loading, setLoading] = useState(false);
  const [side, setSide] = useState<GifterSide>('all');
  const [sort, setSort] = useState<GifterSort>('diamonds');
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [minDiamonds, setMinDiamonds] = useState<number | ''>('');
  const [pageSize, setPageSize] = useState<number>(50);
  const [page, setPage] = useState(0); // zero-based

  // Debounce free-text search so we don't repaginate on every
  // keystroke for a multi-hundred-row dataset.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);

  // Whenever filters change, reset to page 1 so the user isn't
  // stranded on an empty page that no longer exists.
  useEffect(() => {
    setPage(0);
  }, [side, sort, debouncedQ, minDiamonds, pageSize, match.id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    tiktokApi
      .getMatchGiftersBySide(match.id)
      .then((s) => {
        if (!cancelled) setSides(s);
      })
      .catch(() => {
        if (!cancelled) setSides(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [match.id]);

  const merged = useMemo(() => {
    if (!sides) return [] as (TikTokMatchSideGifter & { side: GifterSide })[];
    const tag = (arr: TikTokMatchSideGifter[], s: GifterSide) =>
      arr.map((g) => ({ ...g, side: s }));
    let arr: (TikTokMatchSideGifter & { side: GifterSide })[] = [];
    if (side === 'all') {
      arr = [...tag(sides.host, 'host'), ...tag(sides.opponent, 'opponent'), ...tag(sides.unknown, 'unknown')];
    } else if (side === 'host')     arr = tag(sides.host, 'host');
    else if (side === 'opponent')   arr = tag(sides.opponent, 'opponent');
    else if (side === 'unknown')    arr = tag(sides.unknown, 'unknown');
    const needle = debouncedQ.toLowerCase();
    if (needle) {
      arr = arr.filter(
        (g) =>
          (g.unique_id || '').toLowerCase().includes(needle) ||
          (g.nickname || '').toLowerCase().includes(needle),
      );
    }
    if (minDiamonds !== '' && Number(minDiamonds) > 0) {
      const floor = Number(minDiamonds);
      arr = arr.filter((g) => g.diamonds >= floor);
    }
    arr.sort((a, b) => {
      switch (sort) {
        case 'gifts':          return b.gifts - a.gifts;
        case 'largest_single': return b.largest_single - a.largest_single;
        case 'diamonds':
        default:               return b.diamonds - a.diamonds;
      }
    });
    return arr;
  }, [sides, side, sort, debouncedQ, minDiamonds]);

  const totalPages = Math.max(1, Math.ceil(merged.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const offset = safePage * pageSize;
  const visible = merged.slice(offset, offset + pageSize);

  const since = match.started_at;
  const until = match.ended_at ?? match.last_seen_at;

  if (loading && !sides) {
    return (
      <div className="py-8 text-center text-sm text-gray-500">
        <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
        Loading gifters…
      </div>
    );
  }
  if (!sides) {
    return <p className="py-6 text-center text-sm text-gray-500">Failed to load.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      {/* Toolbar — row 1: side chips + sort + search */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex items-center gap-1">
          {(['all', 'host', 'opponent', 'unknown'] as GifterSide[]).map((s) => (
            <Pill
              key={s}
              kind="chip"
              active={side === s}
              onClick={() => setSide(s)}
            >
              {s === 'all'      ? 'All'
              : s === 'host'    ? `Backed @${hostHandle}`
              : s === 'opponent'? 'Backed opponent'
              : 'Unknown'}
              {sides && (
                <span className="ml-1 text-[10px] opacity-70">
                  (
                  {s === 'host'    ? sides.totals.host_gifters
                  : s === 'opponent'? sides.totals.opponent_gifters
                  : s === 'unknown'? sides.unknown.length
                  : sides.host.length + sides.opponent.length + sides.unknown.length}
                  )
                </span>
              )}
            </Pill>
          ))}
        </div>
        <Select
          value={sort}
          onChange={(e) => setSort(e.target.value as GifterSort)}
          className="text-xs font-mono"
        >
          <option value="diamonds">Sort: Diamonds</option>
          <option value="gifts">Sort: Gift count</option>
          <option value="largest_single">Sort: Largest single gift</option>
        </Select>
        <div className="relative ml-auto">
          <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <Input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search handle or nickname…"
            className="text-xs font-mono pl-7 w-full sm:w-64"
          />
        </div>
      </div>
      {/* Toolbar — row 2: min-diamonds + page size */}
      <div className="flex flex-wrap items-center gap-3 text-[11px] font-mono text-gray-500">
        <label className="inline-flex items-center gap-1.5">
          <Gem className="w-3 h-3 text-amber-500" />
          Min 💎
          <Input
            type="number"
            min={0}
            value={minDiamonds}
            onChange={(e) =>
              setMinDiamonds(e.target.value === '' ? '' : Number(e.target.value))
            }
            placeholder="0"
            className="text-xs font-mono w-24"
          />
        </label>
        <label className="inline-flex items-center gap-1.5">
          Page size
          <Select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="text-xs font-mono w-20"
          >
            {GIFTER_PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
        </label>
        <span className="ml-auto tabular-nums">
          {merged.length === 0
            ? '0 gifters'
            : `${(offset + 1).toLocaleString()}–${Math.min(
                offset + visible.length,
                merged.length,
              ).toLocaleString()} of ${merged.length.toLocaleString()}`}
        </span>
      </div>

      {merged.length === 0 ? (
        <p className="text-xs text-gray-500 text-center py-6">
          No gifters match the current filters.
        </p>
      ) : (
        <div className="rounded-lg border border-gray-200 overflow-x-auto">
          <table className="w-full text-xs min-w-[640px]">
            <thead className="bg-gray-50 dark:bg-white/[0.04]">
              <tr>
                <th className="px-3 py-1.5 text-left auth-mono-label">#</th>
                <th className="px-3 py-1.5 text-left auth-mono-label">Gifter</th>
                <th className="px-3 py-1.5 text-left auth-mono-label">Side</th>
                <th className="px-3 py-1.5 text-right auth-mono-label">Diamonds</th>
                <th className="px-3 py-1.5 text-right auth-mono-label">Gifts</th>
                <th className="px-3 py-1.5 text-right auth-mono-label">Largest</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((g, i) => {
                const display = g.nickname || g.unique_id || '—';
                const sideMeta = {
                  host:     { label: 'host',     class: 'bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' },
                  opponent: { label: 'opponent', class: 'bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300' },
                  unknown:  { label: '?',        class: 'bg-gray-100 text-gray-600' },
                  all:      { label: '—',        class: 'bg-gray-100 text-gray-600' },
                }[g.side];
                return (
                  <tr
                    key={`${g.user_id}-${g.side}`}
                    className="border-t border-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.04] cursor-pointer"
                    onClick={() =>
                      onSelectGifter?.({
                        userId: g.user_id,
                        uniqueId: g.unique_id,
                        nickname: g.nickname,
                        diamonds: g.diamonds,
                        gifts: g.gifts,
                        comments: 0,
                        tab: 'gifts',
                        since,
                        until,
                        windowLabel: 'This battle',
                      })
                    }
                  >
                    <td className="px-3 py-1.5 text-gray-400 tabular-nums">{offset + i + 1}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex items-center gap-2">
                        {g.avatar_url ? (
                          <img
                            src={g.avatar_url}
                            alt=""
                            className="w-6 h-6 rounded-full object-cover"
                            referrerPolicy="no-referrer"
                            loading="lazy"
                          />
                        ) : (
                          <div className="w-6 h-6 rounded-full bg-gray-200 dark:bg-white/10 text-gray-500 flex items-center justify-center text-[10px] font-bold">
                            {display[0]?.toUpperCase()}
                          </div>
                        )}
                        <span className="font-medium">{display}</span>
                        {g.unique_id && g.unique_id !== display && (
                          <span className="text-[10px] text-gray-500 font-mono">
                            @{g.unique_id}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-1.5">
                      <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider ${sideMeta.class}`}>
                        {sideMeta.label}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-amber-700 dark:text-amber-300 font-bold">
                      {g.diamonds.toLocaleString()}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                      {g.gifts.toLocaleString()}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono tabular-nums text-gray-500">
                      {g.largest_single.toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {/* Pagination — only when more than one page exists. */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-gray-500">
          <span>
            Page {safePage + 1} / {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={safePage === 0}
              onClick={() => setPage(0)}
              className="inline-flex items-center px-2 py-0.5 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
              aria-label="First page"
            >
              ‹‹
            </button>
            <button
              type="button"
              disabled={safePage === 0}
              onClick={() => setPage(safePage - 1)}
              className="inline-flex items-center px-2 py-0.5 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-3 h-3" />
            </button>
            <button
              type="button"
              disabled={safePage >= totalPages - 1}
              onClick={() => setPage(safePage + 1)}
              className="inline-flex items-center px-2 py-0.5 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
              aria-label="Next page"
            >
              <ChevronRight className="w-3 h-3" />
            </button>
            <button
              type="button"
              disabled={safePage >= totalPages - 1}
              onClick={() => setPage(totalPages - 1)}
              className="inline-flex items-center px-2 py-0.5 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
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

// ─── Tab: Activity (paginated event log) ────────────────────────────

const ALL_TYPE_KEYS = [
  'gift', 'comment', 'join', 'like', 'follow', 'share', 'match_start', 'match_update', 'match_end',
];
const PAGE_SIZES = [25, 50, 100, 250];

function ActivityTab({
  match,
}: {
  match: TikTokMatch;
  hostHandle: string;
}) {
  const { tz } = useTikTokTimezone();
  const [activeType, setActiveType] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [minDiamonds, setMinDiamonds] = useState<number | ''>('');
  const [pageSize, setPageSize] = useState(50);
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<TikTokEvent[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  // Debounce free-text + min-diamonds.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  // Reset offset whenever the filter set changes — old offset is
  // meaningless against a different result set.
  useEffect(() => {
    setOffset(0);
    setTotal(null);
  }, [activeType, debouncedQ, minDiamonds, pageSize, match.id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const md = minDiamonds === '' ? undefined : Number(minDiamonds);
    Promise.all([
      tiktokApi.searchEvents({
        match_id: match.id,
        type: activeType || undefined,
        q: debouncedQ || undefined,
        min_diamonds: md,
        limit: pageSize,
        offset,
      }),
      total === null
        ? tiktokApi.countEvents({
            match_id: match.id,
            type: activeType || undefined,
            q: debouncedQ || undefined,
            min_diamonds: md,
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
  }, [match.id, activeType, debouncedQ, minDiamonds, pageSize, offset]);

  const realTotal = total ?? 0;
  const totalPages = Math.max(1, Math.ceil(realTotal / pageSize));
  const currentPage = Math.floor(offset / pageSize) + 1;

  return (
    <div className="flex flex-col gap-3">
      {/* Filter toolbar */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1">
          <Pill
            kind="chip"
            active={activeType === null}
            onClick={() => setActiveType(null)}
          >
            All
          </Pill>
          {ALL_TYPE_KEYS.map((t) => {
            const meta = metaFor(t);
            return (
              <Pill
                key={t}
                kind="chip"
                active={activeType === t}
                onClick={() => setActiveType(activeType === t ? null : t)}
              >
                {meta.icon}
                {meta.label}
              </Pill>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            <Input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search payload (text, gift name, handle)…"
              className="text-xs font-mono pl-7 w-full"
            />
          </div>
          <label className="text-[11px] font-mono text-gray-500 inline-flex items-center gap-1.5">
            Min 💎
            <Input
              type="number"
              min={0}
              value={minDiamonds}
              onChange={(e) =>
                setMinDiamonds(e.target.value === '' ? '' : Number(e.target.value))
              }
              className="text-xs font-mono w-24"
            />
          </label>
          <label className="text-[11px] font-mono text-gray-500 inline-flex items-center gap-1.5">
            Page size
            <Select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="text-xs font-mono w-20"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </label>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-gray-50 dark:bg-white/[0.04]">
            <tr>
              <th className="px-3 py-2 text-left auth-mono-label">When</th>
              <th className="px-3 py-2 text-left auth-mono-label">Type</th>
              <th className="px-3 py-2 text-left auth-mono-label">User</th>
              <th className="px-3 py-2 text-left auth-mono-label">Detail</th>
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-8 text-center text-gray-500">
                  <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
                  Loading events…
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-8 text-center text-gray-500">
                  No events match the current filters.
                </td>
              </tr>
            )}
            {items.map((e) => {
              const p = (e.payload || {}) as Record<string, unknown>;
              const u =
                (p.user as { unique_id?: string; nickname?: string } | undefined) ||
                {};
              const meta = metaFor(e.type);
              return (
                <tr key={e.id} className="border-t border-gray-200">
                  <td className="px-3 py-1.5 font-mono text-xs text-gray-500 whitespace-nowrap">
                    {fmtTime(e.ts, tz)}
                  </td>
                  <td className="px-3 py-1.5">
                    <span
                      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] ${meta.tone}`}
                    >
                      {meta.icon}
                      {meta.label}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-xs">
                    {u.nickname && <span className="font-medium">{u.nickname}</span>}
                    {u.unique_id && (
                      <span className="ml-1 font-mono text-[11px] text-gray-500">
                        @{u.unique_id}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-xs text-gray-700">
                    {summarize(e)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-gray-500">
        <span>
          {realTotal === 0
            ? '0'
            : `${(offset + 1).toLocaleString()}–${Math.min(
                offset + items.length,
                realTotal,
              ).toLocaleString()} of ${realTotal.toLocaleString()}`}
        </span>
        <div className="flex items-center gap-1">
          <span>
            Page {currentPage} / {totalPages}
          </span>
          <button
            type="button"
            disabled={offset === 0 || loading}
            onClick={() => setOffset(Math.max(0, offset - pageSize))}
            className="inline-flex items-center px-2 py-0.5 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
          >
            <ChevronLeft className="w-3 h-3" />
          </button>
          <button
            type="button"
            disabled={offset + pageSize >= realTotal || loading}
            onClick={() => setOffset(offset + pageSize)}
            className="inline-flex items-center px-2 py-0.5 rounded border border-gray-200 disabled:opacity-30 hover:bg-gray-100 dark:hover:bg-white/10"
          >
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Tab: Head-to-head ──────────────────────────────────────────────

function HeadToHeadTab({
  match,
  hostHandle,
  onOpenMatch,
}: {
  match: TikTokMatch;
  hostHandle: string;
  /** Click-through: when a row is clicked, swap the modal context to
   *  that prior battle. Parent owns the `selectedMatch` state. */
  onOpenMatch?: (matchId: number) => void;
}) {
  const { tz } = useTikTokTimezone();
  const [rows, setRows] = useState<TikTokMatchHeadToHeadRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [regulars, setRegulars] = useState<TikTokH2HCommonGifter[] | null>(null);
  const [opponentFilter, setOpponentFilter] = useState<string | 'all'>('all');
  const [outcomeFilter, setOutcomeFilter] = useState<'all' | 'won' | 'lost' | 'draw'>('all');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      tiktokApi.getMatchHeadToHead(match.id, { limit: 50 }),
      tiktokApi.getH2HCommonGifters(match.id, { min_battles: 2, limit: 12 }).catch(() => []),
    ])
      .then(([r, g]) => {
        if (cancelled) return;
        setRows(r);
        setRegulars(g);
      })
      .catch(() => {
        if (cancelled) return;
        setRows([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [match.id]);

  // Distinct opponents across the H2H set — drives the opponent
  // filter chips. We use unique_id so the same person isn't double-
  // counted across nickname changes.
  const distinctOpps = useMemo(() => {
    if (!rows) return [] as string[];
    const set = new Set<string>();
    for (const r of rows) {
      for (const h of r.opponent_handles ?? []) set.add(h);
    }
    return Array.from(set).sort();
  }, [rows]);

  const filtered = useMemo(() => {
    if (!rows) return [];
    return rows.filter((r) => {
      if (opponentFilter !== 'all' && !(r.opponent_handles ?? []).includes(opponentFilter)) {
        return false;
      }
      if (outcomeFilter !== 'all' && r.outcome !== outcomeFilter) {
        return false;
      }
      return true;
    });
  }, [rows, opponentFilter, outcomeFilter]);

  // Aggregate stats over the *filtered* rows so the KPI strip
  // honors the active filter.
  const stats = useMemo(() => {
    const t = { won: 0, lost: 0, draw: 0, ended: 0 };
    let netDiff = 0;
    let scoredCount = 0;
    let firstTs: number | null = null;
    let lastTs: number | null = null;
    for (const r of filtered) {
      if (r.outcome === 'won')      t.won  += 1;
      else if (r.outcome === 'lost') t.lost += 1;
      else if (r.outcome === 'draw') t.draw += 1;
      else                           t.ended += 1;
      if (r.host_score != null && r.opp_score != null) {
        netDiff += r.host_score - r.opp_score;
        scoredCount += 1;
      }
      if (r.started_at) {
        const ms = new Date(r.started_at).getTime();
        if (!firstTs || ms < firstTs) firstTs = ms;
        if (!lastTs  || ms > lastTs)  lastTs  = ms;
      }
    }
    // Cadence = battles per week between first and last seen.
    const spanWeeks =
      firstTs && lastTs
        ? Math.max((lastTs - firstTs) / (7 * 86_400_000), 1 / 7)
        : 1;
    const cadence = filtered.length / spanWeeks;
    const lastDaysAgo =
      lastTs ? Math.floor((Date.now() - lastTs) / 86_400_000) : null;
    // Outcome streak (most recent first — the table is sorted DESC).
    let streak = 0;
    let streakKind: 'won' | 'lost' | 'draw' | null = null;
    for (const r of filtered) {
      if (r.outcome === 'ended') { break; }
      if (streakKind == null) streakKind = r.outcome ?? null;
      if (r.outcome === streakKind) streak += 1;
      else break;
    }
    // Per-opponent records.
    const perOpp = new Map<string, { won: number; lost: number; draw: number; ended: number }>();
    for (const r of filtered) {
      for (const h of r.opponent_handles ?? []) {
        const cur = perOpp.get(h) ?? { won: 0, lost: 0, draw: 0, ended: 0 };
        const k: 'won' | 'lost' | 'draw' | 'ended' = r.outcome ?? 'ended';
        cur[k] += 1;
        perOpp.set(h, cur);
      }
    }
    // Verdict — composite read of the rivalry's character.
    const total = filtered.length;
    let verdict: 'heated' | 'lopsided' | 'casual' | 'one-off' = 'one-off';
    if (total >= 2) {
      const winRate = total > 0 ? (t.won + t.lost) / total : 0;
      const dominance =
        Math.max(t.won, t.lost) /
        Math.max(1, t.won + t.lost + t.draw);
      if (cadence >= 1 && winRate >= 0.7 && dominance < 0.7) verdict = 'heated';
      else if (dominance >= 0.7 && total >= 4)               verdict = 'lopsided';
      else if (total >= 4)                                   verdict = 'casual';
    }
    return {
      tally: t,
      netDiff,
      scoredCount,
      cadence,
      lastDaysAgo,
      streak,
      streakKind,
      perOpp,
      verdict,
    };
  }, [filtered]);

  if (loading && !rows) {
    return (
      <div className="py-8 text-center text-sm text-gray-500">
        <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
        Loading head-to-head…
      </div>
    );
  }
  if (!rows || rows.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-gray-500">
        No prior battles between @{hostHandle} and these opponents.
      </p>
    );
  }

  // Pre-compute marquee battles (top 3 by ingested diamonds).
  const marquee = [...filtered]
    .filter((r) => r.diamonds_total > 0)
    .sort((a, b) => b.diamonds_total - a.diamonds_total)
    .slice(0, 3);

  return (
    <div className="flex flex-col gap-4">
      {/* KPI strip */}
      <H2HKpiStrip
        hostHandle={hostHandle}
        stats={stats}
        total={filtered.length}
      />
      {/* Per-opponent record breakdown */}
      {stats.perOpp.size >= 2 && (
        <H2HPerOpponentBars perOpp={stats.perOpp} />
      )}
      {/* Score-margin trend */}
      {filtered.length >= 2 && (
        <H2HMarginTrend rows={filtered} hostHandle={hostHandle} />
      )}
      {/* Marquee battles */}
      {marquee.length > 0 && (
        <H2HMarqueeBattles
          marquee={marquee}
          hostHandle={hostHandle}
          tz={tz}
          onOpen={onOpenMatch}
        />
      )}
      {/* Common gifters bench (regulars). Phase C — only shows when
          we have ≥1 regular. */}
      {regulars && regulars.length > 0 && (
        <H2HRegulars regulars={regulars} />
      )}
      {/* Filters + table */}
      <H2HFilters
        opponents={distinctOpps}
        opponent={opponentFilter}
        setOpponent={setOpponentFilter}
        outcome={outcomeFilter}
        setOutcome={setOutcomeFilter}
        shown={filtered.length}
        total={rows.length}
      />
      <H2HRowsTable
        rows={filtered}
        hostHandle={hostHandle}
        tz={tz}
        onOpen={onOpenMatch}
      />
    </div>
  );
}

// ─── H2H sub-components ─────────────────────────────────────────────

type H2HStats = {
  tally: { won: number; lost: number; draw: number; ended: number };
  netDiff: number;
  scoredCount: number;
  cadence: number;
  lastDaysAgo: number | null;
  streak: number;
  streakKind: 'won' | 'lost' | 'draw' | null;
  perOpp: Map<string, { won: number; lost: number; draw: number; ended: number }>;
  verdict: 'heated' | 'lopsided' | 'casual' | 'one-off';
};

function H2HKpiStrip({
  hostHandle,
  stats,
  total,
}: {
  hostHandle: string;
  stats: H2HStats;
  total: number;
}) {
  const verdictMeta = {
    heated:    { label: '🔥 Heated rivalry',    tone: 'rose'    as const },
    lopsided:  { label: '⚖ Lopsided',           tone: 'amber'   as const },
    casual:    { label: '◯ Casual matchup',     tone: 'sky'     as const },
    'one-off': { label: '· One-off encounter',  tone: 'gray'    as const },
  }[stats.verdict];
  const verdictClass = {
    rose:    'bg-rose-100 dark:bg-rose-500/20 text-rose-800 dark:text-rose-200 ring-rose-300 dark:ring-rose-500/40',
    amber:   'bg-amber-100 dark:bg-amber-500/20 text-amber-800 dark:text-amber-200 ring-amber-300 dark:ring-amber-500/40',
    sky:     'bg-sky-100 dark:bg-sky-500/20 text-sky-800 dark:text-sky-200 ring-sky-300 dark:ring-sky-500/40',
    gray:    'bg-gray-100 text-gray-700 ring-gray-200',
  }[verdictMeta.tone];
  const streakChip = stats.streakKind && stats.streak > 1
    ? {
        won:  { label: `W${stats.streak}`, cls: 'text-emerald-700 dark:text-emerald-300' },
        lost: { label: `L${stats.streak}`, cls: 'text-rose-700 dark:text-rose-300' },
        draw: { label: `D${stats.streak}`, cls: 'text-amber-700 dark:text-amber-300' },
      }[stats.streakKind]
    : null;
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="auth-mono-label flex items-center gap-1.5">
            <Trophy className="w-3.5 h-3.5 text-amber-500" />
            @{hostHandle} vs these opponents
          </span>
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-mono ring-1 ${verdictClass}`}>
            {verdictMeta.label}
          </span>
          {streakChip && (
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-mono bg-gray-100 dark:bg-white/10 ${streakChip.cls}`}>
              streak {streakChip.label}
            </span>
          )}
        </div>
        <span className="ml-auto text-[11px] font-mono text-gray-500 tabular-nums">
          {total} battle{total === 1 ? '' : 's'}
        </span>
      </div>
      {/* Headline numbers — bigger than the old 4-cell grid. */}
      <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
            Record
          </div>
          <div className="mt-0.5 text-2xl font-bold tabular-nums">
            <span className="text-emerald-700 dark:text-emerald-300">{stats.tally.won}</span>
            <span className="text-gray-400 mx-1">–</span>
            <span className="text-rose-700 dark:text-rose-300">{stats.tally.lost}</span>
            {stats.tally.draw > 0 && (
              <>
                <span className="text-gray-400 mx-1">–</span>
                <span className="text-amber-700 dark:text-amber-300">{stats.tally.draw}</span>
              </>
            )}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
            Net PK points
          </div>
          <div
            className={`mt-0.5 text-base font-bold tabular-nums ${
              stats.netDiff > 0
                ? 'text-emerald-700 dark:text-emerald-300'
                : stats.netDiff < 0
                  ? 'text-rose-700 dark:text-rose-300'
                  : 'text-gray-500'
            }`}
            title={`Sum of host_score - opp_score across ${stats.scoredCount} resolved battles`}
          >
            {stats.netDiff >= 0 ? '+' : '−'}{compact(Math.abs(stats.netDiff))}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
            Cadence
          </div>
          <div className="mt-0.5 text-base font-bold tabular-nums">
            {stats.cadence < 1
              ? `${stats.cadence.toFixed(1)}/wk`
              : `${stats.cadence.toFixed(1)} battles/wk`}
          </div>
          {stats.lastDaysAgo != null && (
            <div className="text-[10px] text-gray-500 tabular-nums">
              last {stats.lastDaysAgo === 0 ? 'today' : `${stats.lastDaysAgo}d ago`}
            </div>
          )}
        </div>
        {stats.tally.ended > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
              Unresolved
            </div>
            <div
              className="mt-0.5 text-base font-bold tabular-nums text-gray-500"
              title="Battles where neither match.scores nor opponents[].score were populated"
            >
              {stats.tally.ended}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function H2HPerOpponentBars({
  perOpp,
}: {
  perOpp: H2HStats['perOpp'];
}) {
  const entries = Array.from(perOpp.entries()).sort(
    (a, b) => b[1].won + b[1].lost + b[1].draw - (a[1].won + a[1].lost + a[1].draw),
  );
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label mb-2">Per-opponent record</div>
      <ul className="flex flex-col gap-1.5 text-xs font-mono">
        {entries.map(([handle, rec]) => {
          const total = rec.won + rec.lost + rec.draw + rec.ended;
          if (total === 0) return null;
          return (
            <li
              key={handle}
              className="flex items-center gap-2 px-2 py-1 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
            >
              <span className="shrink-0 w-32 truncate text-gray-900">@{handle}</span>
              <div className="flex-1 h-2 rounded-full overflow-hidden flex bg-gray-200 dark:bg-white/10">
                {rec.won  > 0 && <div className="bg-emerald-500" style={{ width: `${(rec.won  / total) * 100}%` }} title={`${rec.won} won`} />}
                {rec.lost > 0 && <div className="bg-rose-500"    style={{ width: `${(rec.lost / total) * 100}%` }} title={`${rec.lost} lost`} />}
                {rec.draw > 0 && <div className="bg-amber-500"   style={{ width: `${(rec.draw / total) * 100}%` }} title={`${rec.draw} draw`} />}
                {rec.ended > 0 && <div className="bg-gray-400"   style={{ width: `${(rec.ended / total) * 100}%` }} title={`${rec.ended} unresolved`} />}
              </div>
              <span className="shrink-0 tabular-nums">
                <span className="text-emerald-700 dark:text-emerald-300">{rec.won}</span>
                <span className="text-gray-400">–</span>
                <span className="text-rose-700 dark:text-rose-300">{rec.lost}</span>
                {rec.draw > 0 && (
                  <>
                    <span className="text-gray-400">–</span>
                    <span className="text-amber-700 dark:text-amber-300">{rec.draw}</span>
                  </>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function H2HMarginTrend({
  rows,
  hostHandle: _hostHandle,
}: {
  rows: TikTokMatchHeadToHeadRow[];
  hostHandle: string;
}) {
  const isDark = useDarkMode();
  const t = chartTheme(isDark);
  // Order oldest → newest for the trend reading.
  const ordered = [...rows].reverse().filter((r) => r.margin != null);
  const xLabels = ordered.map((r) =>
    r.started_at ? new Date(r.started_at).toISOString().slice(5, 16).replace('T', ' ') : '',
  );
  const margins = ordered.map((r) => r.margin ?? 0);
  const positives = margins.map((v) => (v > 0 ? v : 0));
  const negatives = margins.map((v) => (v < 0 ? v : 0));
  const option = {
    grid: { left: 56, right: 12, top: 24, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: { dataIndex: number }[]) => {
        const idx = params[0]?.dataIndex ?? 0;
        const r = ordered[idx];
        if (!r) return '';
        return [
          new Date(r.started_at!).toLocaleString(),
          r.opponent_handles?.length ? `vs @${r.opponent_handles.join(', @')}` : '',
          `${r.host_score} – ${r.opp_score} (${(r.margin ?? 0) >= 0 ? '+' : '−'}${compact(Math.abs(r.margin ?? 0))})`,
        ].filter(Boolean).join('<br/>');
      },
    },
    xAxis: {
      type: 'category',
      data: xLabels,
      axisLabel: { fontSize: 9, color: t.axisLabel, hideOverlap: true },
      axisLine: { lineStyle: { color: t.axisLine } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 9, color: t.axisLabel, formatter: (v: number) => compact(v) },
      splitLine: { lineStyle: { color: t.splitLine } },
      axisLine: { lineStyle: { color: t.axisLine } },
    },
    series: [
      {
        // Wins above zero (emerald), losses below (rose). One bar
        // chart, divergent semantics.
        name: 'host margin',
        type: 'bar',
        stack: 'm',
        color: '#10b981',
        data: positives,
      },
      {
        name: 'opponent margin',
        type: 'bar',
        stack: 'm',
        color: '#f43f5e',
        data: negatives,
      },
    ],
  };
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <TrendingUp className="w-3.5 h-3.5 text-primary-500" />
        Score-margin trend
        <span className="ml-2 text-gray-500 font-mono normal-case text-[11px]">
          host above zero, opponent below — is the gap closing or widening?
        </span>
      </div>
      <ReactECharts
        echarts={echarts}
        option={option}
        style={{ height: 200, minHeight: 160 }}
        notMerge
        lazyUpdate
      />
    </section>
  );
}

function H2HMarqueeBattles({
  marquee,
  hostHandle: _hostHandle,
  tz,
  onOpen,
}: {
  marquee: TikTokMatchHeadToHeadRow[];
  hostHandle: string;
  tz: string;
  onOpen?: (id: number) => void;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Award className="w-3.5 h-3.5 text-amber-500" />
        Marquee battles
        <span className="ml-2 text-gray-500 font-mono normal-case text-[11px]">
          highest combined diamonds we ingested
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {marquee.map((m) => {
          const outcomeTone = {
            won:   'text-emerald-700 dark:text-emerald-300',
            lost:  'text-rose-700 dark:text-rose-300',
            draw:  'text-amber-700 dark:text-amber-300',
            ended: 'text-gray-500',
          }[m.outcome ?? 'ended'];
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => onOpen?.(m.id)}
              className="text-left rounded-md border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06] hover:bg-gray-100 dark:hover:bg-white/10 transition-colors px-3 py-2"
              title="Open this battle in the modal"
            >
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <span className="text-[10px] font-mono text-gray-500">
                  {fmtTs(m.started_at, tz)}
                </span>
                <span className={`text-[10px] font-mono uppercase tracking-wider font-bold ${outcomeTone}`}>
                  {m.outcome}
                </span>
              </div>
              <div className="text-xs font-mono text-gray-700 truncate">
                vs {(m.opponent_handles ?? []).slice(0, 2).map((h) => `@${h}`).join(', ')}
              </div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-base font-bold tabular-nums text-amber-700 dark:text-amber-300 inline-flex items-baseline gap-0.5">
                  <Gem className="w-3 h-3 self-center" />
                  {compact(m.diamonds_total)}
                </span>
                {m.host_score != null && m.opp_score != null && (
                  <span className="text-[11px] font-mono text-gray-500 tabular-nums">
                    {compact(m.host_score)}–{compact(m.opp_score)}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function H2HRegulars({
  regulars,
}: {
  regulars: TikTokH2HCommonGifter[];
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white dark:bg-gray-100/[0.05] p-4 shadow-sm">
      <div className="auth-mono-label flex items-center gap-1.5 mb-2">
        <Users className="w-3.5 h-3.5 text-primary-500" />
        The regulars
        <span className="ml-2 text-gray-500 font-mono normal-case text-[11px]">
          gifters who showed up to ≥2 of these battles
        </span>
      </div>
      <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
        {regulars.map((g) => {
          const display = g.nickname || g.unique_id || `User ${g.user_id}`;
          return (
            <li
              key={g.user_id}
              className="flex items-center gap-2 px-2 py-1.5 rounded border border-gray-200 bg-gray-50 dark:bg-gray-100/[0.06]"
            >
              {g.avatar_url ? (
                <img
                  src={g.avatar_url}
                  alt=""
                  className="w-7 h-7 rounded-full object-cover ring-1 ring-gray-200 dark:ring-white/10 shrink-0"
                  referrerPolicy="no-referrer"
                  loading="lazy"
                />
              ) : (
                <div className="w-7 h-7 rounded-full bg-gray-200 dark:bg-white/10 text-gray-500 flex items-center justify-center text-[10px] font-bold shrink-0">
                  {display[0]?.toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs">{display}</div>
                {g.unique_id && g.unique_id !== display && (
                  <div className="truncate text-[10px] font-mono text-gray-500">@{g.unique_id}</div>
                )}
              </div>
              <div className="shrink-0 text-right text-[10px] font-mono">
                <div className="text-primary-700 dark:text-primary-300 tabular-nums">
                  {g.battles}× battles
                </div>
                {g.diamonds > 0 && (
                  <div className="text-amber-700 dark:text-amber-300 tabular-nums inline-flex items-baseline gap-0.5">
                    <Gem className="w-3 h-3 self-center" />
                    {compact(g.diamonds)}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function H2HFilters({
  opponents,
  opponent,
  setOpponent,
  outcome,
  setOutcome,
  shown,
  total,
}: {
  opponents: string[];
  opponent: string | 'all';
  setOpponent: (v: string | 'all') => void;
  outcome: 'all' | 'won' | 'lost' | 'draw';
  setOutcome: (v: 'all' | 'won' | 'lost' | 'draw') => void;
  shown: number;
  total: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {opponents.length >= 2 && (
        <div className="inline-flex items-center gap-1 flex-wrap">
          <Pill kind="chip" active={opponent === 'all'} onClick={() => setOpponent('all')}>
            All opponents
          </Pill>
          {opponents.map((h) => (
            <Pill
              key={h}
              kind="chip"
              active={opponent === h}
              onClick={() => setOpponent(h)}
            >
              @{h}
            </Pill>
          ))}
        </div>
      )}
      <div className="inline-flex items-center gap-1">
        {(['all', 'won', 'lost', 'draw'] as const).map((o) => (
          <Pill
            key={o}
            kind="chip"
            active={outcome === o}
            onClick={() => setOutcome(o)}
          >
            {o === 'all' ? 'Any outcome' : o}
          </Pill>
        ))}
      </div>
      <span className="ml-auto text-[11px] font-mono text-gray-500 tabular-nums">
        {shown.toLocaleString()} of {total.toLocaleString()} shown
      </span>
    </div>
  );
}

function H2HRowsTable({
  rows,
  hostHandle: _hostHandle,
  tz,
  onOpen,
}: {
  rows: TikTokMatchHeadToHeadRow[];
  hostHandle: string;
  tz: string;
  onOpen?: (id: number) => void;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-xs text-gray-500 text-center py-3">
        No battles match the current filters.
      </p>
    );
  }
  return (
    <section className="rounded-lg border border-gray-200 overflow-x-auto">
      <table className="w-full text-xs min-w-[640px]">
        <thead className="bg-gray-50 dark:bg-white/[0.04]">
          <tr>
            <th className="px-3 py-1.5 text-left auth-mono-label">When</th>
            <th className="px-3 py-1.5 text-left auth-mono-label">Opponent(s)</th>
            <th className="px-3 py-1.5 text-right auth-mono-label">Score</th>
            <th className="px-3 py-1.5 text-right auth-mono-label">Margin</th>
            <th className="px-3 py-1.5 text-right auth-mono-label">Diamonds</th>
            <th className="px-3 py-1.5 text-right auth-mono-label">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const tone = {
              won:   'text-emerald-700 dark:text-emerald-300',
              lost:  'text-rose-700 dark:text-rose-300',
              draw:  'text-amber-700 dark:text-amber-300',
              ended: 'text-gray-500',
            }[r.outcome ?? 'ended'];
            // Decisive vs nail-biter pill on the margin column.
            const decisiveBadge =
              r.decisive_pct != null
                ? r.decisive_pct >= 50
                  ? { label: 'decisive', cls: 'bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-300' }
                  : r.decisive_pct >= 20
                    ? { label: 'comfortable', cls: 'bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300' }
                    : { label: 'close', cls: 'bg-sky-100 dark:bg-sky-500/15 text-sky-700 dark:text-sky-300' }
                : null;
            return (
              <tr
                key={r.id}
                className="border-t border-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.04] cursor-pointer"
                onClick={() => onOpen?.(r.id)}
                title="Open this battle"
              >
                <td className="px-3 py-1.5 text-gray-500 font-mono whitespace-nowrap">
                  {fmtTs(r.started_at, tz)}
                </td>
                <td className="px-3 py-1.5">
                  {(r.opponent_handles ?? []).slice(0, 3).map((h) => `@${h}`).join(', ')}
                  {(r.opponent_handles?.length ?? 0) > 3 && (
                    <span className="text-gray-500"> +{(r.opponent_handles?.length ?? 0) - 3}</span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                  {r.host_score != null && r.opp_score != null
                    ? `${compact(r.host_score)}–${compact(r.opp_score)}`
                    : '—'}
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                  {r.margin != null ? (
                    <span className="inline-flex items-center gap-1.5 justify-end">
                      <span className={r.margin > 0 ? 'text-emerald-700 dark:text-emerald-300' : r.margin < 0 ? 'text-rose-700 dark:text-rose-300' : 'text-gray-500'}>
                        {r.margin >= 0 ? '+' : '−'}{compact(Math.abs(r.margin))}
                      </span>
                      {decisiveBadge && (
                        <span className={`text-[9px] uppercase tracking-wider px-1 py-0.5 rounded-full ${decisiveBadge.cls}`}>
                          {decisiveBadge.label}
                        </span>
                      )}
                    </span>
                  ) : '—'}
                </td>
                <td
                  className="px-3 py-1.5 text-right font-mono tabular-nums text-amber-700 dark:text-amber-300"
                  title="Diamonds we ingested for this match. May be 0 when only the opponent's stream had gifts."
                >
                  {r.diamonds_total > 0 ? r.diamonds_total.toLocaleString() : '—'}
                </td>
                <td
                  className={`px-3 py-1.5 text-right font-mono uppercase tracking-wider text-[10px] font-bold ${tone}`}
                >
                  {r.outcome}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

// ─── Pill primitive — replaces the old Pair / FilterChip / TabButton.

interface PillProps {
  kind: 'tab' | 'chip';
  active: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}

function Pill({ kind, active, onClick, children }: PillProps) {
  if (kind === 'tab') {
    return (
      <button
        type="button"
        role="tab"
        aria-selected={active}
        onClick={onClick}
        className={`shrink-0 inline-flex items-center gap-1.5 px-3 py-2 text-xs font-mono uppercase tracking-wider border-b-2 -mb-px transition-colors ${
          active
            ? 'border-primary-500 text-primary-700 dark:text-primary-300'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
        }`}
      >
        {children}
      </button>
    );
  }
  // chip
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-mono transition-colors border ${
        active
          ? 'bg-primary-100 dark:bg-primary-500/20 border-primary-300 text-primary-700 dark:text-primary-300'
          : 'bg-white dark:bg-white/5 border-gray-200 text-gray-700 hover:border-gray-300'
      }`}
    >
      {children}
    </button>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────

function summarizeOpponents(m: TikTokMatch, hostHandle: string): string {
  const others = (m.opponents ?? [])
    .map((o) => o.unique_id || o.nickname)
    .filter((s): s is string => Boolean(s) && s !== hostHandle);
  if (others.length === 0) return '';
  return `vs ${others.map((h) => `@${h.replace(/^@/, '')}`).join(', ')}`;
}

/** Resolve (hostScore, oppScore) from whichever signal carried the
 *  data. TikTok delivers PK scores via three paths the lib decodes
 *  into different fields:
 *    1. `match.scores: {team_id: score}` (older protocol, team-PK)
 *    2. `match.scores: {user_id: score}` (newer 1v1 — backend
 *        coalesces `match_update.opponent_scores` into this shape)
 *    3. `opponents[i].score` per anchor entry (always populated on
 *        match end, regardless of protocol version)
 *  Different battles use different shapes — the resolver tries them
 *  in order and falls through on empty/missing data. */
function resolveScores(
  m: { opponents?: TikTokMatchOpponent[]; scores?: Record<string, number> },
  hostHandle: string,
): { hostScore: number | null; oppScore: number | null } {
  const opps = m.opponents ?? [];
  const oppKeys = new Set<string>();
  const hostKeys = new Set<string>();
  for (const o of opps) {
    const isOpp = (o.unique_id || o.nickname) !== hostHandle;
    const set = isOpp ? oppKeys : hostKeys;
    if (o.team_id != null) set.add(String(o.team_id));
    if (o.user_id != null) set.add(String(o.user_id));
  }
  const teamEntries = Object.entries(m.scores || {});
  if (teamEntries.length >= 2) {
    let hostScore: number | null = null;
    let oppScore: number | null = null;
    for (const [k, v] of teamEntries) {
      if (hostKeys.has(k))      { if (hostScore == null) hostScore = Number(v); }
      else if (oppKeys.has(k))  { if (oppScore  == null) oppScore  = Number(v); }
    }
    if (hostScore != null && oppScore != null) {
      return { hostScore, oppScore };
    }
  }
  // Path 3: opponents[].score fallback.
  const hostEntry = opps.find(
    (o) => (o.unique_id || o.nickname) === hostHandle && o.score != null,
  );
  const oppEntry = opps.find(
    (o) => (o.unique_id || o.nickname) !== hostHandle && o.score != null,
  );
  return {
    hostScore: hostEntry?.score != null ? Number(hostEntry.score) : null,
    oppScore:  oppEntry?.score  != null ? Number(oppEntry.score)  : null,
  };
}

function summarize(e: TikTokEvent): string {
  const p = (e.payload || {}) as Record<string, unknown>;
  if (e.type === 'comment') return String(p.text ?? '').slice(0, 200);
  if (e.type === 'gift') {
    const base = `${p.gift_name ?? 'gift'} ×${p.repeat_count ?? 1} · ${
      Number(p.diamond_count ?? 0) * Number(p.repeat_count ?? 1)
    }💎`;
    const to = p.to_user as
      | { unique_id?: string; nickname?: string }
      | undefined;
    const dest = to && (to.nickname || to.unique_id);
    return dest ? `${base} → ${to.nickname || `@${to.unique_id}`}` : base;
  }
  if (e.type === 'like') return `liked ×${p.count ?? 1}`;
  if (e.type === 'join') return 'joined';
  if (e.type === 'follow') return 'followed';
  if (e.type === 'share') return 'shared';
  if (e.type === 'match_start') return 'PK battle started';
  if (e.type === 'match_end') return `PK battle ended (${p.reason ?? 'completed'})`;
  if (e.type === 'match_update') {
    const scores = p.scores as Record<string, number> | undefined;
    if (scores) {
      const teams = Object.entries(scores)
        .map(([t, s]) => `team${t}:${s}`)
        .join(' · ');
      return `score ${teams}`;
    }
    return 'score update';
  }
  return JSON.stringify(p).slice(0, 150);
}

function fmtTs(iso: string | null, tz: string): string {
  if (!iso) return '—';
  const p = partsInZone(iso, tz);
  return `${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

function fmtTime(iso: string, tz: string): string {
  if (!iso) return '—';
  const p = partsInZone(iso, tz);
  return `${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}

// `AnimatedScore` moved to a shared component so the in-progress
// PK card on `/admin/tiktok/$handle` can use the same animation.
// See `@admin/components/AnimatedScore`.


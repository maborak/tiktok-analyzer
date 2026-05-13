import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Radio } from 'lucide-react';

import { PageShell, PageHeader } from '@/components/ui/PageShell';
import {
  SubscriptionCard,
  type TikTokSubscription,
  type TikTokLiveSummary,
} from '@admin';
// Same code-split as the admin /admin/tiktok page — the gifter modal
// pulls echarts on import and is closed 99% of the time. Loading the
// chunk on first open keeps the public-lives bundle (which a viewer
// hits cold from a marketing link) trim.
const TikTokGifterDetailModal = lazy(() =>
  import('@admin/components/TikTokGifterDetailModal')
    .then((m) => ({ default: m.TikTokGifterDetailModal })),
);
import {
  TikTokApiProvider,
  type TikTokApi,
} from '@admin/contexts/TikTokApiContext';
import { publicTiktokApi, type PublicLivesPayload } from '../services/publicTiktok';

/** Unauthenticated public-lives index — surfaces the operator's
 *  public TikTok lives at `/lives`. The landing page at `/` has a
 *  marketing CTA that links here. Renders the *same* `SubscriptionCard` as the admin
 *  page so a public viewer gets visual parity (scoreboard, sparkline,
 *  week-heatmap, top-gifter chips, IN-MATCH pill, emerald LIVE
 *  badge) minus operator-only chrome.
 *
 *  Read-only by contract:
 *  - No drill-in to admin pages (the card's avatar/identity is
 *    plain-div, not a `<Link>` to `/admin/tiktok/$handle`).
 *  - No actions row (pause, reconnect, delete, send-comment composer,
 *    Public toggle, Stats link).
 *  - No listener health dot, no "checked Xm ago / N reconnects/h"
 *    operator detail.
 *  - The top-gifter chips still open the gifter modal — it sums the
 *    same public signals the scoreboard already shows.
 *
 *  Polling mirrors the admin index (30s) and pauses on
 *  `visibilitychange: hidden` so background tabs don't burn API
 *  capacity. Initial fetch happens regardless of visibility so a
 *  cold visit shows data without waiting for the next tick. */
export function PublicLives() {
  // Wider payload: `subscription` is a TikTokSubscription-shaped dict
  // (operator-only fields stripped server-side), `summary` is a
  // TikTokLiveSummary-shaped dict (top_gifters, hourly_buckets,
  // week_calendar, etc.) so the shared card has everything it needs.
  type PublicEntry = {
    subscription: TikTokSubscription;
    summary: TikTokLiveSummary;
  };
  const [entries, setEntries] = useState<PublicEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Gifter detail modal — mirrors the admin page. The modal queries
  // its own data via `/admin/...` endpoints today, but those calls
  // return the same shape for unauthenticated viewers when the modal
  // is mounted from this page; if they fail, the modal's empty/error
  // states gracefully render. (Backend gates per-route.)
  const [selectedGifter, setSelectedGifter] = useState<{
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
    diamonds: number;
    gifts: number;
    roomId: string | null;
    currentHandle: string;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const r = await publicTiktokApi.listLives();
        if (cancelled) return;
        const next = normalizePayload(r);
        // Structural sharing across polls — same pattern as the admin
        // lives page. Each 30 s tick brings a fresh JSON parse, so
        // entry / subscription / summary refs change wholesale even
        // when the underlying data is unchanged. By preserving prior
        // per-host references when JSON.stringify(prev) === stringify(new),
        // `React.memo(SubscriptionCard)` short-circuits and we avoid
        // re-rendering every card on every poll.
        setEntries((prev) => {
          if (prev.length === 0) return next;
          const prevByHandle = new Map(
            prev.map((e) => [e.subscription.unique_id, e]),
          );
          let mutated = false;
          const merged = next.map((entry) => {
            const prior = prevByHandle.get(entry.subscription.unique_id);
            if (!prior) {
              mutated = true;
              return entry;
            }
            const subSame =
              JSON.stringify(prior.subscription) === JSON.stringify(entry.subscription);
            const sumSame =
              JSON.stringify(prior.summary) === JSON.stringify(entry.summary);
            if (subSame && sumSame) {
              return prior;
            }
            mutated = true;
            return {
              subscription: subSame ? prior.subscription : entry.subscription,
              summary: sumSame ? prior.summary : entry.summary,
            };
          });
          if (!mutated && merged.length === prev.length) return prev;
          return merged;
        });
        setError(null);
      } catch (e) {
        if (cancelled) return;
        console.error(e);
        setError('Unable to load live streams right now.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchOnce();
    let interval: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (interval == null && document.visibilityState === 'visible') {
        interval = setInterval(fetchOnce, 30_000);
      }
    };
    const stop = () => {
      if (interval != null) {
        clearInterval(interval);
        interval = null;
      }
    };
    if (document.visibilityState === 'visible') start();
    const onVis = () => {
      if (document.visibilityState === 'visible') {
        fetchOnce();
        start();
      } else {
        stop();
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      cancelled = true;
      stop();
      document.removeEventListener('visibilitychange', onVis);
    };
  }, []);

  // Live hosts first, then offline; within each bucket, viewers desc.
  // Mirrors the admin page's default "live first → by live_checked_at"
  // ordering closely enough that the visual ranking is stable across
  // the two pages.
  const sorted = useMemo(() => {
    const arr = entries.slice();
    arr.sort((a, b) => {
      const aLive = isHostLive(a) ? 1 : 0;
      const bLive = isHostLive(b) ? 1 : 0;
      if (aLive !== bLive) return bLive - aLive;
      const av = a.summary.viewer_count ?? 0;
      const bv = b.summary.viewer_count ?? 0;
      return bv - av;
    });
    return arr;
  }, [entries]);

  return (
    /* Wrap the page in the public TikTok-API namespace so every
       descendant `useTikTokApi()` call (notably inside the gifter
       modal, which now spans Current + Profile tabs) hits
       `/public/tiktok/*` instead of falling back to the admin
       default — without this the modal's data fetches 401 for
       anonymous viewers. */
    <TikTokApiProvider value={publicTiktokApi as unknown as TikTokApi}>
    <PageShell className="max-w-6xl mx-auto px-4 py-6">
      <PageHeader
        title="Live Streams"
        icon={<Radio className="w-5 h-5" />}
        description="Streams being tracked right now."
      />

      {loading && entries.length === 0 && (
        <div className="rounded-lg border border-gray-200 px-4 py-8 text-center text-gray-500">
          Loading…
        </div>
      )}

      {!loading && error && entries.length === 0 && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-6 text-center text-sm text-rose-700">
          {error}
        </div>
      )}

      {!loading && !error && entries.length === 0 && (
        <div className="rounded-lg border border-gray-200 px-4 py-8 text-center text-gray-500">
          No public streams right now.
        </div>
      )}

      {sorted.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {sorted.map((entry) => (
            <SubscriptionCard
              key={entry.subscription.unique_id}
              sub={entry.subscription}
              summary={entry.summary}
              readOnly
              onSelectGifter={setSelectedGifter}
            />
          ))}
        </div>
      )}

      {/* Gifter detail modal — same drill-in UX as the admin page so
          public viewers can inspect a top-gifter's history. The modal
          only displays the same kinds of signals the scoreboard
          already surfaces (totals, recent gifts), so it's safe to
          expose. Mounted conditionally so the lazy chunk is fetched
          only when a gifter chip is actually clicked. */}
      <Suspense fallback={null}>
        {selectedGifter !== null && (
          <TikTokGifterDetailModal
            isOpen
            onClose={() => setSelectedGifter(null)}
            userId={selectedGifter.userId ?? null}
            uniqueId={selectedGifter.uniqueId ?? null}
            nickname={selectedGifter.nickname ?? null}
            diamondsTotal={selectedGifter.diamonds ?? 0}
            giftsCount={selectedGifter.gifts ?? 0}
            roomId={selectedGifter.roomId ?? null}
            currentHandle={selectedGifter.currentHandle}
            readOnly
          />
        )}
      </Suspense>
    </PageShell>
    </TikTokApiProvider>
  );
}

// ─── Payload normalization ──────────────────────────────────────────
//
// The backend ships the public payload in one of three shapes during
// the transition window between the legacy "thin PublicLive" wire
// format and the wider "full subscription + summary" format. We
// accept all three so the frontend lands independent of the backend
// rollout sequence:
//
//   A) {items: [{subscription, summary}]} — final wide shape
//   B) {subscriptions, summaries: {<handle>: ...}} — alt wide shape
//   C) {items: [PublicLive...]}             — legacy thin shape
//
// Anything we don't recognize falls back to an empty list and the
// "No public streams" placeholder. Never throw on parse — a malformed
// upstream shouldn't blank-page the public landing.

interface LegacyPublicLive {
  unique_id: string;
  nickname: string | null;
  avatar_url: string | null;
  follower_count: number | null;
  is_live: boolean | null;
  viewer_count: number | null;
  diamonds_session: number | null;
  started_at: string | null;
  hourly_buckets: number[];
}

interface WideEntry {
  subscription: TikTokSubscription;
  summary: TikTokLiveSummary;
}

function normalizePayload(payload: PublicLivesPayload): WideEntry[] {
  // Shape A — preferred wide format.
  if (payload && Array.isArray((payload as { items?: unknown }).items)) {
    const items = (payload as { items: unknown[] }).items;
    // The legacy thin shape ALSO lives under `items`, so peek at the
    // first element to disambiguate. Wide entries carry a nested
    // `subscription` object; legacy entries do not.
    const first = items[0] as Record<string, unknown> | undefined;
    if (first && typeof first === 'object' && 'subscription' in first) {
      return (items as WideEntry[]).filter((e) => !!e?.subscription);
    }
    // Shape C — legacy thin shape. Build synthetic subscription + summary.
    return (items as LegacyPublicLive[]).map(legacyToWide).filter(Boolean) as WideEntry[];
  }

  // Shape B — parallel arrays / map.
  const subs = (payload as { subscriptions?: unknown }).subscriptions;
  const summaries = (payload as { summaries?: unknown }).summaries;
  if (Array.isArray(subs)) {
    const summaryMap = (summaries && typeof summaries === 'object')
      ? (summaries as Record<string, TikTokLiveSummary>)
      : {};
    return (subs as TikTokSubscription[]).map((sub) => {
      const key = (sub.unique_id || '').toLowerCase();
      return {
        subscription: sub,
        summary: summaryMap[key] ?? summaryMap[sub.unique_id] ?? {},
      };
    });
  }

  return [];
}

/** Build a `WideEntry` from the legacy `PublicLive` row. The
 *  `SubscriptionCard` falls back gracefully when summary fields are
 *  absent — only the scoreboard cells they back will render '—' or
 *  hide entirely, and the activity strip drops the heatmap / 7-day
 *  averages. */
function legacyToWide(p: LegacyPublicLive | null | undefined): WideEntry | null {
  if (!p || !p.unique_id) return null;
  const subscription: TikTokSubscription = {
    unique_id:       p.unique_id,
    enabled:         true,
    state:           p.is_live ? 'CONNECTED' : 'DISCONNECTED',
    room_id:         null,
    is_connected:    false,
    created_at:      null,
    updated_at:      null,
    nickname:        p.nickname,
    avatar_url:      p.avatar_url,
    follower_count:  p.follower_count,
    is_live:         p.is_live,
    live_checked_at: null,
    current_room_id: null,
    is_public:       true,
  };
  const summary: TikTokLiveSummary = {
    active_room_id:    p.is_live ? 'unknown' : null,
    live_started_at:   p.started_at,
    viewer_count:      p.viewer_count,
    diamonds_session:  p.diamonds_session ?? 0,
    hourly_buckets:    p.hourly_buckets ?? [],
  };
  return { subscription, summary };
}

/** Live truth-source identical to the card's internal rule —
 *  `active_room_id` is the authoritative signal; falls back to the
 *  cached `is_live` flag only when the summary hasn't loaded yet. */
function isHostLive(e: WideEntry): boolean {
  if (e.summary?.active_room_id != null) return true;
  return !!e.subscription.is_live;
}

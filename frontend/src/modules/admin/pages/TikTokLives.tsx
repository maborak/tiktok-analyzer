import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from '@tanstack/react-router';
import { Globe, Plus, RefreshCw, RotateCcw, Search, Star, Trash2, Power, PowerOff, Send, Radio, BarChart3, Users, X } from 'lucide-react';
import toast from 'react-hot-toast';

import { useTikTokLivesSocket } from '@admin/hooks/useTikTokLivesSocket';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import {
  tiktokApi,
  isElectronClient,
  type TikTokSubscription,
  type TikTokLiveSummary,
  type TikTokLivesTotals,
} from '@admin/services/tiktok';
// Two modals account for ~hundreds of KB of bundle (echarts core +
// LineChart parses on import in the gifter modal). Both stay closed
// 99% of the time on the lives list — defer their bundle until the
// user actually opens one. The Suspense boundary below renders
// nothing while the chunk loads, which is fine since neither modal
// is on the first-paint critical path.
const TikTokAddLiveModal = lazy(() =>
  import('@admin/components/TikTokAddLiveModal').then((m) => ({ default: m.TikTokAddLiveModal })),
);
const TikTokGifterDetailModal = lazy(() =>
  import('@admin/components/TikTokGifterDetailModal').then((m) => ({ default: m.TikTokGifterDetailModal })),
);
import { TikTokCommonGiftersTable } from '@admin/components/TikTokCommonGiftersTable';
import { TikTokFavoriteGiftersTable } from '@admin/components/TikTokFavoriteGiftersTable';
import { TikTokRealtimeIndicator } from '@admin/components/TikTokRealtimeIndicator';
import { TikTokTimezonePill } from '@admin/components/TikTokTimezonePill';
import {
  TikTokTimezoneProvider,
  useTikTokTimezone,
  partsInZone,
} from '@admin/contexts/TikTokTimezoneContext';
import {
  TikTokRuntimeConfigProvider,
  useTikTokRuntimeConfig,
} from '@admin/contexts/TikTokRuntimeConfigContext';

const STATE_TONE: Record<string, string> = {
  CONNECTED: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  CONNECTING: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  LIVE_ENDED: 'bg-gray-100 text-gray-700 dark:bg-white/10 dark:text-gray-300',
  DISCONNECTED: 'bg-gray-100 text-gray-700 dark:bg-white/10 dark:text-gray-300',
  DISABLED: 'bg-gray-100 text-gray-500 dark:bg-white/10',
  ERROR: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
};

export function TikTokLives() {
  // `audience="admin"` → hits `/admin/tiktok/runtime-config` so this
  // page reads the full typed-config set (poll cadence + admin
  // realtime mode + public realtime mode). The public mirror only
  // returns the trimmed slice; the admin endpoint is the truth.
  return (
    <TikTokTimezoneProvider>
      <TikTokRuntimeConfigProvider audience="admin">
        <TikTokLivesBody />
      </TikTokRuntimeConfigProvider>
    </TikTokTimezoneProvider>
  );
}

function TikTokLivesBody() {
  // Runtime config — poll cadence applied to the lives summary +
  // totals interval below; admin-realtime mode would gate WS opens
  // here too if this page held any (it doesn't; the WS lives in
  // TikTokLiveDetail). `pollIntervalMs` is the operator-configured
  // value from typed config (default 30000), clamped server-side
  // to [1000, 600000] so a misconfig can't DDOS our own backend.
  const { pollIntervalMs } = useTikTokRuntimeConfig();
  // Active operator timezone — threaded into livesBundle so the
  // per-host `week_calendar` strip buckets by calendar day in this
  // zone (e.g. Lima) instead of rolling-24h-UTC.
  const { tz } = useTikTokTimezone();
  const [subs, setSubs] = useState<TikTokSubscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [newHandle, setNewHandle] = useState('');
  // Two-step add: typing the handle stages a candidate; clicking Add pops a
  // confirmation modal that previews the user's TikTok profile + live state.
  const [pendingHandle, setPendingHandle] = useState<string | null>(null);
  // URL-driven tab state. The tab key is in `?tab=…` so deep-linking
  // and browser back/forward both work. We use plain history APIs
  // here (no TanStack search-schema dance) so this stays a one-file
  // change. `replaceState` on tab change avoids polluting history
  // with each click; popstate keeps state in sync if the user
  // back-buttons.
  //
  // NOTE: `settings` and `worker` are NOT tabs here — both live
  // inside the consolidated Settings page at /admin/tiktok/settings
  // (Worker is a sub-tab; Sign Engine is another). Keeping them out
  // of TabKey forbids any code path from accidentally re-introducing
  // them as tabs.
  type TabKey = 'lives' | 'common' | 'global' | 'favorites';
  const ALLOWED_TABS: ReadonlySet<TabKey> = new Set([
    'lives', 'common', 'global', 'favorites',
  ]);
  const readTabFromUrl = (): TabKey => {
    if (typeof window === 'undefined') return 'lives';
    const v = new URL(window.location.href).searchParams.get('tab') as TabKey | null;
    return v && ALLOWED_TABS.has(v) ? v : 'lives';
  };
  const [tab, setTabState] = useState<TabKey>(readTabFromUrl);
  const setTab = (next: TabKey) => {
    setTabState(next);
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    // `lives` is the default — keep the URL clean by omitting it.
    if (next === 'lives') url.searchParams.delete('tab');
    else url.searchParams.set('tab', next);
    window.history.replaceState({}, '', url);
  };
  // Sync state on browser back/forward.
  useEffect(() => {
    const onPop = () => setTabState(readTabFromUrl());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Per-tab refresh keys — page-header Refresh forwards into the
  // currently-active tab's component so its data refetches without
  // remounting (preserves search input + pagination).
  const [commonRefreshKey, setCommonRefreshKey] = useState(0);
  const [globalRefreshKey, setGlobalRefreshKey] = useState(0);
  const [favoritesRefreshKey, setFavoritesRefreshKey] = useState(0);
  // Gifter detail modal — opened from the "👑 Top:" chips on each
  // live card. Scope is the host's current room (so the modal sums
  // gifts this gifter has sent *during this session*). Same UX shape
  // as the live-detail page's gifter modal.
  const [selectedGifter, setSelectedGifter] = useState<{
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
    diamonds: number;
    gifts: number;
    roomId: string | null;
    currentHandle: string;
  } | null>(null);
  // Live filter for the Lives table / mobile cards. Substring match
  // against nickname OR @unique_id; case-insensitive.
  const [livesQuery, setLivesQuery] = useState('');
  // Status filter pill — narrow the list to ONLINE-only / OFFLINE-only.
  // Live-truth derivation mirrors the per-card `isLive` rule:
  // `summary.active_room_id` is authoritative when a summary slice
  // exists, otherwise fall back to the cached `sub.is_live` flag.
  const [statusFilter, setStatusFilter] = useState<'all' | 'online' | 'offline'>('all');
  // Sort key for the table — purely client-side over the loaded list.
  type SortKey =
    | 'live'
    | 'followers'
    | 'last_seen'
    | 'last_diamonds'
    | 'last_duration'
    | 'session_diamonds';
  const [sortKey, setSortKey] = useState<SortKey>('live');
  // Server-enriched per-host data (sparkline, viewers, top gifter,
  // active match, last broadcasts, momentum). Refreshed on focus +
  // every 30s while focused. Keyed by lowercased handle.
  const [summary, setSummary] = useState<Record<string, TikTokLiveSummary>>({});
  const [totals, setTotals] = useState<TikTokLivesTotals | null>(null);
  const filteredSubs = useMemo(() => {
    const q = livesQuery.trim().toLowerCase();
    let arr = subs;
    if (q) {
      arr = arr.filter(
        (s) =>
          (s.unique_id || '').toLowerCase().includes(q) ||
          (s.nickname || '').toLowerCase().includes(q),
      );
    }
    // Status pill filter — derive `isLive` from the summary slice
    // when present (authoritative), else fall back to the cached
    // `sub.is_live` flag. Mirrors the per-card rule so the pill
    // and the card accent agree.
    if (statusFilter !== 'all') {
      arr = arr.filter((s) => {
        const slice = s.unique_id ? summary[s.unique_id.toLowerCase()] : undefined;
        const isLive = slice?.active_room_id != null
          || (slice == null && !!s.is_live);
        return statusFilter === 'online' ? isLive : !isLive;
      });
    }
    const tsKey = (s?: string | null) =>
      s ? new Date(s).getTime() : 0;
    const sumOf = (h?: string | null) =>
      (h ? summary[h.toLowerCase()] : null) || ({} as TikTokLiveSummary);
    const sorted = arr.slice().sort((a, b) => {
      switch (sortKey) {
        case 'followers':
          return (b.follower_count ?? 0) - (a.follower_count ?? 0);
        case 'last_seen':
          return tsKey(b.live_checked_at) - tsKey(a.live_checked_at);
        case 'last_diamonds': {
          const ad = sumOf(a.unique_id).last_broadcasts?.[0]?.diamonds ?? 0;
          const bd = sumOf(b.unique_id).last_broadcasts?.[0]?.diamonds ?? 0;
          return bd - ad;
        }
        case 'last_duration': {
          const ad = sumOf(a.unique_id).last_broadcasts?.[0]?.duration_min ?? 0;
          const bd = sumOf(b.unique_id).last_broadcasts?.[0]?.duration_min ?? 0;
          return bd - ad;
        }
        case 'session_diamonds':
          return (sumOf(b.unique_id).diamonds_session ?? 0)
               - (sumOf(a.unique_id).diamonds_session ?? 0);
        case 'live':
        default: {
          // live first, then by recent live_checked_at
          const al = a.is_live ? 1 : 0;
          const bl = b.is_live ? 1 : 0;
          if (al !== bl) return bl - al;
          return tsKey(b.live_checked_at) - tsKey(a.live_checked_at);
        }
      }
    });
    return sorted;
  }, [subs, livesQuery, statusFilter, sortKey, summary]);
  const electron = isElectronClient();

  // ── data ──────────────────────────────────────────────────────────

  // Quick subs-only refresh — used after CRUD operations (add,
  // delete, toggle, reconnect, public-flip) where we only need to
  // re-fetch the subscription list to surface the change. The next
  // `/lives/bundle` poll cycle picks up summary changes naturally.
  // Cheaper than calling bundle, since summary + totals are heavy.
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await tiktokApi.listLives();
      setSubs(data);
    } catch (e) {
      console.error(e);
      toast.error('Failed to load subscriptions');
    } finally {
      setLoading(false);
    }
  }, []);

  // Phase 9.E — WS-pushed per-host state. The hook subscribes to the
  // `tiktok:lives:delta:admin` channel via the existing
  // `/admin/tiktok/ws` endpoint. Every state-cache mutation on the
  // server publishes a `summary-delta` frame; the hook applies it
  // here via `onSocketUpdate`. Status drives the reconciliation
  // cadence below: WS-live → 5-min safety-net fetch; WS-degraded →
  // fall back to 30-s polling so the UI doesn't go stale.
  const onSocketUpdate = useCallback(
    (host: string, slice: TikTokLiveSummary, version: number) => {
      setSummary((prev) => {
        const existing = prev[host];
        // Same structural-share rule as the bundle merge — preserve
        // per-host reference identity when the merged value is byte-
        // equivalent so `React.memo(SubscriptionCard)` short-circuits.
        const merged: TikTokLiveSummary = {
          ...(existing ?? {}),
          ...slice,
          version,
        };
        if (
          existing &&
          JSON.stringify(existing) === JSON.stringify(merged)
        ) {
          return prev;
        }
        return { ...prev, [host]: merged };
      });
    },
    [],
  );

  const wsStatus = useTikTokLivesSocket({
    audience: 'admin',
    onUpdate: onSocketUpdate,
  });

  // Seed the WS hook's per-host version cursor whenever the bundle
  // brings fresh data in. Without this, a WS reconnect before the
  // first delta arrives finds an empty version map and skips the
  // on-reconnect snapshot step, leaving cards stale until the next
  // 5-minute reconcile poll. See `useTikTokLivesSocket.ts:seedVersions`.
  //
  // Dep is `wsStatus.seedVersions` (stable useCallback ref), NOT
  // `wsStatus` itself — the hook returns a fresh object each render
  // and depending on the whole would re-fire this effect on every
  // re-render of the page.
  const seedVersions = wsStatus.seedVersions;
  useEffect(() => {
    const versions: Record<string, number> = {};
    for (const [host, slice] of Object.entries(summary)) {
      const v = (slice as { version?: number }).version;
      if (typeof v === 'number' && v > 0) versions[host] = v;
    }
    if (Object.keys(versions).length > 0) {
      seedVersions(versions);
    }
  }, [summary, seedVersions]);

  // Single bundled fetch — provides initial subs + summary + totals.
  // After Phase 9.E this also acts as the periodic safety-net
  // reconciliation: when the WS is live (driving deltas) we re-fetch
  // every 5 min just to catch any drift; when the WS is degraded we
  // fall back to the old 30-s cadence so the UI doesn't go stale.
  const reconcileIntervalMs =
    wsStatus.status === 'live' ? 5 * 60 * 1000 : pollIntervalMs;

  useEffect(() => {
    if (tab !== 'lives') return;
    let cancelled = false;
    const fetchOnce = () => {
      tiktokApi
        .livesBundle({ tz })
        .then(({ subs: nextSubs, summary: nextSummary, totals: nextTotals }) => {
          if (cancelled) return;
          setSubs(nextSubs);
          setSummary((prev) => {
            const next: Record<string, TikTokLiveSummary> = {};
            let changed = false;
            for (const [k, v] of Object.entries(nextSummary)) {
              const prevEntry = prev[k];
              if (prevEntry && JSON.stringify(prevEntry) === JSON.stringify(v)) {
                next[k] = prevEntry;
              } else {
                next[k] = v;
                changed = true;
              }
            }
            for (const k of Object.keys(prev)) {
              if (!(k in next)) {
                changed = true;
              }
            }
            return changed ? next : prev;
          });
          setTotals(nextTotals);
          setLoading(false);
        })
        .catch(() => {
          /* silent — next tick will retry */
          setLoading(false);
        });
    };
    setLoading(true);
    fetchOnce();
    let interval: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (interval == null && document.visibilityState === 'visible') {
        interval = setInterval(fetchOnce, reconcileIntervalMs);
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
  }, [tab, reconcileIntervalMs, tz]);

  // ── actions ───────────────────────────────────────────────────────

  // Stage Add: open the preview modal with the typed handle.
  const onAdd = () => {
    const handle = newHandle.replace(/^@/, '').trim();
    if (!handle) return;
    setPendingHandle(handle);
  };

  // Confirm from the modal: actually create the subscription.
  const onConfirmAdd = async () => {
    const handle = pendingHandle;
    if (!handle) return;
    setAdding(true);
    try {
      await tiktokApi.createLive(handle);
      toast.success(`Subscribed to @${handle}`);
      setNewHandle('');
      setPendingHandle(null);
      refresh();
    } catch (e) {
      console.error(e);
      toast.error(`Failed to subscribe @${handle}`);
    } finally {
      setAdding(false);
    }
  };

  const onCancelAdd = () => {
    setPendingHandle(null);
  };

  // All row handlers are wrapped in `useCallback` and accept the row
  // directly so the parent never has to spawn a per-card inline arrow.
  // Combined with `React.memo` on `SubscriptionCard` this is what
  // stops every 30s poll tick from re-rendering the entire 79-card
  // grid — only hosts whose summary slice actually changed re-render.
  const onToggle = useCallback(async (s: TikTokSubscription) => {
    try {
      await tiktokApi.setEnabled(s.unique_id, !s.enabled);
      toast.success(`@${s.unique_id} ${s.enabled ? 'paused' : 'enabled'}`);
      refresh();
    } catch (e) {
      console.error(e);
      toast.error('Failed to update');
    }
  }, [refresh]);

  const onDelete = useCallback(async (s: TikTokSubscription) => {
    if (!confirm(`Remove subscription for @${s.unique_id}? Historical data is kept.`)) return;
    try {
      await tiktokApi.deleteLive(s.unique_id);
      toast.success(`Removed @${s.unique_id}`);
      refresh();
    } catch (e) {
      console.error(e);
      toast.error('Failed to remove');
    }
  }, [refresh]);

  const onReconnect = useCallback(async (s: TikTokSubscription) => {
    try {
      await tiktokApi.reconnectLive(s.unique_id);
      toast.success(`Reconnect requested for @${s.unique_id}`);
      // Refresh after a short delay so the worker has a tick to act
      // (reconcile cadence is ~10s; first poll at 5s is usually enough
      // to see the cleared is_live cache and the new state).
      setTimeout(refresh, 5_000);
    } catch (e) {
      console.error(e);
      toast.error('Failed to request reconnect');
    }
  }, [refresh]);

  // Optimistic local flip so the button visual snaps immediately —
  // revert + toast on failure. We don't `refresh()` on success to
  // avoid flicker; the persisted value will surface on the next poll.
  const onSetPublic = useCallback(async (s: TikTokSubscription) => {
    const next = !s.is_public;
    setSubs((prev) =>
      prev.map((row) =>
        row.unique_id === s.unique_id ? { ...row, is_public: next } : row,
      ),
    );
    try {
      await tiktokApi.setLivePublic(s.unique_id, next);
      toast.success(
        next ? `@${s.unique_id} is now public` : `@${s.unique_id} hidden from public`,
      );
    } catch (e) {
      console.error(e);
      toast.error('Failed to update visibility');
      // Revert the optimistic flip.
      setSubs((prev) =>
        prev.map((row) =>
          row.unique_id === s.unique_id ? { ...row, is_public: !next } : row,
        ),
      );
    }
  }, []);

  const onElectronLogin = async () => {
    if (!window.api?.login) return;
    try {
      const r = (await window.api.login()) as { logged_in?: boolean; error?: string };
      if (r.logged_in) toast.success('Logged in to TikTok');
      else toast.error(r.error || 'Login did not complete');
    } catch (e) {
      console.error(e);
      toast.error('Login failed');
    }
  };

  const onElectronSend = useCallback(async (handle: string, text: string) => {
    if (!window.api?.navigateToLive || !window.api?.sendComment) return;
    try {
      await window.api.navigateToLive(handle);
      const r = (await window.api.sendComment(text)) as { ok?: boolean; detail?: string };
      if (r.ok) toast.success('Sent');
      else toast.error(r.detail || 'Send failed');
    } catch (e) {
      console.error(e);
      toast.error('Send failed');
    }
  }, []);

  // ── render ────────────────────────────────────────────────────────

  return (
    <PageShell>
      <PageHeader
        title="TikTok Lives"
        icon={<Radio className="w-5 h-5" />}
        description={
          electron
            ? 'Subscribe to TikTok creators and gather their live events. Posting is enabled (Electron client detected).'
            : 'Subscribe to TikTok creators and gather their live events. Posting is read-only here — open in the desktop client to send chat.'
        }
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <TikTokTimezonePill compact />
            <TikTokRealtimeIndicator audience="admin" />
            <Button
              variant="ghost"
              onClick={() => {
                if (tab === 'common') setCommonRefreshKey((k) => k + 1);
                else if (tab === 'global') setGlobalRefreshKey((k) => k + 1);
                else if (tab === 'favorites') setFavoritesRefreshKey((k) => k + 1);
                else refresh();
              }}
              disabled={tab === 'lives' && loading}
              title={
                tab === 'common'
                  ? 'Refresh common gifters'
                  : tab === 'global'
                    ? 'Refresh global gifters'
                    : tab === 'favorites'
                      ? 'Refresh favourites'
                      : 'Refresh subscriptions'
              }
            >
              <RefreshCw className={loading && tab === 'lives' ? 'animate-spin w-4 h-4' : 'w-4 h-4'} />
            </Button>
          </div>
        }
      />

      {/* Add new subscription — page-level control, sits ABOVE the tab
          bar so it's visible on every tab. Useful even when the admin
          is on Common Gifters / Worker / etc. (Settings is a separate
          sidebar page — not a tab here.) */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="@username — add a new TikTok creator"
          value={newHandle}
          onChange={(e) => setNewHandle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onAdd();
          }}
          className="w-full sm:max-w-sm"
        />
        <Button onClick={onAdd} disabled={adding || !newHandle.trim()}>
          <Plus className="w-4 h-4 mr-1" />
          Add
        </Button>
        {electron && (
          <Button variant="secondary" onClick={onElectronLogin}>
            Login to TikTok
          </Button>
        )}
      </div>

      {/* Tab strip. Settings is intentionally absent — it has its own
          sidebar entry + route at /admin/tiktok/settings. */}
      <div className="flex items-center gap-1 border-b border-gray-200 -mb-px overflow-x-auto">
        <PageTabButton active={tab === 'lives'} onClick={() => setTab('lives')}>
          <Radio className="w-3.5 h-3.5" />
          Lives
        </PageTabButton>
        <PageTabButton active={tab === 'common'} onClick={() => setTab('common')}>
          <Users className="w-3.5 h-3.5" />
          Common Gifters
        </PageTabButton>
        <PageTabButton active={tab === 'global'} onClick={() => setTab('global')}>
          <Globe className="w-3.5 h-3.5" />
          Global Gifters
        </PageTabButton>
        <PageTabButton active={tab === 'favorites'} onClick={() => setTab('favorites')}>
          <Star className="w-3.5 h-3.5" />
          Favourites
        </PageTabButton>
      </div>

      {/* Non-lives tab bodies. `pt-4` gives the first row breathing
          room from the tab underline above. */}
      <div className="pt-4">
        {tab === 'common' && <TikTokCommonGiftersTable refreshKey={commonRefreshKey} />}
        {tab === 'global' && (
          <TikTokCommonGiftersTable refreshKey={globalRefreshKey} mode="global" />
        )}
        {tab === 'favorites' && (
          <TikTokFavoriteGiftersTable refreshKey={favoritesRefreshKey} />
        )}
      </div>

      {tab === 'lives' && (
        <div className="pt-4 flex flex-col gap-3">
      {/* Page-level totals strip — N live, total subs, diamonds 24h,
          events/min across all hosts. Refreshed by the same poll
          loop that drives the per-row summary. */}
      {totals && (
        <LivesTotalsStrip totals={totals} />
      )}
      {/* Lives search + status filter — same row on md+, stacked on
          mobile. The Add subscription field lives OUTSIDE the tabs
          (page-level), so this row is search + filter only. */}
      <div className="flex flex-col md:flex-row md:items-center gap-2">
        <div className="relative flex-1 focus-within:ring-2 focus-within:ring-primary-500/30 focus-within:border-primary-500 rounded-md border-2 border-gray-200 bg-white dark:bg-gray-100/5 transition-colors">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none" />
          <input
            type="search"
            value={livesQuery}
            onChange={(e) => setLivesQuery(e.target.value)}
            placeholder={
              subs.length > 0
                ? `Search ${subs.length} subscriptions by nickname or @handle…`
                : 'Search subscriptions…'
            }
            disabled={subs.length === 0}
            className="w-full pl-8 pr-8 py-2 rounded-md bg-transparent text-sm font-mono placeholder:text-gray-500 focus:outline-none disabled:opacity-50"
          />
          {livesQuery && (
            <button
              type="button"
              onClick={() => setLivesQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
              aria-label="Clear filter"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        {/* Status pills — ALL / ONLINE / OFFLINE. Active = primary
            tone; inactive = neutral so the highlighted pill draws
            the eye. Pill (rounded-full) not button — matches the
            sort selector visual language below. */}
        <div className="flex items-center gap-1.5 shrink-0">
          {([
            { id: 'all',     label: 'ALL' },
            { id: 'online',  label: 'ONLINE' },
            { id: 'offline', label: 'OFFLINE' },
          ] as { id: typeof statusFilter; label: string }[]).map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => setStatusFilter(opt.id)}
              className={`px-3 py-1.5 text-xs font-mono rounded-full transition-colors ${
                statusFilter === opt.id
                  ? 'bg-primary-100 text-primary-700 dark:bg-primary-500/20 dark:text-primary-300'
                  : 'bg-white text-gray-600 border border-gray-200 hover:border-gray-300 dark:bg-gray-100/5'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Empty state (shared across both layouts). */}
      {subs.length === 0 && (
        <div className="rounded-lg border border-gray-200 px-4 py-8 text-center text-gray-500">
          {loading ? 'Loading…' : 'No subscriptions yet. Add one above.'}
        </div>
      )}

      {/* Mobile: stacked cards. Desktop: table. The table layout has 5
          columns and even with `min-w-[640px]` + horizontal scroll it
          felt cramped on phones — cards present the same data in a
          natural one-per-creator block. */}
      {subs.length > 0 && filteredSubs.length === 0 && (
        <div className="rounded-lg border border-gray-200 px-4 py-8 text-center text-sm text-gray-500">
          {livesQuery ? (
            <>No subscriptions match <span className="font-mono">"{livesQuery}"</span>{statusFilter !== 'all' ? <> in <span className="font-mono uppercase">{statusFilter}</span></> : null}.</>
          ) : (
            <>No <span className="font-mono uppercase">{statusFilter}</span> subscriptions.</>
          )}
        </div>
      )}
      {filteredSubs.length > 0 && (
        <>
          {/* Sort selector — purely client-side over the loaded list. */}
          <div className="flex items-center gap-2 text-[11px] font-mono text-gray-500 flex-wrap">
            <span className="hidden sm:inline">Sort:</span>
            {([
              { id: 'live',             label: 'Live first' },
              { id: 'session_diamonds', label: 'Live diamonds' },
              { id: 'followers',        label: 'Followers' },
              { id: 'last_diamonds',    label: 'Last live 💎' },
              { id: 'last_duration',    label: 'Last live duration' },
              { id: 'last_seen',        label: 'Last seen' },
            ] as { id: typeof sortKey; label: string }[]).map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setSortKey(opt.id)}
                className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full border transition-colors ${
                  sortKey === opt.id
                    ? 'bg-primary-100 dark:bg-primary-500/20 border-primary-300 text-primary-700 dark:text-primary-300'
                    : 'bg-white dark:bg-white/5 border-gray-200 hover:border-gray-300'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* 2-column card grid only at xl+ (≥1280px). Below that,
              the cards have a lot of inline content and side-by-side
              forces wrap-heavy layouts that look like soup. Wider
              gap-4 vs gap-3 so the live-card rose accent doesn't
              touch its neighbour. */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {filteredSubs.map((s) => (
              <SubscriptionCard
                key={s.unique_id}
                sub={s}
                electron={electron}
                summary={s.unique_id ? summary[s.unique_id.toLowerCase()] : undefined}
                onToggle={onToggle}
                onDelete={onDelete}
                onReconnect={onReconnect}
                onSetPublic={onSetPublic}
                onSend={onElectronSend}
                onSelectGifter={setSelectedGifter}
              />
            ))}
          </div>
        </>
      )}

        </div>
      )}

      {/* Page-level modals — code-split via React.lazy. Each modal is
          mounted only when its trigger flips truthy, which means the
          bundle for the echarts-heavy gifter modal is never fetched
          on a session that doesn't open one. Suspense fallback is
          null because both are interactive overlays — there's no
          point flashing a spinner; the chunk arrives faster than the
          user can perceive the trigger click. */}
      <Suspense fallback={null}>
        {pendingHandle !== null && (
          <TikTokAddLiveModal
            isOpen
            handle={pendingHandle}
            onCancel={onCancelAdd}
            onConfirm={onConfirmAdd}
          />
        )}
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
            defaultTab="current"
          />
        )}
      </Suspense>
    </PageShell>
  );
}

interface PageTabButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function PageTabButton({ active, onClick, children }: PageTabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors ' +
        (active
          ? 'border-primary-500 text-primary-700 dark:text-primary-300'
          : 'border-transparent text-gray-600 hover:text-gray-900')
      }
    >
      {children}
    </button>
  );
}

// ── helpers ────────────────────────────────────────────────────────

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}

interface SelectedGifter {
  userId: string | null;
  uniqueId: string | null;
  nickname: string | null;
  diamonds: number;
  gifts: number;
  roomId: string | null;
  currentHandle: string;
}

interface RowProps {
  sub: TikTokSubscription;
  electron?: boolean;
  /** Server-enriched data for this host. May be empty / undefined
   *  while the first poll is in flight. */
  summary?: TikTokLiveSummary;
  /** Read-only mode — hides every admin-side action (composer,
   *  reconnect / pause / delete, the Stats link, the Public toggle)
   *  and any operator-only signal (listener health dot, "checked Xm
   *  ago" / "N reconnects/h" line). The card's avatar, identity,
   *  scoreboard, sparkline, heatmap, top-gifter chips, and in-match
   *  pill stay identical so a viewer on `/` gets parity with
   *  `/admin/tiktok`. The top-gifter chip still calls
   *  `onSelectGifter` when provided — the gifter modal sums public
   *  signals only and is fine to expose. */
  readOnly?: boolean;
  /** Action handlers take the row's subscription / handle directly so
   *  the parent can pass stable function refs (no per-card inline
   *  arrows). Without this, every parent render would synthesize five
   *  fresh closures per card, defeating `React.memo`. */
  onToggle?: (s: TikTokSubscription) => void;
  onDelete?: (s: TikTokSubscription) => void;
  onReconnect?: (s: TikTokSubscription) => void;
  /** Flips the subscription's `is_public` flag — controls whether this
   *  host's sanitized scoreboard shows up on the unauthenticated home
   *  page. Optimistic update happens at the page level. */
  onSetPublic?: (s: TikTokSubscription) => void;
  onSend?: (handle: string, text: string) => void;
  /** Lifts a click on a top-gifter chip up to the page-level modal
   *  state. Optional so the card stays usable in contexts where no
   *  modal host is available. */
  onSelectGifter?: (g: SelectedGifter) => void;
}

/** Universal card — replaces both the desktop table row AND the
 *  mobile stacked card. Renders 2-up on lg+ via the parent grid;
 *  collapses to 1-per-row at smaller widths. The card is dense
 *  enough that the desktop user gets table-equivalent info density
 *  while gaining real estate for the activity strip, sparkline,
 *  recent broadcasts, and identity context.
 *
 *  Exported so the unauthenticated public page (`/`) can render the
 *  identical visual with `readOnly` — same scoreboard, same
 *  sparkline / heatmap / chips, just no admin-side actions. */
function SubscriptionCardImpl({ sub, electron, summary, readOnly, onToggle, onDelete, onReconnect, onSetPublic, onSend, onSelectGifter }: RowProps) {
  const [composer, setComposer] = useState('');
  const [sending, setSending] = useState(false);
  const display = sub.nickname || sub.unique_id;
  // Same live-truth rule as `ActivityStrip` — see the comment there.
  // The cached `sub.is_live` lingers stale after streams end; the
  // freshly-computed `summary.active_room_id` is the authoritative
  // signal. Without this, the rose border accent sticks on every
  // card whose `is_live` flag hasn't been re-scraped yet.
  const isLive = summary?.active_room_id != null
    || (summary == null && !!sub.is_live);
  const cardAccent =
    sub.state === 'ERROR'
      ? 'border-l-4 border-l-rose-400'
      : isLive
        ? 'border-l-4 border-l-emerald-500'
        : 'border-l-4 border-l-gray-300 dark:border-l-gray-100/10';

  return (
    <div
      className={`rounded-lg border border-gray-200 ${cardAccent} bg-white dark:bg-white/5 p-3 flex flex-col gap-3 transition-shadow hover:shadow-sm`}
    >
      {/* Top row: avatar + identity + state pill.
          In readOnly (public) mode, the click target drills into the
          unauthenticated detail page `/lives/$handle` — same React
          tree as `/admin/tiktok/$handle` rendered with the public API
          namespace + every admin-write affordance hidden. The previous
          behaviour was an external link to tiktok.com itself, but the
          user expects the click to OPEN the deep-dive view we serve. */}
      <div className="flex items-start gap-3">
        {readOnly ? (
          <Link
            to="/lives/$handle"
            params={{ handle: sub.unique_id }}
            title={`Open @${sub.unique_id}'s live page`}
            className="flex items-start gap-3 flex-1 min-w-0 group"
          >
            <div className="relative shrink-0">
              {sub.avatar_url ? (
                <img
                  src={sub.avatar_url}
                  alt=""
                  className="w-14 h-14 rounded-full object-cover ring-2 ring-gray-100 dark:ring-white/10 group-hover:ring-primary-200 transition-shadow"
                  referrerPolicy="no-referrer"
                  loading="lazy"
                />
              ) : (
                <div className="w-14 h-14 rounded-full bg-gray-100 text-gray-400 flex items-center justify-center text-lg font-bold">
                  {(sub.unique_id[0] || '?').toUpperCase()}
                </div>
              )}
              {isLive && (
                <span
                  className="absolute -bottom-1 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 rounded-full bg-emerald-600 text-white text-[9px] font-bold tracking-wider px-1.5 py-0.5 ring-2 ring-white dark:ring-gray-900 shadow-sm"
                  aria-label="Live now"
                  title="Live now"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                  LIVE
                </span>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-bold text-gray-900 group-hover:text-primary-700 truncate flex items-center gap-1.5">
                {display}
                {sub.verified && (
                  <span title="Verified" className="text-primary-600 text-sm shrink-0">✓</span>
                )}
                {isLive && summary?.active_match && (() => {
                  const am = summary.active_match!;
                  const opps = am.opponents ?? [];
                  const others = opps.filter(
                    (o) => o.unique_id && o.unique_id !== sub.unique_id
                  );
                  const primary = others[0] ?? null;
                  const extraCount = Math.max(0, others.length - 1);
                  const extraTitle = extraCount > 0
                    ? `Other rivals: ${others.slice(1).map((o) => '@' + o.unique_id).join(', ')}`
                    : '';
                  return (
                    <span className="shrink-0 inline-flex items-center gap-1">
                      <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-purple-100 dark:bg-purple-500/15 text-purple-700 dark:text-purple-300 text-[9px] font-mono font-bold uppercase tracking-wider"
                        title="Host is in a PK battle right now"
                      >
                        ⚔ In match
                      </span>
                      {primary?.unique_id && (
                        <span
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-purple-50 dark:bg-purple-500/10 text-purple-700 dark:text-purple-300 text-[10px] font-mono"
                          title={extraTitle || `Rival: @${primary.unique_id}`}
                        >
                          vs @{primary.unique_id}
                          {extraCount > 0 && (
                            <span className="opacity-70 tabular-nums">+{extraCount}</span>
                          )}
                        </span>
                      )}
                    </span>
                  );
                })()}
              </div>
              <div
                className="text-xs font-mono text-gray-500 truncate"
                title={
                  sub.follower_count != null
                    ? `${sub.follower_count.toLocaleString()} followers${sub.room_id ? ` · Room ${sub.room_id}` : ''}`
                    : undefined
                }
              >
                @{sub.unique_id}
              </div>
            </div>
          </Link>
        ) : (
        <Link
          to="/admin/tiktok/$handle"
          params={{ handle: sub.unique_id }}
          className="flex items-start gap-3 flex-1 min-w-0 group"
        >
          <div className="relative shrink-0">
            {sub.avatar_url ? (
              <img
                src={sub.avatar_url}
                alt=""
                className="w-14 h-14 rounded-full object-cover ring-2 ring-gray-100 dark:ring-white/10 group-hover:ring-primary-200 transition-shadow"
                referrerPolicy="no-referrer"
                loading="lazy"
              />
            ) : (
              <div className="w-14 h-14 rounded-full bg-gray-100 text-gray-400 flex items-center justify-center text-lg font-bold">
                {(sub.unique_id[0] || '?').toUpperCase()}
              </div>
            )}
            {isLive && (
              <span
                className="absolute -bottom-1 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 rounded-full bg-emerald-600 text-white text-[9px] font-bold tracking-wider px-1.5 py-0.5 ring-2 ring-white dark:ring-gray-900 shadow-sm"
                aria-label="Live now"
                title="Live now"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                LIVE
              </span>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-bold text-gray-900 group-hover:text-primary-700 truncate flex items-center gap-1.5">
              {display}
              {sub.verified && (
                <span title="Verified" className="text-primary-600 text-sm shrink-0">✓</span>
              )}
              {/* `IN MATCH` chip + primary rival pill — surfaces an
                  active PK battle at-a-glance on the lives index.
                  Multi-rival battles collapse the extras into a
                  "+N" suffix on the rival pill (operator can hover
                  for the full list). Backed by `summary.active_match`
                  populated by `get_lives_summary` only while the
                  match is fresh (last_seen_at within 2 min, no
                  ended_at). */}
              {isLive && summary?.active_match && (() => {
                const am = summary.active_match!;
                const opps = am.opponents ?? [];
                const others = opps.filter(
                  (o) => o.unique_id && o.unique_id !== sub.unique_id
                );
                const primary = others[0] ?? null;
                const extraCount = Math.max(0, others.length - 1);
                const extraTitle = extraCount > 0
                  ? `Other rivals: ${others.slice(1).map((o) => '@' + o.unique_id).join(', ')}`
                  : '';
                return (
                  <span className="shrink-0 inline-flex items-center gap-1">
                    <span
                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-purple-100 dark:bg-purple-500/15 text-purple-700 dark:text-purple-300 text-[9px] font-mono font-bold uppercase tracking-wider"
                      title="Host is in a PK battle right now"
                    >
                      ⚔ In match
                    </span>
                    {primary?.unique_id && (
                      <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-purple-50 dark:bg-purple-500/10 text-purple-700 dark:text-purple-300 text-[10px] font-mono"
                        title={extraTitle || `Rival: @${primary.unique_id}`}
                      >
                        vs @{primary.unique_id}
                        {extraCount > 0 && (
                          <span className="opacity-70 tabular-nums">+{extraCount}</span>
                        )}
                      </span>
                    )}
                  </span>
                );
              })()}
            </div>
            <div
              className="text-xs font-mono text-gray-500 truncate"
              title={
                sub.follower_count != null
                  ? `${sub.follower_count.toLocaleString()} followers${sub.room_id ? ` · Room ${sub.room_id}` : ''}`
                  : sub.room_id
                    ? `Room ${sub.room_id}`
                    : undefined
              }
            >
              @{sub.unique_id}
            </div>
          </div>
        </Link>
        )}
        {/* Listener health dot replaces the verbose state pill.
            Operator-only signal — hidden in read-only mode. */}
        {!readOnly && <HealthDot sub={sub} summary={summary} />}
      </div>

      {/* Activity strip — sparkline, live stats, PK chip, top gifter,
          24h activity rhythm, recent broadcasts, 30d averages. Falls
          back gracefully if the summary hasn't loaded yet. */}
      <ActivityStrip sub={sub} summary={summary} readOnly={readOnly} onSelectGifter={onSelectGifter} />

      {/* Actions row — Stats link on the left, electron composer
          fills the rest, icon buttons grouped on the right so they
          stay together when the row wraps. All hit-targets ≥ 44px
          via the wrapper sizes for touch (audit fix).
          Entire row suppressed in read-only mode. */}
      {!readOnly && (
      <div className="flex flex-wrap items-center gap-2 border-t border-gray-200 dark:border-white/10 pt-2">
        <Link
          to="/admin/tiktok/$handle"
          params={{ handle: sub.unique_id }}
          className="inline-flex items-center gap-1 px-2 py-2 text-xs text-gray-500 hover:text-primary-600"
          aria-label="Open stats"
        >
          <BarChart3 className="w-4 h-4" />
          <span>Stats</span>
        </Link>
        {electron && sub.is_connected && onSend && (
          <div className="flex items-center gap-1 w-full sm:w-auto sm:flex-1 min-w-0">
            <Input
              placeholder="say something…"
              value={composer}
              onChange={(e) => setComposer(e.target.value)}
              className="flex-1 min-w-0 sm:max-w-xs"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && composer.trim() && !sending) {
                  setSending(true);
                  onSend(sub.unique_id, composer);
                  setComposer('');
                  setSending(false);
                }
              }}
            />
            <Button
              variant="primary"
              size="sm"
              disabled={!composer.trim() || sending}
              className="min-w-[44px] min-h-[44px]"
              onClick={() => {
                setSending(true);
                onSend(sub.unique_id, composer);
                setComposer('');
                setSending(false);
              }}
            >
              <Send className="w-3.5 h-3.5" />
            </Button>
          </div>
        )}
        {/* Icon-button cluster — pinned right, never splits across
            rows even when the composer wraps. min-w-[44px] +
            min-h-[44px] meets Apple/WCAG touch-target minimum on
            mobile while staying compact on desktop. */}
        <div className="flex items-center gap-1 ml-auto">
          {/* Public-visibility toggle — when on, this host's sanitized
              scoreboard appears on the unauthenticated `/` page. The
              button is `aria-pressed` so screen readers announce the
              binary state; the emerald fill mirrors the `LIVE` accent
              for visual continuity with "this is going out". */}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onSetPublic?.(sub)}
            aria-pressed={!!sub.is_public}
            className={
              'min-w-[44px] min-h-[44px] ' +
              (sub.is_public
                ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
                : 'text-gray-500 hover:text-gray-700')
            }
            title={
              sub.is_public
                ? 'Public on — visible on the public home page. Click to hide.'
                : 'Mark this live as public (visible on /home)'
            }
            aria-label={sub.is_public ? 'Public on' : 'Public off'}
          >
            <Globe className="w-4 h-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onReconnect?.(sub)}
            disabled={!sub.enabled}
            className="min-w-[44px] min-h-[44px]"
            title={
              sub.enabled
                ? 'Reconnect — wakes the listener and clears the LIVE cache.'
                : 'Enable the subscription before reconnecting.'
            }
            aria-label="Reconnect listener"
          >
            <RotateCcw className="w-4 h-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onToggle?.(sub)}
            className="min-w-[44px] min-h-[44px]"
            title={sub.enabled ? 'Disable' : 'Enable'}
            aria-label={sub.enabled ? 'Disable' : 'Enable'}
          >
            {sub.enabled ? <PowerOff className="w-4 h-4" /> : <Power className="w-4 h-4" />}
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => onDelete?.(sub)}
            className="min-w-[44px] min-h-[44px]"
            title="Delete"
            aria-label="Delete"
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        </div>
      </div>
      )}
    </div>
  );
}

/** Memoized card. Re-renders only when `sub`, `summary`, or one of
 *  the handler refs changes. The parent does structural sharing on
 *  `summary` (preserving per-host object identity when JSON matches)
 *  and `useCallback`-wraps the handlers, so a steady-state 30s poll
 *  re-renders only the cards whose host data actually changed. */
export const SubscriptionCard = memo(SubscriptionCardImpl);


// ─── Page-level totals strip ───────────────────────────────────────

function LivesTotalsStrip({ totals }: { totals: TikTokLivesTotals }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <TotalCell
        label="Live now"
        value={`${totals.n_live} / ${totals.n_total}`}
        tone={totals.n_live > 0 ? 'rose' : 'gray'}
      />
      <TotalCell
        label="Diamonds (24h)"
        value={formatCount(totals.diamonds_24h)}
        tone="amber"
      />
      <TotalCell
        label="Events / min"
        value={formatCount(Math.round(totals.events_per_min))}
        tone="primary"
        hint="Across all tracked hosts in the last 5 minutes"
      />
      <TotalCell
        label="Offline"
        value={String(totals.n_offline)}
        tone="gray"
      />
    </div>
  );
}

function TotalCell({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone: 'rose' | 'amber' | 'primary' | 'gray';
  hint?: string;
}) {
  const valCls = {
    rose:    'text-rose-700 dark:text-rose-300',
    amber:   'text-amber-700 dark:text-amber-300',
    primary: 'text-primary-700 dark:text-primary-300',
    gray:    'text-gray-700',
  }[tone];
  return (
    <div
      className="rounded-md border border-gray-200 bg-white dark:bg-white/5 px-3 py-2"
      title={hint}
    >
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono">
        {label}
      </div>
      <div className={`mt-0.5 text-lg font-bold tabular-nums ${valCls}`}>
        {value}
      </div>
    </div>
  );
}

// ─── Per-row activity strip ─────────────────────────────────────────
//
// Drives the "what's happening with this creator right now" cell on
// the desktop table + mobile card. Reads the server-enriched summary
// when available; falls back to the subscription's own fields when
// the first poll hasn't returned yet.

function ActivityStrip({
  sub,
  summary,
  readOnly,
  onSelectGifter,
}: {
  sub: TikTokSubscription;
  summary?: TikTokLiveSummary;
  /** When true, suppress operator-only lines (the
   *  "checked Xm ago / N reconnects/h" detail on offline cards).
   *  The scoreboard, last-broadcast preview, top-gifter chips,
   *  sparkline, and heatmap still render — they're all derived from
   *  what's already public on TikTok itself. */
  readOnly?: boolean;
  onSelectGifter?: (g: SelectedGifter) => void;
}) {
  // Live state truth source: `summary.active_room_id` is computed
  // backend-side from `tiktok_rooms.last_seen_at > now() - 5min AND
  // ended_at IS NULL` — the freshest possible signal. The cached
  // `sub.is_live` boolean is set by the live-checked-at scraper and
  // can stay TRUE for minutes after a stream actually ends, which
  // produced "everything red, all zeros" on offline cards.
  // Only fall back to the cached flag while the first poll is in
  // flight so the UI doesn't flash gray for a beat on page load.
  const isLive = summary?.active_room_id != null
    || (summary == null && !!sub.is_live);
  const startedAt = summary?.live_started_at ?? null;
  const durationMin = startedAt
    ? Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 60_000))
    : null;
  const viewers = summary?.viewer_count ?? null;
  const diamonds = summary?.diamonds_session ?? 0;
  const topGifters = summary?.top_gifters ?? [];
  const hourly = summary?.hourly_buckets ?? [];
  const favs = summary?.favorites_in_room ?? [];
  const lastGiftAge = summary?.last_gift_age_s ?? null;
  const lastCommentAge = summary?.last_comment_age_s ?? null;
  const vsTypical = summary?.diamonds_vs_typical ?? null;
  const reconnects1h = summary?.reconnects_1h ?? 0;
  const nUnique = summary?.n_unique_gifters ?? 0;
  const nFirstTime = summary?.n_first_time_gifters ?? 0;

  // "Diamonds vs typical" multiplier — single most actionable signal
  // for picking which live to drop into. Color tones the chip:
  // ≥2× = rose (rocket), ≥1.2× = amber, ≤0.5× = slate (dud).
  let vsTypicalChip: { label: string; cls: string } | null = null;
  if (vsTypical != null && Number.isFinite(vsTypical)) {
    if (vsTypical >= 2) {
      vsTypicalChip = { label: `🚀 ${vsTypical.toFixed(1)}× typical`, cls: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300' };
    } else if (vsTypical >= 1.2) {
      vsTypicalChip = { label: `↑ ${vsTypical.toFixed(1)}× typical`, cls: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300' };
    } else if (vsTypical <= 0.5) {
      vsTypicalChip = { label: `🐢 ${vsTypical.toFixed(1)}× typical`, cls: 'bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300' };
    } else {
      // Within the boring band [0.5, 1.2) — don't render
    }
  }

  // Silence detector — only render when the live has gone quiet.
  // Threshold: gift > 90s AND comment > 30s.
  let silenceChip: { label: string } | null = null;
  if (
    isLive
    && lastGiftAge != null && lastGiftAge > 90
    && lastCommentAge != null && lastCommentAge > 30
  ) {
    const longest = Math.max(lastGiftAge, lastCommentAge);
    silenceChip = {
      label: `🔇 quiet ${fmtDur(longest)}`,
    };
  }

  // Active-poll chip — present when the host has a poll open right
  // now (backend gates on mt=2 + last 60s freshness). Truncated title
  // since poll prompts can be long.
  let pollChip: { label: string; title: string } | null = null;
  const ap = summary?.active_poll;
  if (isLive && ap && ap.title) {
    const t = ap.title.length > 32 ? `${ap.title.slice(0, 32)}…` : ap.title;
    pollChip = { label: `📊 Poll: ${t}`, title: ap.title };
  }

  const stats = summary?.session_stats ?? {};
  return (
    <div className="flex flex-col gap-2">
      {/* Scoreboard grid — the headline numbers about THIS broadcast.
          Operator's first-ask fields: diamonds, viewers, battles,
          W-L, comments, gifts, likes, joins. Renders only when the
          host is live; offline cards skip directly to the offline
          line below. Cell values default to "—" so the grid stays
          structurally stable while the first poll comes in. */}
      {isLive && (
        <ScoreboardGrid
          diamonds={diamonds}
          viewers={viewers}
          viewerHistory={summary?.viewer_history}
          stats={stats}
          uniqueGifters={nUnique}
          firstTimeGifters={nFirstTime}
          durationMin={durationMin}
          nPauses={summary?.n_pauses ?? 0}
          lastPauseAgeS={summary?.last_pause_age_s ?? null}
          nEnvelopes={summary?.n_envelopes_session ?? 0}
          envelopeDiamonds={summary?.envelope_diamonds_session ?? 0}
        />
      )}

      {/* Optional context chips ABOVE the scoreboard — the
          "is this live worth dropping into" signals that aren't
          plain counters: vs-typical multiplier, cpm-vs-baseline
          flag, silence detector. Only renders when at least one
          chip has signal (kept hidden when nothing actionable). */}
      {isLive && (vsTypicalChip || silenceChip || pollChip) && (
        <div className="flex items-center gap-1.5 flex-wrap text-[10px] font-mono">
          {vsTypicalChip && (
            <span className={`shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full ${vsTypicalChip.cls}`}>
              {vsTypicalChip.label}
            </span>
          )}
          {silenceChip && (
            <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
              {silenceChip.label}
            </span>
          )}
          {pollChip && (
            <span
              title={pollChip.title}
              className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300"
            >
              {pollChip.label}
            </span>
          )}
        </div>
      )}
      {!isLive && (
        <div className="flex flex-col gap-1.5">
          {/* Status pill row — same as before but trimmed since the
              scoreboard below now carries the "when did this end"
              info via the latest broadcast. The "checked Xm ago" and
              "N reconnects/h" detail leak operator-only signals
              (scraper cadence, listener instability), so they're
              suppressed in read-only mode — the bare `offline` pill
              still renders so the public viewer sees the state. */}
          <div className="flex items-center gap-2 text-[11px] font-mono text-gray-500">
            <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] uppercase tracking-wider">
              offline
            </span>
            {!readOnly && sub.live_checked_at && (
              <span className="tabular-nums">
                checked {relTime(sub.live_checked_at)}
              </span>
            )}
            {!readOnly && reconnects1h > 0 && (
              <span
                className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300 text-[10px]"
                title="Listener has reconnected this many times in the last hour — may be unstable."
              >
                ⚠ {reconnects1h} reconnect{reconnects1h === 1 ? '' : 's'}/h
              </span>
            )}
          </div>
          {/* Last-broadcast mini-scoreboard. Renders when the host has
              at least one recorded broadcast in `last_broadcasts`. The
              `ended_at` is fed from the room's `last_seen_at` when the
              listener didn't flag a clean shutdown — we mark it with a
              `~` prefix on the relative-time stamp so the operator
              knows it's inferred, not authoritative. */}
          {(() => {
            const last = summary?.last_broadcasts?.[0];
            if (!last || !last.started_at) return null;
            const endLabel = last.ended_at
              ? `${last.ended_inferred ? '~' : ''}${relTime(last.ended_at)}`
              : '—';
            return (
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-1 text-center">
                <Stat
                  label="last live"
                  value={endLabel}
                  prominent
                />
                <Stat
                  label="duration"
                  value={last.duration_min != null ? fmtDuration(last.duration_min) : '—'}
                />
                <Stat
                  label="diamonds"
                  value={last.diamonds > 0 ? compactCount(last.diamonds) : '—'}
                  accent="amber"
                />
                <Stat
                  label="peak 👁"
                  value={(last.peak_viewers ?? 0) > 0 ? compactCount(last.peak_viewers!) : '—'}
                />
                <Stat
                  label="comments"
                  value={(last.n_comments ?? 0) > 0 ? compactCount(last.n_comments!) : '—'}
                  sub={(last.n_gifts ?? 0) > 0 ? `${compactCount(last.n_gifts!)} gifts` : undefined}
                />
              </div>
            );
          })()}
        </div>
      )}

      {/* PK with countdown + W-L hint moved up next to the `IN MATCH`
          tag in the name row. See SubscriptionCard's name-row block. */}

      {/* Favourite-gifter presence — pre-gift edge. */}
      {favs.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap text-[10px] font-mono">
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-200">
            ★ {favs.length} fav{favs.length === 1 ? '' : 's'} in room
          </span>
          {favs.slice(0, 3).map((f) => (
            <span key={f.user_id || f.unique_id || ''} className="inline-flex items-center gap-1 text-gray-600">
              {f.avatar_url ? (
                <img
                  src={f.avatar_url}
                  alt=""
                  className="w-4 h-4 rounded-full ring-1 ring-white dark:ring-white/10"
                  referrerPolicy="no-referrer"
                  loading="lazy"
                />
              ) : null}
              @{f.unique_id || '—'}
            </span>
          ))}
        </div>
      )}

      {/* Top gifters — top 3, each as avatar+handle+amount. Each
          chip opens the gifter modal at the page level, scoped to
          the host's active room (so the modal's default "this
          broadcast" view shows the gifts that put them on this
          podium). Falls back to a static chip when no
          `onSelectGifter` handler was passed in. */}
      {topGifters.length > 0 && topGifters[0]?.diamonds > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap text-[10px] font-mono">
          <span className="text-gray-500 shrink-0">👑 Top:</span>
          {topGifters.slice(0, 3).map((g, i) => {
            const handleClick = () => {
              if (!onSelectGifter) return;
              onSelectGifter({
                userId:   g.user_id ?? null,
                uniqueId: g.unique_id ?? null,
                nickname: g.nickname ?? null,
                diamonds: g.diamonds,
                gifts:    g.gifts,
                // Pin the modal to the host's CURRENT room when live
                // so its default view sums gifts in this session.
                roomId:   summary?.active_room_id ?? null,
                currentHandle: sub.unique_id,
              });
            };
            return (
              <button
                type="button"
                key={g.user_id || g.unique_id || i}
                onClick={handleClick}
                disabled={!onSelectGifter}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-50 dark:bg-white/5 text-gray-700 hover:bg-gray-100 dark:hover:bg-white/10 transition-colors cursor-pointer disabled:cursor-default"
                title={`${g.nickname || g.unique_id || ''} — open full history`}
              >
                {g.avatar_url ? (
                  <img
                    src={g.avatar_url}
                    alt=""
                    className="w-4 h-4 rounded-full ring-1 ring-white dark:ring-white/10"
                    referrerPolicy="no-referrer"
                    loading="lazy"
                  />
                ) : null}
                <span className="truncate max-w-[6rem]">@{g.unique_id ?? '—'}</span>
                <span className="text-amber-700 dark:text-amber-300 tabular-nums">
                  {compactCount(g.diamonds)}💎
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Audience composition (gifters · new) is rendered inline
          inside the scoreboard grid above. */}

      {/* Activity row — 60-min diamond sparkline + 7-day heatmap in
          a 50/50 split. When one side has no data we still hold its
          slot with a dashed "no activity" placeholder so the row
          stays visually balanced. */}
      {(hourly.some((v) => v > 0) || (summary?.week_calendar?.some((d) => d.diamonds > 0 || d.rooms > 0))) && (
        <div className="grid grid-cols-2 gap-3 items-center">
          <div className="min-w-0">
            {hourly.some((v) => v > 0) ? (
              <Sparkline values={hourly} />
            ) : (
              <NoActivityLine label="60m" />
            )}
          </div>
          <div className="min-w-0 flex justify-start">
            {summary?.week_calendar && summary.week_calendar.some((d) => d.diamonds > 0 || d.rooms > 0) ? (
              <WeekHeatmap days={summary.week_calendar} />
            ) : (
              <NoActivityLine label="7d" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Last-7-days mini-strip: 7 boxes in a single row, one per day,
 *  oldest → newest (today on the right). Each box shows its weekday
 *  initial inside and is tinted by diamond intensity on the same
 *  sky-blue ramp the live calendar + profile heatmap use. */
function WeekHeatmap({ days }: { days: NonNullable<TikTokLiveSummary['week_calendar']> }) {
  // Active operator timezone — labels must match the buckets the
  // backend just sent (which were computed in this same zone).
  const { tz } = useTikTokTimezone();
  const maxDiamonds = Math.max(0, ...days.map((d) => d.diamonds));
  const total = days.reduce((acc, d) => acc + d.diamonds, 0);

  // Anchor "today" as the date components of NOW in the active tz,
  // packed into a fake-UTC Date (date bag — never .toISOString'd).
  // This is what makes "today's box" + "today's weekday letter" agree
  // with the operator's wall-clock calendar instead of the browser's.
  const todayParts = partsInZone(new Date(), tz);
  const todayAnchor = new Date(Date.UTC(
    todayParts.year, todayParts.month - 1, todayParts.day,
  ));

  const LEVEL_COLOR = [
    'bg-gray-100 dark:bg-white/[0.04]',
    'bg-sky-100 dark:bg-sky-500/[0.20]',
    'bg-sky-300 dark:bg-sky-500/[0.45]',
    'bg-sky-500 dark:bg-sky-500/[0.75]',
    'bg-sky-700 dark:bg-sky-400',
  ];
  // Borders are tinted one notch darker than the fill so the outline
  // reinforces the cell's intensity instead of overprinting it with a
  // mismatched gray. Empty cells get a very soft gray edge; filled
  // cells get a darker shade of the same sky family.
  const LEVEL_BORDER = [
    'ring-gray-200 dark:ring-white/10',
    'ring-sky-300/70 dark:ring-sky-400/30',
    'ring-sky-500/70 dark:ring-sky-300/40',
    'ring-sky-700/70 dark:ring-sky-200/50',
    'ring-sky-900/60 dark:ring-sky-100/60',
  ];
  const levelFor = (d: number): number => {
    if (d <= 0 || maxDiamonds <= 0) return 0;
    const ratio = Math.sqrt(d / maxDiamonds);
    if (ratio >= 0.8) return 4;
    if (ratio >= 0.55) return 3;
    if (ratio >= 0.3) return 2;
    return 1;
  };

  const WEEKDAY_LETTER = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

  // Pre-compute weekday letter + level for each day so the header
  // row and cell row stay in lockstep.
  const cells = days.map((d, i) => {
    const daysAgo = days.length - 1 - i;
    const date = new Date(todayAnchor);
    date.setUTCDate(todayAnchor.getUTCDate() - daysAgo);
    const lvl = levelFor(d.diamonds);
    const datePart = date.toLocaleDateString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric',
    });
    const hoverTitle =
      `${datePart}\n` +
      `${d.rooms} broadcast${d.rooms === 1 ? '' : 's'}\n` +
      `${fmtDuration(d.duration_min)} streamed\n` +
      `${d.diamonds.toLocaleString()} 💎`;
    return {
      d,
      lvl,
      letter: WEEKDAY_LETTER[date.getUTCDay()],
      hoverTitle,
    };
  });

  return (
    <div
      className="inline-block"
      title={`Last 7 days — ${total.toLocaleString()} 💎 total`}
    >
      <div
        className="grid gap-x-[2px] gap-y-[2px]"
        style={{ gridTemplateColumns: 'repeat(7, 2.25rem)' }}
      >
        {/* Header row — weekday letter for each day. */}
        {cells.map((c, i) => (
          <div
            key={`h-${i}`}
            className="text-[8px] font-mono text-gray-500 text-center leading-none"
          >
            {c.letter}
          </div>
        ))}
        {/* Cell row — diamond count inside a short square. */}
        {cells.map((c, i) => {
          const textTone = c.lvl >= 3
            ? 'text-sky-50 dark:text-sky-50'
            : 'text-gray-700';
          return (
            <div
              key={i}
              className={
                `h-6 rounded-sm ring-1 ring-inset ${LEVEL_COLOR[c.lvl]} ${LEVEL_BORDER[c.lvl]} ` +
                `flex items-center justify-center font-mono leading-none ${textTone}`
              }
              title={c.hoverTitle}
              aria-label={c.hoverTitle}
            >
              <span className="text-[9px] tabular-nums">
                {c.d.diamonds > 0 ? compactCount(c.d.diamonds) : '–'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Dashed placeholder used in the activity row when one of the two
 *  panels has no data. Keeps the 50/50 row visually balanced and
 *  signals "checked, nothing to show" rather than collapsing the
 *  slot (which would leave the populated half visually orphaned). */
function NoActivityLine({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 w-full text-[9px] font-mono text-gray-400">
      <div className="flex-1 border-t border-dashed border-gray-300 dark:border-white/15" />
      <span className="shrink-0">no activity</span>
      <span className="shrink-0 tabular-nums">· {label}</span>
    </div>
  );
}

/** Compact "Hh Mm" format for a number of minutes. */
function fmtDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

/** Compact "Mm Ss" / "Ss" format for a number of seconds. */
function fmtDur(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}:${String(s).padStart(2, '0')}` : `${m}m`;
}

/** Scoreboard grid for the active broadcast. Sport-stat density:
 *  big number on top, tiny mono label underneath. The ten cells
 *  cover everything an operator asks at-a-glance ("how big is the
 *  room? how much money is moving? is the stream chatty? are they
 *  in PKs?"). Hidden when not live. */
function ScoreboardGrid({
  diamonds,
  viewers,
  viewerHistory,
  stats,
  uniqueGifters,
  firstTimeGifters,
  durationMin,
  nPauses,
  lastPauseAgeS,
  nEnvelopes,
  envelopeDiamonds,
}: {
  diamonds: number;
  viewers: number | null;
  viewerHistory?: number[];
  stats: NonNullable<TikTokLiveSummary['session_stats']>;
  uniqueGifters: number;
  firstTimeGifters: number;
  durationMin: number | null;
  nPauses: number;
  lastPauseAgeS: number | null;
  nEnvelopes: number;
  envelopeDiamonds: number;
}) {
  // Battles + W-L cell renders as a stacked dual-line: top = total
  // battles, bottom = `W–L–D`. Only when there's been ≥1 battle in
  // the session.
  const battles = stats.n_battles ?? 0;
  const wld = battles > 0
    ? `${stats.session_w ?? 0}-${stats.session_l ?? 0}${(stats.session_d ?? 0) > 0 ? `-${stats.session_d}` : ''}`
    : null;

  return (
    <div className="grid grid-cols-3 sm:grid-cols-5 gap-1 text-center">
      <Stat
        label="diamonds"
        value={compactCount(diamonds)}
        accent="amber"
        prominent
        sub={
          nEnvelopes > 0
            ? `🧧 ${nEnvelopes}${envelopeDiamonds > 0 ? ` · +${compactCount(envelopeDiamonds)}` : ''}`
            : undefined
        }
      />
      <Stat
        label="viewers"
        value={viewers != null ? compactCount(viewers) : '—'}
        accent="rose"
        prominent
        sparkline={viewerHistory && viewerHistory.length >= 2 ? viewerHistory : undefined}
      />
      <Stat
        label="battles"
        value={battles > 0 ? String(battles) : '—'}
        sub={wld ? `${wld} W-L${(stats.session_d ?? 0) > 0 ? '-D' : ''}` : undefined}
        accent="purple"
        prominent
      />
      <Stat
        label="duration"
        value={durationMin != null ? fmtDuration(durationMin) : '—'}
        sub={
          nPauses > 0
            ? `⏸ ${nPauses}×${lastPauseAgeS != null ? ` · ${fmtDur(lastPauseAgeS)} ago` : ''}`
            : undefined
        }
      />
      <Stat
        label="biggest 💎"
        value={
          (stats.largest_gift_diamonds ?? 0) > 0
            ? compactCount(stats.largest_gift_diamonds!)
            : '—'
        }
      />
      <Stat
        label="comments"
        value={compactCount(stats.n_comments ?? 0)}
        sub={stats.n_unique_commenters ? `${compactCount(stats.n_unique_commenters)} ppl` : undefined}
      />
      <Stat
        label="gifts"
        value={compactCount(stats.n_gifts ?? 0)}
        sub={uniqueGifters > 0 ? `${compactCount(uniqueGifters)} ppl${firstTimeGifters > 0 ? ` · ${firstTimeGifters} new` : ''}` : undefined}
      />
      <Stat label="likes" value={compactCount(stats.n_likes ?? 0)} />
      <Stat label="joins" value={compactCount(stats.n_joins ?? 0)} />
      <Stat
        label="follows"
        value={compactCount(stats.n_follows ?? 0)}
        sub={(stats.n_shares ?? 0) > 0 ? `${compactCount(stats.n_shares!)} shares` : undefined}
      />
    </div>
  );
}

/** Single scoreboard cell. Tight, mono. Prominent variant uses a
 *  larger value font for the headline metrics (diamonds / viewers /
 *  battles / duration). Optional sparkline renders an inline trend
 *  strip below the value (used for the viewers cell). */
function Stat({
  label,
  value,
  sub,
  accent,
  prominent,
  sparkline,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: 'amber' | 'rose' | 'purple';
  prominent?: boolean;
  sparkline?: number[];
}) {
  const valCls = (() => {
    switch (accent) {
      case 'amber':  return 'text-amber-700 dark:text-amber-300';
      case 'rose':   return 'text-rose-700 dark:text-rose-300';
      case 'purple': return 'text-purple-700 dark:text-purple-300';
      default:       return 'text-gray-900';
    }
  })();
  const sparkStroke = (() => {
    switch (accent) {
      case 'amber':  return 'stroke-amber-500';
      case 'rose':   return 'stroke-rose-500';
      case 'purple': return 'stroke-purple-500';
      default:       return 'stroke-gray-500';
    }
  })();
  const valSize = prominent ? 'text-base' : 'text-sm';
  return (
    <div className="rounded border border-gray-200 bg-gray-50 dark:bg-white/5 px-1.5 py-1 min-w-0">
      <div className={`font-bold tabular-nums ${valSize} ${valCls} truncate`}>
        {value}
      </div>
      {sparkline && sparkline.length >= 2 && (
        <MicroSparkline values={sparkline} strokeCls={sparkStroke} />
      )}
      <div className="text-[9px] uppercase tracking-wider font-mono text-gray-500 truncate">
        {label}
      </div>
      {sub && (
        <div className="text-[9px] font-mono text-gray-400 truncate">
          {sub}
        </div>
      )}
    </div>
  );
}

/** Tiny inline sparkline for stat cells. Single-stroke polyline with
 *  no axes / labels — pure visual trend. Fluid width via 100-unit
 *  viewBox stretched with `width="100%"`. The `min === max` case is
 *  flat-line at vertical center to avoid divide-by-zero in the
 *  height calc. */
function MicroSparkline({ values, strokeCls }: { values: number[]; strokeCls: string }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  const h = 8;
  const W = 100;
  const step = W / Math.max(1, values.length - 1);
  const pts = values
    .map((v, i) => `${(i * step).toFixed(2)},${(h - ((v - min) / range) * h).toFixed(2)}`)
    .join(' ');
  return (
    <svg
      viewBox={`0 0 ${W} ${h}`}
      preserveAspectRatio="none"
      className="w-full"
      style={{ height: `${h}px` }}
    >
      <polyline
        points={pts}
        fill="none"
        strokeWidth="1.2"
        strokeLinejoin="round"
        strokeLinecap="round"
        className={strokeCls}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** Listener-health traffic-light dot — replaces the bare state pill.
 *  Combines connection state + last-event freshness + reconnect
 *  pressure into a single green/amber/red dot. The tooltip carries
 *  the full diagnostic. */
function HealthDot({
  sub,
  summary,
}: {
  sub: TikTokSubscription;
  summary?: TikTokLiveSummary;
}) {
  const lastAge = summary?.last_event_age_s ?? null;
  const reconnects = summary?.reconnects_1h ?? 0;
  const isLive = !!sub.is_live;
  const stateOk = sub.state === 'CONNECTED' || sub.state === 'LIVE_ENDED';

  // Red: error state, OR live but no events in 60s, OR >5 reconnects/hr
  // Amber: connecting, OR live but no events in 30s, OR 1-5 reconnects/hr
  // Green: connected, fresh events, no reconnect pressure
  // Gray: offline / disabled (not active)
  let dotCls = 'bg-gray-300';
  let label = sub.state;
  let detail = '';
  if (sub.state === 'ERROR') {
    dotCls = 'bg-rose-500';
    label = 'Error';
    detail = sub.profile_error || 'Listener error';
  } else if (sub.state === 'DISABLED') {
    dotCls = 'bg-gray-400';
    label = 'Disabled';
  } else if (sub.state === 'CONNECTING') {
    dotCls = 'bg-amber-500';
    label = 'Connecting…';
  } else if (isLive && lastAge != null && lastAge > 60) {
    dotCls = 'bg-rose-500';
    label = 'Stale';
    detail = `Last event ${fmtDur(lastAge)} ago — listener may be hung`;
  } else if (isLive && lastAge != null && lastAge > 30) {
    dotCls = 'bg-amber-500';
    label = 'Slow';
    detail = `Last event ${fmtDur(lastAge)} ago`;
  } else if (reconnects >= 5) {
    dotCls = 'bg-rose-500';
    label = `${reconnects} reconnects/h`;
  } else if (reconnects >= 1) {
    dotCls = 'bg-amber-500';
    label = `${reconnects} reconnect${reconnects === 1 ? '' : 's'}/h`;
  } else if (stateOk) {
    dotCls = 'bg-emerald-500';
    label = sub.state;
  }
  const tooltip = detail ? `${label} — ${detail}` : label;
  // Hide entirely when there's nothing to warn about: the LIVE pill on
  // the avatar already shows liveness, and a healthy listener doesn't
  // need its own pill. Render only on actual warning states (rose or
  // amber dots) so the badge stays a *problem* signal.
  const isWarning = dotCls.includes('rose') || dotCls.includes('amber');
  if (!isWarning) return null;
  return (
    <span
      className="shrink-0 inline-flex items-center gap-1.5"
      title={tooltip}
      aria-label={tooltip}
    >
      <span className={`w-2 h-2 rounded-full ${dotCls}`} />
      <span className="text-[9px] font-mono text-gray-500 uppercase tracking-wider hidden sm:inline">
        {label}
      </span>
    </span>
  );
}

function Sparkline({ values }: { values: number[] }) {
  // 60 minute-buckets, oldest→newest. Fluid width — uses a 100-unit
  // viewBox stretched via `width="100%"` so the chart shrinks on a
  // narrow card and grows on a wide one without re-renders. Caller
  // bounds with a max-width wrapper.
  const max = Math.max(1, ...values);
  const h = 22;
  const W = 100;
  const step = W / Math.max(1, values.length - 1);
  const pts = values
    .map((v, i) => `${(i * step).toFixed(2)},${(h - (v / max) * h).toFixed(2)}`)
    .join(' ');
  const lastV = values[values.length - 1] || 0;
  const total = values.reduce((a, b) => a + b, 0);
  return (
    <div
      className="flex items-center gap-2 w-full"
      title={`Last 60 minutes — ${total.toLocaleString()} 💎 total, peak ${max.toLocaleString()}/min`}
    >
      <svg
        viewBox={`0 0 ${W} ${h}`}
        preserveAspectRatio="none"
        className="w-full overflow-visible"
        style={{ height: `${h}px` }}
      >
        <polyline
          points={pts}
          fill="none"
          stroke="#f59e0b"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        <circle
          cx={(values.length - 1) * step}
          cy={h - (lastV / max) * h}
          r="1.5"
          fill="#f59e0b"
        />
      </svg>
      <span className="text-[9px] font-mono text-gray-500 tabular-nums shrink-0">
        60m
      </span>
    </div>
  );
}

function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}

function relTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

/**
 * TikTokNotificationsCenter — Stream design.
 *
 * Floating bell at the bottom-right (next to the LiveChat widget on
 * desktop, stacked above it on mobile) opens a slide-in drawer
 * reframed as a live activity feed:
 *   • host-grouped (collapsible), not date-grouped — host is the
 *     mental model the operator works in
 *   • "● live" dot in the header reflects whether the polling stream
 *     is healthy
 *   • a "new since you last looked" divider appears the moment the
 *     drawer reopens, so you don't have to scan everything
 *   • items that arrive while the drawer is open get a brief tinted
 *     fade so realtime activity is visually obvious
 *   • avatars come from `payload.user.avatar_url`; type icon is a
 *     small corner badge instead of replacing identity
 *
 * All responsive bugs caught by the audit are fixed here:
 *   • bell offset gated to ≥sm (no LiveChat collision on iPhone SE)
 *   • close X is 44px (Apple/WCAG minimum)
 *   • per-row clear is always visible at low opacity (touch-friendly)
 *   • slide-in + fade-in animations
 *   • header buttons collapse to icon-only on mobile
 *   • dropped wrong dark-mode tokens (`dark:bg-gray-100/[0.04]`) on
 *     neutrals — let auto-inversion do its job
 *   • focus moves to close button on open, restored on close
 */

import { forwardRef, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from '@tanstack/react-router';
import {
  Bell,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Gem,
  Gift as GiftIcon,
  Loader2,
  MessageSquare,
  Radio,
  Sparkles,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import toast from 'react-hot-toast';

import { useNotifications } from '@admin/hooks/useNotifications';
import { fmtMonthDayTime, useTikTokTimezone } from '@admin/contexts/TikTokTimezoneContext';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { SafeAvatar } from '@admin/components/SafeAvatar';
import {
  TikTokUserBadges,
  type IdentityBlock,
} from '@admin/components/TikTokUserBadges';
import type { TikTokNotification } from '@admin/services/tiktok';

type TypeFilter = 'all' | 'gift' | 'comment' | 'join';

export function TikTokNotificationsCenter() {
  const [open, setOpen] = useState(false);
  const [confirmClearAll, setConfirmClearAll] = useState(false);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  // Hosts the user has manually collapsed inside this drawer session.
  // Reset on close so reopening is fresh.
  const [collapsedHosts, setCollapsedHosts] = useState<Set<string>>(() => new Set());
  // Snapshot the lastOpenedAt at the moment the drawer opens so the
  // "new since" line stays stable while you read; markOpenedNow then
  // re-bases it for the next open.
  const sessionBaselineRef = useRef<string | null>(null);
  // Track which item ids existed when the drawer opened. Anything
  // arriving afterwards gets a fade-in flash so live activity is
  // visually obvious.
  const baselineIdsRef = useRef<Set<number>>(new Set());
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);
  const triggerBtnRef = useRef<HTMLButtonElement | null>(null);

  const {
    items,
    unreadCount,
    loading,
    error,
    connected,
    lastOpenedAt,
    markOpenedNow,
    markRead,
    markAllRead,
    clear,
    clearAll,
  } = useNotifications();

  // Mount focus management: when drawer opens, focus the close button
  // (a11y) and snapshot the baselines.
  useEffect(() => {
    if (!open) return;
    sessionBaselineRef.current = lastOpenedAt;
    baselineIdsRef.current = new Set(items.map((n) => n.id));
    // Focus after paint so the panel slide-in finishes first.
    const t = setTimeout(() => closeBtnRef.current?.focus(), 50);
    return () => {
      clearTimeout(t);
    };
    // We deliberately depend on `open` only — capturing items on open
    // is the whole point of the baseline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        triggerBtnRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  // Stamp lastOpenedAt when the drawer closes — the "new since" line
  // for the *next* open should be relative to the moment they
  // actually finished looking, not the moment they tapped.
  useEffect(() => {
    if (!open) return;
    return () => {
      markOpenedNow();
    };
  }, [open, markOpenedNow]);

  return (
    <>
      <BellTrigger
        ref={triggerBtnRef}
        unreadCount={unreadCount}
        connected={connected}
        onToggle={() => setOpen((v) => !v)}
        open={open}
      />

      {open && (
        <>
          {/* Backdrop. fade-in keeps the open feel responsive. */}
          <div
            className="fixed inset-0 z-[54] bg-black/30 dark:bg-black/50 animate-in fade-in duration-150"
            onClick={() => {
              setOpen(false);
              triggerBtnRef.current?.focus();
            }}
            aria-hidden
          />
          <aside
            className="fixed right-0 top-0 bottom-0 z-[55] w-full sm:w-[420px] bg-white sm:border-l border-gray-200 shadow-2xl flex flex-col animate-in slide-in-from-right duration-200"
            role="dialog"
            aria-label="Notifications"
            aria-modal="true"
          >
            <DrawerHeader
              ref={closeBtnRef}
              loading={loading}
              connected={connected}
              unreadCount={unreadCount}
              hasItems={items.length > 0}
              typeFilter={typeFilter}
              setTypeFilter={setTypeFilter}
              countsByType={countByType(items)}
              onClose={() => {
                setOpen(false);
                triggerBtnRef.current?.focus();
              }}
              onMarkAllRead={async () => {
                try {
                  await markAllRead();
                } catch (e) {
                  toast.error(
                    (e as Error).message || 'Failed to mark all as read',
                  );
                }
              }}
              onClearAll={() => setConfirmClearAll(true)}
            />
            {error && (
              <div className="px-4 py-2 text-xs text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-500/10 border-b border-rose-200 dark:border-rose-500/30">
                {error}
              </div>
            )}
            <div className="flex-1 overflow-y-auto overscroll-contain">
              {items.length === 0 ? (
                <EmptyState loading={loading} />
              ) : (
                <StreamBody
                  items={items}
                  typeFilter={typeFilter}
                  collapsedHosts={collapsedHosts}
                  toggleHost={(h) =>
                    setCollapsedHosts((prev) => {
                      const next = new Set(prev);
                      if (next.has(h)) next.delete(h);
                      else next.add(h);
                      return next;
                    })
                  }
                  baselineIds={baselineIdsRef.current}
                  newSinceIso={sessionBaselineRef.current}
                  onMarkRead={markRead}
                  onClear={clear}
                  onClose={() => setOpen(false)}
                />
              )}
            </div>
          </aside>
        </>
      )}

      {/* Custom confirm — replaces native `confirm()` which behaves
          badly on mobile WebView. */}
      <Modal
        isOpen={confirmClearAll}
        onClose={() => setConfirmClearAll(false)}
        title="Clear all notifications?"
        className="max-w-sm"
        footer={
          <div className="flex items-center justify-end gap-2 w-full">
            <Button
              variant="ghost"
              onClick={() => setConfirmClearAll(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={async () => {
                setConfirmClearAll(false);
                try {
                  await clearAll();
                } catch (e) {
                  toast.error(
                    (e as Error).message || 'Failed to clear',
                  );
                }
              }}
            >
              <Trash2 className="w-3.5 h-3.5 mr-1.5" />
              Clear all
            </Button>
          </div>
        }
      >
        <p className="text-sm text-gray-700">
          This soft-deletes the entire notification stream. The rows
          stay in the database for a short window so the worker's
          `cleared` flag can roll back if needed, but they won't be
          surfaced here again.
        </p>
      </Modal>
    </>
  );
}

// ─── Floating bell trigger ─────────────────────────────────────────

interface BellTriggerProps {
  unreadCount: number;
  connected: boolean;
  onToggle: () => void;
  open: boolean;
}

const BellTrigger = forwardRef<HTMLButtonElement, BellTriggerProps>(
  function BellTrigger(
    { unreadCount, onToggle, open },
    ref,
  ) {
    return (
      <button
        ref={ref}
        type="button"
        onClick={onToggle}
        // <sm: stacks above the LiveChat widget (right-5 bottom-[80px])
        // sm+:  sits to the LEFT of the LiveChat (right-[88px] bottom-5)
        // 48px square ≥ Apple's 44px minimum.
        className={`fixed z-50 inline-flex items-center justify-center w-12 h-12 rounded-full bg-primary-600 hover:bg-primary-700 text-white shadow-lg transition-all bottom-[80px] right-5 sm:bottom-5 sm:right-[88px] ${open ? 'scale-90' : ''}`}
        aria-label={`Notifications${unreadCount > 0 ? ` — ${unreadCount} unread` : ''}`}
        aria-expanded={open}
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span
            className="absolute -top-1 -right-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold ring-2 ring-white animate-in fade-in"
            aria-hidden
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>
    );
  },
);

// ─── Drawer header ─────────────────────────────────────────────────

interface DrawerHeaderProps {
  loading: boolean;
  connected: boolean;
  unreadCount: number;
  hasItems: boolean;
  typeFilter: TypeFilter;
  setTypeFilter: (t: TypeFilter) => void;
  countsByType: Record<string, number>;
  onClose: () => void;
  onMarkAllRead: () => void;
  onClearAll: () => void;
}

const DrawerHeader = forwardRef<HTMLButtonElement, DrawerHeaderProps>(
  function DrawerHeader(
    {
      loading,
      connected,
      unreadCount,
      hasItems,
      typeFilter,
      setTypeFilter,
      countsByType,
      onClose,
      onMarkAllRead,
      onClearAll,
    },
    closeRef,
  ) {
    const liveDotClass = connected
      ? 'bg-emerald-500 animate-pulse'
      : 'bg-gray-400';
    return (
      <header className="border-b border-gray-200">
        <div className="px-4 py-3 flex items-center gap-2">
          <span
            className={`shrink-0 inline-block w-2 h-2 rounded-full ${liveDotClass}`}
            title={connected ? 'Live — polling healthy' : 'Disconnected'}
            aria-label={connected ? 'Live' : 'Disconnected'}
          />
          <h2 className="text-base font-bold text-gray-900">Notifications</h2>
          {unreadCount > 0 && (
            <span className="text-[11px] font-mono text-gray-500 tabular-nums">
              {unreadCount} unread
            </span>
          )}
          {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" />}
          <div className="ml-auto flex items-center gap-1">
            {hasItems && unreadCount > 0 && (
              <button
                type="button"
                onClick={onMarkAllRead}
                className="inline-flex items-center justify-center w-9 sm:w-auto h-9 sm:h-9 px-0 sm:px-2 gap-1 rounded-md text-[11px] font-mono text-primary-700 hover:bg-primary-50 dark:hover:bg-primary-500/15"
                title="Mark all as read"
                aria-label="Mark all as read"
              >
                <CheckCheck className="w-4 h-4" />
                <span className="hidden sm:inline">Mark all read</span>
              </button>
            )}
            {hasItems && (
              <button
                type="button"
                onClick={onClearAll}
                className="inline-flex items-center justify-center w-9 sm:w-auto h-9 sm:h-9 px-0 sm:px-2 gap-1 rounded-md text-[11px] font-mono text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-500/15"
                title="Clear all"
                aria-label="Clear all"
              >
                <Trash2 className="w-4 h-4" />
                <span className="hidden sm:inline">Clear all</span>
              </button>
            )}
            <button
              ref={closeRef}
              type="button"
              onClick={onClose}
              className="inline-flex items-center justify-center w-11 h-11 rounded-md text-gray-500 hover:bg-gray-100 dark:hover:bg-white/10"
              aria-label="Close notifications"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
        {/* Type-filter chip strip — gives one-tap filtering and a
            count per type so the operator can see at a glance what
            kind of activity has been happening. */}
        <div className="px-3 pb-2 flex items-center gap-1 overflow-x-auto whitespace-nowrap">
          {([
            { id: 'all',     label: 'All' },
            { id: 'gift',    label: 'Gifts' },
            { id: 'comment', label: 'Comments' },
            { id: 'join',    label: 'Joins' },
          ] as { id: TypeFilter; label: string }[]).map((t) => {
            const active = typeFilter === t.id;
            const n = t.id === 'all'
              ? Object.values(countsByType).reduce((a, b) => a + b, 0)
              : countsByType[t.id] ?? 0;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTypeFilter(t.id)}
                className={`shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-mono uppercase tracking-wider border transition-colors ${
                  active
                    ? 'bg-primary-100 dark:bg-primary-500/20 border-primary-300 text-primary-700 dark:text-primary-300'
                    : 'bg-white dark:bg-white/5 border-gray-200 text-gray-700 hover:border-gray-300'
                }`}
              >
                {t.label}
                {n > 0 && (
                  <span className="text-[10px] opacity-70 tabular-nums">
                    {n}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </header>
    );
  },
);

// ─── Stream body — host-grouped collapsible feed ───────────────────

function StreamBody({
  items,
  typeFilter,
  collapsedHosts,
  toggleHost,
  baselineIds,
  newSinceIso,
  onMarkRead,
  onClear,
  onClose,
}: {
  items: TikTokNotification[];
  typeFilter: TypeFilter;
  collapsedHosts: Set<string>;
  toggleHost: (host: string) => void;
  baselineIds: Set<number>;
  newSinceIso: string | null;
  onMarkRead: (id: number) => Promise<void>;
  onClear: (id: number) => Promise<void>;
  onClose: () => void;
}) {
  const { tz } = useTikTokTimezone();

  // Apply type filter, then group by host. Keep stable iteration:
  // host groups appear in order of their newest item.
  const groups = useMemo(() => {
    const filtered = typeFilter === 'all'
      ? items
      : items.filter((n) => n.type === typeFilter);
    const map = new Map<string, TikTokNotification[]>();
    for (const n of filtered) {
      const key = n.host_unique_id || '·';
      const arr = map.get(key);
      if (arr) arr.push(n);
      else map.set(key, [n]);
    }
    return Array.from(map.entries()).map(([host, items]) => ({
      host,
      items,
      newestTs: items[0]?.ts ? new Date(items[0].ts).getTime() : 0,
      unread: items.filter((n) => !n.read).length,
    })).sort((a, b) => b.newestTs - a.newestTs);
  }, [items, typeFilter]);

  if (groups.length === 0) {
    return (
      <p className="px-6 py-12 text-center text-sm text-gray-500">
        No notifications match this filter.
      </p>
    );
  }

  return (
    <div className="flex flex-col">
      {groups.map((g) => {
        const collapsed = collapsedHosts.has(g.host);
        return (
          <section key={g.host}>
            <HostHeader
              host={g.host}
              count={g.items.length}
              unread={g.unread}
              collapsed={collapsed}
              onToggle={() => toggleHost(g.host)}
            />
            {!collapsed && (
              <ul className="flex flex-col">
                {g.items.map((n, idx) => {
                  const isFresh = !baselineIds.has(n.id);
                  const isNewSince =
                    newSinceIso != null
                    && n.ts != null
                    && n.ts > newSinceIso
                    && !isFresh; // already-shown items, but newer than last open
                  // Insert a "new since" divider above the FIRST item
                  // newer than newSinceIso within this group.
                  const showDivider =
                    isNewSince
                    && (idx === 0 || !(g.items[idx - 1].ts != null && g.items[idx - 1].ts! > newSinceIso));
                  return (
                    <li key={n.id} className="contents">
                      {showDivider && (
                        <li className="px-4 py-1 text-[10px] uppercase tracking-wider font-mono text-primary-700 dark:text-primary-300 bg-primary-50 dark:bg-primary-500/10 border-b border-primary-200/60 dark:border-primary-500/30">
                          New since you last looked
                        </li>
                      )}
                      <NotificationItem
                        n={n}
                        tz={tz}
                        flash={isFresh}
                        onClick={async () => {
                          if (!n.read) {
                            try { await onMarkRead(n.id); } catch { /* ignore */ }
                          }
                        }}
                        onClear={async (e) => {
                          e.stopPropagation();
                          e.preventDefault();
                          try { await onClear(n.id); } catch { /* ignore */ }
                        }}
                        onClose={onClose}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

function HostHeader({
  host,
  count,
  unread,
  collapsed,
  onToggle,
}: {
  host: string;
  count: number;
  unread: number;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="sticky top-0 z-10 w-full flex items-center gap-2 px-4 py-2 bg-white border-b border-gray-200 hover:bg-gray-50 transition-colors text-left"
      aria-expanded={!collapsed}
    >
      {collapsed ? (
        <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
      ) : (
        <ChevronUp className="w-3.5 h-3.5 text-gray-400" />
      )}
      <span className="text-[11px] uppercase tracking-wider font-mono text-gray-700">
        {host === '·' ? '(no host)' : `@${host}`}
      </span>
      <span className="text-[10px] font-mono text-gray-400 tabular-nums">
        {count}
      </span>
      {unread > 0 && (
        <span className="ml-auto inline-flex items-center justify-center min-w-[18px] h-4 px-1 rounded-full bg-primary-500 text-white text-[10px] font-mono tabular-nums">
          {unread}
        </span>
      )}
    </button>
  );
}

// ─── Item row ──────────────────────────────────────────────────────

function NotificationItem({
  n,
  tz,
  flash,
  onClick,
  onClear,
  onClose,
}: {
  n: TikTokNotification;
  tz: string;
  flash: boolean;
  onClick: () => void;
  onClear: (e: React.MouseEvent) => void;
  onClose: () => void;
}) {
  // Local expand-for-detail. Tap the chevron to reveal the structured
  // payload extras (recipient, ids, raw fields). Keeps the collapsed
  // row dense; users who want more detail get it on demand.
  const [expanded, setExpanded] = useState(false);

  const TypeIcon =
    n.type === 'gift'    ? GiftIcon
    : n.type === 'comment' ? MessageSquare
    : n.type === 'join'    ? Users
    : Sparkles;
  const typeBadgeBg = {
    gift:    'bg-amber-500',
    comment: 'bg-sky-500',
    join:    'bg-emerald-500',
  }[n.type] || 'bg-gray-400';

  // Pull identity / gift / comment context out of the payload up
  // front. The watcher persists the full TikTokLive payload so all
  // these fields are available without a follow-up fetch.
  const p = (n.payload || {}) as Record<string, unknown>;
  const userBlob = (p.user as Record<string, unknown> | undefined) || {};
  const avatarUrl = (userBlob.avatar_url as string) || null;
  const identity = (userBlob.identity as IdentityBlock | undefined) || null;
  const display =
    (userBlob.nickname as string)
    || (userBlob.unique_id as string)
    || n.title;
  const seed = (display[0] || '?').toUpperCase();

  // Gift-specific extras.
  const giftIconUrl = (p.gift_icon_url as string) || null;
  const giftName = (p.gift_name as string) || null;
  const repeat = Number(p.repeat_count ?? 1) || 1;
  const perGift = Number(p.diamond_count ?? 0) || 0;
  const totalDiamonds = perGift * repeat;
  const toUser = p.to_user as
    | { user_id?: number | string; unique_id?: string; nickname?: string }
    | undefined;
  // Targeted gift = recipient explicitly set AND it isn't the
  // default-zero placeholder. In a 1v1 PK with no `to_user`, gift
  // implicitly went to the host of the broadcast.
  const targetedRecipient =
    toUser
    && toUser.user_id != null
    && String(toUser.user_id) !== '0'
    && Boolean(toUser.nickname || toUser.unique_id)
      ? (toUser.nickname || `@${(toUser.unique_id || '').replace(/^@/, '')}`)
      : null;

  // Comment-specific extra.
  const commentText = n.type === 'comment' ? (p.text as string) || n.body : null;

  // Cosmetic flags.
  const flashClass = flash
    ? 'animate-in fade-in slide-in-from-top-1 duration-300 bg-primary-50/60 dark:bg-primary-500/10'
    : '';
  const stripe = !n.read
    ? 'border-l-2 border-l-primary-500'
    : 'border-l-2 border-l-transparent';
  const titleClass = n.read
    ? 'text-gray-700'
    : 'text-gray-900 font-semibold';

  const Inner = (
    <div
      onClick={onClick}
      className={`group ${stripe} ${flashClass} px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-white/[0.04] transition-colors cursor-pointer border-b border-gray-200`}
    >
      <div className="flex items-start gap-3">
        {/* Avatar + type-icon corner badge. */}
        <div className="relative shrink-0">
          <SafeAvatar
            src={avatarUrl}
            alt=""
            size={40}
            className="ring-1 ring-gray-200 dark:ring-white/10"
            fallback={
              <span className="text-xs font-bold text-gray-500">{seed}</span>
            }
          />

          <span
            className={`absolute -bottom-0.5 -right-0.5 inline-flex items-center justify-center w-4 h-4 rounded-full text-white ring-2 ring-white dark:ring-gray-900 ${typeBadgeBg}`}
            aria-hidden
          >
            <TypeIcon className="w-2.5 h-2.5" />
          </span>
        </div>
        <div className="min-w-0 flex-1">
          {/* Headline — type tag + actor display name. The backend's
              verbose title ("X sent Heart Me ×3") was redundant with
              the per-type body block below; replacing it with a tag
              + name makes the row scannable at speed. */}
          <div className="flex items-baseline gap-2">
            <div className={`min-w-0 flex-1 inline-flex items-center gap-1.5 flex-wrap text-sm leading-snug ${titleClass}`}>
              <TypeTag type={n.type} />
              <span className="truncate">{display}</span>
            </div>
            <span className="shrink-0 text-[10px] font-mono text-gray-400 tabular-nums">
              {fmtMonthDayTime(n.ts, tz)}
            </span>
          </div>

          {/* Type-specific rich body. */}
          {n.type === 'gift' && (
            <div className="mt-1 flex items-center gap-2 flex-wrap">
              {giftIconUrl && (
                <img
                  src={giftIconUrl}
                  alt={giftName ?? ''}
                  className="w-7 h-7 rounded object-contain bg-amber-50 dark:bg-amber-500/10 ring-1 ring-amber-200 dark:ring-amber-500/30 shrink-0"
                  referrerPolicy="no-referrer"
                  loading="lazy"
                />
              )}
              <div className="text-xs font-mono text-gray-700">
                <span className="text-gray-500">{repeat}× </span>
                <span className="text-gray-900">{giftName ?? '—'}</span>
                <span className="text-gray-500"> · {perGift}💎 each</span>
              </div>
              <span className="ml-auto text-sm font-bold tabular-nums text-amber-700 dark:text-amber-300 inline-flex items-baseline gap-0.5">
                <Gem className="w-3 h-3 self-center" />
                {totalDiamonds.toLocaleString()}
              </span>
            </div>
          )}
          {n.type === 'comment' && commentText && (
            <p className="mt-1 text-sm text-gray-700 break-words whitespace-pre-wrap">
              {commentText}
            </p>
          )}

          {/* Identity badges + recipient pill + host. */}
          <div className="mt-1 flex items-center gap-2 flex-wrap text-[10px] font-mono text-gray-500">
            {identity && <TikTokUserBadges identity={identity} />}
            {targetedRecipient && n.type === 'gift' && (
              <span
                className="inline-flex items-center gap-0.5 px-1 py-px rounded bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300 text-[9px]"
                title="Gift was targeted at a specific guest / opponent"
              >
                → {targetedRecipient}
              </span>
            )}
            {n.host_unique_id && (
              <span className="inline-flex items-center gap-0.5">
                <Radio className="w-2.5 h-2.5 text-primary-500" />
                @{n.host_unique_id}
              </span>
            )}
          </div>
        </div>
        {/* Right-rail action stack — chevron (expand) + clear X. */}
        <div className="shrink-0 flex items-center gap-0.5">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              setExpanded((v) => !v);
            }}
            className="inline-flex items-center justify-center w-9 h-9 text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:hover:bg-white/10 rounded-md"
            aria-label={expanded ? 'Collapse details' : 'Expand details'}
            aria-expanded={expanded}
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
          <button
            type="button"
            onClick={onClear}
            className="inline-flex items-center justify-center w-11 h-11 -mr-2 text-gray-300 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-500/10 rounded-md"
            aria-label="Clear notification"
            title="Clear"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Expanded detail panel — raw extras pulled from payload. */}
      {expanded && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="mt-2 ml-13 pl-3 border-l-2 border-gray-200 text-[11px] font-mono text-gray-600 space-y-1"
        >
          {n.type === 'gift' && (
            <>
              <DetailRow label="Gift id" value={String(p.gift_id ?? '—')} />
              <DetailRow
                label="Streak"
                value={p.streakable ? 'streakable' : 'one-shot'}
              />
              {targetedRecipient && (
                <DetailRow label="Recipient" value={targetedRecipient} />
              )}
              {!targetedRecipient && (
                <DetailRow
                  label="Recipient"
                  value="Host (default)"
                  hint="The lib didn't surface to_user — typical for solo lives. The gift went to the broadcast host."
                />
              )}
            </>
          )}
          {(identity?.member_level ?? 0) > 0 && (
            <DetailRow
              label="Member level"
              value={String(identity?.member_level)}
              hint="The gifter's tier inside this host's room"
            />
          )}
          {(identity?.fan_ticket_count ?? 0) > 0 && (
            <DetailRow
              label="Fan tickets"
              value={String(identity?.fan_ticket_count)}
            />
          )}
          {n.user_id && (
            <DetailRow
              label="User id"
              value={n.user_id}
              copyable
            />
          )}
          {(p.message_id != null) && (
            <DetailRow
              label="Message id"
              value={String(p.message_id)}
              copyable
            />
          )}
          {(p.room_id != null || (n.payload?.['room_id'] != null)) && (
            <DetailRow
              label="Room id"
              value={String(p.room_id ?? n.payload?.['room_id'] ?? '')}
              copyable
            />
          )}
        </div>
      )}
    </div>
  );

  return n.host_unique_id ? (
    <Link
      to="/admin/tiktok/$handle"
      params={{ handle: n.host_unique_id }}
      onClick={onClose}
      className="block"
    >
      {Inner}
    </Link>
  ) : (
    Inner
  );
}

function TypeTag({ type }: { type: string }) {
  // Compact type pill rendered inline in the row headline. Mirrors
  // the corner-badge color on the avatar so the eye reads them as
  // the same axis (type), not two unrelated chips.
  const meta: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    gift: {
      label: 'GIFT',
      cls: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
      icon: <GiftIcon className="w-2.5 h-2.5" />,
    },
    comment: {
      label: 'COMMENT',
      cls: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300',
      icon: <MessageSquare className="w-2.5 h-2.5" />,
    },
    join: {
      label: 'JOIN',
      cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
      icon: <Users className="w-2.5 h-2.5" />,
    },
  };
  const m = meta[type] ?? {
    label: type.toUpperCase(),
    cls: 'bg-gray-100 text-gray-700',
    icon: <Sparkles className="w-2.5 h-2.5" />,
  };
  return (
    <span
      className={`shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded font-mono text-[9px] uppercase tracking-wider ${m.cls}`}
    >
      {m.icon}
      {m.label}
    </span>
  );
}

function DetailRow({
  label,
  value,
  copyable,
  hint,
}: {
  label: string;
  value: string;
  copyable?: boolean;
  hint?: string;
}) {
  return (
    <div className="flex items-baseline gap-2" title={hint}>
      <span className="shrink-0 w-24 text-[10px] uppercase tracking-wider text-gray-400">
        {label}
      </span>
      <span
        className={`min-w-0 flex-1 truncate text-gray-700 ${copyable ? 'select-all' : ''}`}
      >
        {value}
      </span>
    </div>
  );
}

// ─── Empty state ───────────────────────────────────────────────────

function EmptyState({ loading }: { loading: boolean }) {
  if (loading) {
    return (
      <div className="py-16 text-center text-sm text-gray-500">
        <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
        Loading notifications…
      </div>
    );
  }
  return (
    <div className="py-16 px-6 text-center">
      <Bell className="w-10 h-10 text-gray-300 mx-auto mb-3" />
      <p className="text-sm text-gray-500">No notifications yet.</p>
      <p className="mt-1 text-xs text-gray-400">
        Favourite-gifter alerts and system events will land here.
      </p>
    </div>
  );
}

// ─── Helpers ───────────────────────────────────────────────────────

function countByType(items: TikTokNotification[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const n of items) {
    out[n.type] = (out[n.type] || 0) + 1;
  }
  return out;
}

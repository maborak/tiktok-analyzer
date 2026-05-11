/**
 * useNotifications — central notification stream hook.
 *
 * Source of truth: backend `tiktok_notifications` table. The worker
 * writes rows whenever a favourite gifter triggers an enabled event
 * type, so history is intact regardless of whether any browser tab
 * was open at the time. localStorage caches the latest fetched page
 * so the bell badge has a number on first paint.
 *
 * Refresh strategy: refetch on mount, on window focus, every 30 s
 * while the tab is focused, and immediately whenever the favourites
 * watcher fires (it dispatches `tiktok:notifications:refresh` from
 * the WS callback so the badge ticks the same instant as the toast).
 */

import { useCallback, useEffect, useState } from 'react';

import {
  type TikTokNotification,
  tiktokApi,
} from '@admin/services/tiktok';

const STORAGE_KEY = 'tiktok:notifications:v1';
const UNREAD_KEY = 'tiktok:notifications:unread:v1';
const LAST_OPENED_KEY = 'tiktok:notifications:lastOpened:v1';
const MAX_LOCAL_ITEMS = 500;

// ── localStorage helpers ───────────────────────────────────────────

function readCache(): TikTokNotification[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as TikTokNotification[]) : [];
  } catch {
    return [];
  }
}

function writeCache(items: TikTokNotification[]): void {
  if (typeof window === 'undefined') return;
  try {
    // FIFO eviction so a long-running session doesn't blow the
    // ~5MB localStorage budget.
    const trimmed = items.slice(0, MAX_LOCAL_ITEMS);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    /* quota / private mode — silent. The server is the source of truth. */
  }
}

function readUnreadCache(): number {
  if (typeof window === 'undefined') return 0;
  try {
    const raw = window.localStorage.getItem(UNREAD_KEY);
    return raw ? Math.max(0, parseInt(raw, 10) || 0) : 0;
  } catch {
    return 0;
  }
}

function writeUnreadCache(n: number): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(UNREAD_KEY, String(Math.max(0, n)));
  } catch {
    /* ignore */
  }
}

/** Reads the ISO timestamp of the last time the user opened the
 *  drawer. Used to render the "new since you last looked"
 *  separator. Returns null on first-ever open. */
function readLastOpened(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(LAST_OPENED_KEY);
  } catch {
    return null;
  }
}

function writeLastOpened(iso: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(LAST_OPENED_KEY, iso);
  } catch {
    /* ignore */
  }
}

// ── Hook ───────────────────────────────────────────────────────────

interface UseNotificationsResult {
  items: TikTokNotification[];
  unreadCount: number;
  loading: boolean;
  error: string | null;
  /** Approximate "is the backend stream healthy" signal. True when
   *  the last poll succeeded recently; false when the most recent
   *  attempt failed or has been silent past the poll interval.
   *  Drives the "● live" dot in the drawer header. */
  connected: boolean;
  /** ISO of the last time the drawer was opened. Items strictly
   *  newer than this are flagged "new since you last looked." */
  lastOpenedAt: string | null;
  /** Stamp the current time so the "new" divider re-baselines after
   *  the user has actually looked. Called by the drawer on open. */
  markOpenedNow: () => void;
  refetch: () => Promise<void>;
  markRead: (id: number) => Promise<void>;
  markAllRead: () => Promise<void>;
  clear: (id: number) => Promise<void>;
  clearAll: () => Promise<void>;
}

export function useNotifications(): UseNotificationsResult {
  // Hydrate immediately from cache so the bell badge has a number on
  // first paint instead of zero-then-flicker.
  const [items, setItems] = useState<TikTokNotification[]>(() => readCache());
  const [unreadCount, setUnreadCount] = useState<number>(() => readUnreadCache());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastOpenedAt, setLastOpenedAt] = useState<string | null>(() => readLastOpened());

  // Persist on every items/unread change.
  useEffect(() => {
    writeCache(items);
  }, [items]);
  useEffect(() => {
    writeUnreadCache(unreadCount);
  }, [unreadCount]);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, count] = await Promise.all([
        tiktokApi.listNotifications({ limit: 200 }),
        tiktokApi.unreadNotificationsCount(),
      ]);
      setItems(list);
      setUnreadCount(count.unread);
      setConnected(true);
    } catch (e) {
      setError((e as Error).message || 'Failed to load notifications');
      setConnected(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const markOpenedNow = useCallback(() => {
    const iso = new Date().toISOString();
    writeLastOpened(iso);
    setLastOpenedAt(iso);
  }, []);

  // Initial load + refresh on focus + on the watcher's "something
  // just happened" prod + every 30s while focused.
  useEffect(() => {
    refetch();
    const onFocus = () => refetch();
    const onPoke = () => refetch();
    window.addEventListener('focus', onFocus);
    window.addEventListener('tiktok:notifications:refresh', onPoke);
    let interval: ReturnType<typeof setInterval> | null = null;
    const startPolling = () => {
      if (interval != null) return;
      interval = setInterval(() => {
        if (document.visibilityState === 'visible') refetch();
      }, 30_000);
    };
    const stopPolling = () => {
      if (interval == null) return;
      clearInterval(interval);
      interval = null;
    };
    if (document.visibilityState === 'visible') startPolling();
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        startPolling();
        refetch();
      } else {
        stopPolling();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('tiktok:notifications:refresh', onPoke);
      document.removeEventListener('visibilitychange', onVisibility);
      stopPolling();
    };
  }, [refetch]);

  const markRead = useCallback(async (id: number) => {
    setItems((prev) =>
      prev.map((n) => (n.id === id && !n.read ? { ...n, read: true } : n)),
    );
    setUnreadCount((n) => Math.max(0, n - 1));
    if (id < 0) return; // optimistic temp id; nothing to PATCH yet
    try {
      await tiktokApi.markNotificationRead(id, true);
    } catch (e) {
      // Roll back on error.
      setItems((prev) =>
        prev.map((n) => (n.id === id ? { ...n, read: false } : n)),
      );
      setUnreadCount((n) => n + 1);
      throw e;
    }
  }, []);

  const markAllRead = useCallback(async () => {
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    setUnreadCount(0);
    try {
      await tiktokApi.markAllNotificationsRead();
    } catch (e) {
      // Refetch to recover the truth.
      await refetch();
      throw e;
    }
  }, [refetch]);

  const clear = useCallback(async (id: number) => {
    setItems((prev) => prev.filter((n) => n.id !== id));
    if (id < 0) return; // optimistic temp id; nothing to DELETE yet
    try {
      await tiktokApi.clearNotification(id);
    } catch (e) {
      await refetch();
      throw e;
    }
  }, [refetch]);

  const clearAll = useCallback(async () => {
    setItems([]);
    setUnreadCount(0);
    try {
      await tiktokApi.clearAllNotifications();
    } catch (e) {
      await refetch();
      throw e;
    }
  }, [refetch]);

  return {
    items,
    unreadCount,
    loading,
    error,
    connected,
    lastOpenedAt,
    markOpenedNow,
    refetch,
    markRead,
    markAllRead,
    clear,
    clearAll,
  };
}

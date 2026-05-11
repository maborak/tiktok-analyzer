/**
 * Favourite-gifter alert watcher.
 *
 * Mounted once at the `/admin/tiktok/...` route layout — stays alive
 * across page navigations between Lives, the live-detail page,
 * Dashboard, etc. so the user gets a toast whenever a favourited
 * viewer gifts in any tracked broadcast.
 *
 * Subscribes to the WebSocket with `handles: '*'` (every tracked
 * creator) and filters incoming `gift` events against the favourites
 * set. The set is fetched on mount and refreshed on the
 * `tiktok:favorites-changed` custom event (fired by the
 * Add/Remove favourite buttons in the gifter modals).
 *
 * Renders nothing — pure side-effect component.
 */

import { useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';

import {
  type TikTokWsEvent,
  openTikTokWebSocket,
  tiktokApi,
} from '@admin/services/tiktok';

interface NotifyConfig {
  notify_gift: boolean;
  notify_comment: boolean;
  notify_join: boolean;
}

// Verbose breadcrumbs so the admin can see in DevTools why an alert
// did or didn't fire. Cheap (only logs on favourite hits + load
// transitions); production-safe.
const DEBUG = true;
function dbg(...args: unknown[]) {
  if (DEBUG) console.info('[favourites-watcher]', ...args);
}

export function TikTokFavoritesWatcher() {
  // Map of user_id → which event types should fire a toast. The WS
  // callback reads this on every event; held in a ref so we can
  // refresh the map without reconnecting the socket.
  const notifyMapRef = useRef<Map<string, NotifyConfig>>(new Map());
  const [refetchTick, setRefetchTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    tiktokApi
      .listFavoriteGifterNotifyConfig()
      .then((r) => {
        if (cancelled) return;
        const m = new Map<string, NotifyConfig>();
        for (const row of r.items) {
          m.set(row.user_id, {
            notify_gift: row.notify_gift,
            notify_comment: row.notify_comment,
            notify_join: row.notify_join,
          });
        }
        notifyMapRef.current = m;
        dbg(`favourites loaded — ${m.size} entries`,
          Array.from(m.entries()).map(([uid, c]) => ({
            user_id: uid,
            gift: c.notify_gift, comment: c.notify_comment, join: c.notify_join,
          })),
        );
      })
      .catch((e) => {
        dbg('favourites load failed', e);
        /* keep whatever map we already had */
      });
    const onChanged = () => setRefetchTick((n) => n + 1);
    window.addEventListener('tiktok:favorites-changed', onChanged);
    return () => {
      cancelled = true;
      window.removeEventListener('tiktok:favorites-changed', onChanged);
    };
  }, [refetchTick]);

  // Single WS for the entire admin shell. Subscribed to `*` so the
  // watcher sees every creator's stream regardless of page.
  useEffect(() => {
    let opened = false;
    const ws = openTikTokWebSocket(
      (msg: TikTokWsEvent) => {
        if (!opened) {
          // First message ever received — confirms the WS is wired
          // through and the backend is sending events.
          opened = true;
          dbg('WS first message received', { type: msg.type, host: msg.unique_id });
        }
        if (!msg.user_id) return;
        const cfg = notifyMapRef.current.get(String(msg.user_id));
        if (!cfg) return; // not a favourite — silent skip (would log every event otherwise)
        // Per-event-type opt-in. Log every favourite hit so the
        // admin can see in DevTools whether the gate (cfg flags vs
        // event type) is letting the event through.
        const allowed =
          (msg.type === 'gift' && cfg.notify_gift) ||
          (msg.type === 'comment' && cfg.notify_comment) ||
          (msg.type === 'join' && cfg.notify_join);
        dbg('favourite-actor event', {
          type: msg.type,
          user_id: msg.user_id,
          host: msg.unique_id,
          notify_cfg: cfg,
          willToast: allowed,
        });
        if (!allowed) return;
        const p = (msg.payload || {}) as Record<string, unknown>;
        const u =
          (p.user as { nickname?: string; unique_id?: string } | undefined) ||
          {};
        const display = u.nickname || u.unique_id || `user ${msg.user_id}`;
        let summary = '';
        if (msg.type === 'gift') {
          const gift = (p.gift_name as string) || 'a gift';
          const repeat = Number(p.repeat_count ?? 1) || 1;
          const diamonds = (Number(p.diamond_count ?? 0) || 0) * repeat;
          summary = `⭐ ${display} sent ${gift}${repeat > 1 ? ` ×${repeat}` : ''} (${diamonds.toLocaleString()}💎)`;
        } else if (msg.type === 'comment') {
          const text = String(p.text ?? '').slice(0, 80);
          summary = `💬 ${display}: ${text}`;
        } else if (msg.type === 'join') {
          summary = `👋 ${display} joined`;
        } else {
          return;
        }
        dbg('toast firing', summary);
        // Toast is the transient in-tab feedback. Notification
        // persistence lives in the *backend* now (tiktok_service
        // writes a `tiktok_notifications` row whenever a favourite
        // triggers an enabled event type) so history survives
        // browser-closed periods.
        toast.success(`${summary} in @${msg.unique_id}`, { duration: 6000 });
        // Tell the bell hook to refetch — the user wants the badge
        // to update *now* without waiting for the next 30s poll.
        window.dispatchEvent(new CustomEvent('tiktok:notifications:refresh'));
      },
      (err) => dbg('WS error', err),
      { handles: '*' },
    );
    dbg('WS open() called — subscribed to handles=*');
    ws.addEventListener('open', () => dbg('WS open event'));
    ws.addEventListener('close', (ev) => dbg('WS close event', ev.code, ev.reason));
    return () => {
      try { ws.close(); } catch { /* ignore */ }
    };
  }, []);

  return null;
}

import { memo, useEffect, useState } from 'react';
import { Loader2, Users } from 'lucide-react';

import { type TikTokRoomRecipient } from '@admin/services/tiktok';
import { useTikTokApi } from '@admin/contexts/TikTokApiContext';

interface Props {
  roomId: string | null;
  range: { since?: string; until?: string };
  refreshKey: number;
  /** Reuse the live-page's gifter-modal handler — clicking a recipient
   *  row opens that user's gift / comment history (same UX as the top
   *  gifters table). */
  onSelectUser: (g: {
    userId: string | null;
    uniqueId: string | null;
    nickname: string | null;
    diamonds: number;
    gifts: number;
    comments: number;
    tab: 'gifts' | 'comments';
  }) => void;
}

function TikTokRoomRecipientsCardImpl({
  roomId,
  range,
  refreshKey,
  onSelectUser,
}: Props) {
  const tiktokApi = useTikTokApi();
  const [items, setItems] = useState<TikTokRoomRecipient[]>([]);
  const [totalDiamonds, setTotalDiamonds] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!roomId) {
      setItems([]);
      setTotalDiamonds(0);
      return;
    }
    let cancelled = false;
    setLoading(true);
    tiktokApi
      .getRoomRecipients(roomId, {
        since: range.since,
        until: range.until,
        limit: 20,
      })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotalDiamonds(res.total_diamonds);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTotalDiamonds(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [roomId, range.since, range.until, refreshKey]);

  // Auto-hide for solo broadcasts (no recipient data) so the live-detail
  // page doesn't grow an empty card. The TikTokLive lib only emits a
  // distinct to_user when the gifter targets a specific anchor (multi-
  // guest live or PK), so an empty list here means there's nothing
  // useful to display.
  if (!loading && items.length === 0) return null;

  return (
    <section className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="auth-mono-label flex items-center gap-1.5">
          <Users className="w-3.5 h-3.5 text-amber-500" />
          Diamonds by recipient
          {items.length > 0 && (
            <span className="ml-1 text-[10px] font-mono text-gray-500">
              ({items.length})
            </span>
          )}
        </h2>
        <span className="text-[11px] font-mono text-gray-500">
          {totalDiamonds.toLocaleString()} 💎 attributed
        </span>
      </div>

      {loading && items.length === 0 ? (
        <div className="py-4 text-center text-sm text-gray-500">
          <Loader2 className="w-4 h-4 inline mr-2 animate-spin" />
          Loading recipients…
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((r) => {
            const pct =
              totalDiamonds > 0 ? (r.diamonds / totalDiamonds) * 100 : 0;
            return (
              <button
                key={r.user_id ?? r.unique_id ?? Math.random()}
                type="button"
                onClick={() =>
                  onSelectUser({
                    userId: r.user_id,
                    uniqueId: r.unique_id,
                    nickname: r.nickname,
                    diamonds: r.diamonds,
                    gifts: r.gifts,
                    comments: 0,
                    tab: 'gifts',
                  })
                }
                className="block w-full text-left rounded hover:bg-gray-50 px-2 py-1.5 transition-colors"
                title="Open this user's gift history"
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-sm truncate">
                    <span className="font-medium">{r.nickname ?? '—'}</span>{' '}
                    {r.unique_id && (
                      <span className="text-[11px] font-mono text-gray-500">
                        @{r.unique_id}
                      </span>
                    )}
                  </span>
                  <span className="font-mono text-xs tabular-nums text-amber-700 dark:text-amber-300 whitespace-nowrap">
                    {r.diamonds.toLocaleString()} 💎
                    <span className="ml-1.5 text-gray-500">
                      ({pct.toFixed(1)}%)
                    </span>
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden dark:bg-gray-100/30">
                  <div
                    className="h-full bg-amber-500 transition-[width] duration-500"
                    style={{ width: `${Math.min(100, pct).toFixed(2)}%` }}
                  />
                </div>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

/** Memoized — shielded from the live-detail page's per-WS-event
 *  reconcile cascade. */
export const TikTokRoomRecipientsCard = memo(TikTokRoomRecipientsCardImpl);

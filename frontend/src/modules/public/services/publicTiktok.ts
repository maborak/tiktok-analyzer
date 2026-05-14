import { apiRequest } from '@/api/client';
import type {
  TikTokSubscription,
  TikTokLiveSummary,
  TikTokRoom,
  TikTokRoomStats,
  TikTokRoomGifters,
  TikTokRoomRecipients,
  TikTokMatch,
  TikTokMatchScoreFrame,
  TikTokMatchGiftersBySide,
  TikTokMatchHeadToHeadRow,
  TikTokH2HCommonGifter,
  TikTokEvent,
  TikTokUserMatchesResponse,
  PublicLive,
} from '@admin';

// Re-export so consumers in this module don't need to reach into
// `@admin/*` for the shared shape.
export type { PublicLive } from '@admin';

const BASE = '/public/tiktok';

/** Widened wire shape for `/public/tiktok/lives`.
 *
 *  The endpoint is in the middle of a rollout from the legacy thin
 *  `PublicLive[]` shape to a richer payload that mirrors the admin
 *  page's per-handle `{subscription, summary}` pair (so the same
 *  `SubscriptionCard` can render both pages). We accept ALL three
 *  shapes here — the public-page normalizer picks the right branch:
 *
 *    A) `{items: [{subscription, summary}, ...]}` — wide nested
 *    B) `{subscriptions: [...], summaries: {<handle>: ...}}` — wide split
 *    C) `{items: [PublicLive, ...]}` — legacy thin
 *
 *  All three carry operator-only fields stripped server-side. */
export type PublicLivesPayload =
  | { items: Array<{ subscription: TikTokSubscription; summary: TikTokLiveSummary }> }
  | { subscriptions: TikTokSubscription[]; summaries: Record<string, TikTokLiveSummary> }
  | { items: PublicLive[] };

/** Per-host summary returned by `/public/tiktok/lives/{handle}`. Same
 *  shape as the live-detail page's per-handle slice on the admin lives
 *  endpoint — operator-only fields stripped server-side. */
export interface PublicHostSummary {
  subscription: TikTokSubscription;
  summary: TikTokLiveSummary;
}

/** Unauthenticated client for the public lives view.
 *
 *  `apiRequest` silently omits the `Authorization` header when there's
 *  no JWT in storage, so calls here work for anonymous visitors. The
 *  backend strips operator-only fields server-side — never request
 *  any other `/admin/*` endpoint from the public page.
 *
 *  Method shape mirrors `tiktokApi` (admin) one-for-one for the read
 *  endpoints the public live-detail page consumes. URL differs
 *  (`/public/tiktok/...` vs `/admin/tiktok/...`); response types are
 *  identical so the shared `TikTokLiveDetail` component can switch
 *  namespaces via context without any branching. */
export const publicTiktokApi = {
  listLives(opts?: { tz?: string }): Promise<PublicLivesPayload> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives`,
      // Active TZ pill selection — backend uses it to bucket per-host
      // week_calendar by calendar day in the viewer's zone.
      params: opts?.tz ? { tz: opts.tz } : undefined,
    });
  },

  /** Fetch a single host's subscription record. Public endpoint
   *  returns `{subscription, summary}`; we unwrap to the subscription
   *  alone so callers can use the same shape on both namespaces. Use
   *  `getLiveByHandleWithSummary` for the original wide shape. */
  getLiveByHandle(handle: string): Promise<TikTokSubscription> {
    return apiRequest<PublicHostSummary>({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}`,
    }).then((row) => row.subscription);
  },

  /** Same endpoint, original `{subscription, summary}` shape — kept
   *  for callers that need the per-host summary alongside the
   *  subscription (e.g. a future header card on the detail page). */
  getLiveByHandleWithSummary(handle: string): Promise<PublicHostSummary> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}`,
    });
  },

  /** Three-state visibility probe used by the `/lives/:handle` route
   *  guard. Returns `public` (render detail page), `private` (show
   *  "currently private" message), or `not_found` (show "no tracked
   *  live" message). Always resolves — never throws — so the guard
   *  doesn't need a try/catch. This is the ONLY public endpoint that
   *  differentiates "exists but private" from "doesn't exist"; every
   *  data endpoint still 404s opaquely. */
  getLiveStatus(handle: string): Promise<{ status: 'public' | 'private' | 'not_found'; handle: string }> {
    return apiRequest<{ status: 'public' | 'private' | 'not_found'; handle: string }>({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/status`,
    }).catch(() => ({ status: 'not_found' as const, handle }));
  },

  // ── Rooms / calendar ─────────────────────────────────────────────

  getHostCalendar(
    handle: string,
    weeks = 26,
    tz: string = 'UTC',
  ): Promise<{
    host: string;
    start_date: string;
    end_date: string;
    weeks: number;
    tz?: string;
    cells: Array<{
      date: string;
      rooms: number;
      duration_minutes: number;
      diamonds: number;
      matches: number;
    }>;
  }> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/calendar`,
      params: { weeks, tz },
    });
  },

  listHostRooms(handle: string, limit = 50): Promise<TikTokRoom[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/rooms`,
      params: { limit },
    });
  },

  getRoomStats(
    roomId: string,
    opts?: {
      window_minutes?: number;
      bucket_seconds?: number;
      since?: string;
      until?: string;
    },
  ): Promise<TikTokRoomStats> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/rooms/${roomId}/stats`,
      params: opts,
    });
  },

  getRoomGifters(
    roomId: string,
    opts?: {
      since?: string;
      until?: string;
      q?: string;
      limit?: number;
      offset?: number;
      extra_room_ids?: string[];
    },
  ): Promise<TikTokRoomGifters> {
    const { extra_room_ids, ...rest } = opts ?? {};
    return apiRequest({
      method: 'GET',
      url: `${BASE}/rooms/${roomId}/gifters`,
      params: {
        ...rest,
        ...(extra_room_ids && extra_room_ids.length > 0
          ? { room_ids: extra_room_ids.join(',') }
          : {}),
      },
    });
  },

  getRoomRecipients(
    roomId: string,
    opts?: {
      since?: string;
      until?: string;
      limit?: number;
    },
  ): Promise<TikTokRoomRecipients> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/rooms/${roomId}/recipients`,
      params: opts,
    });
  },

  /** Public mirror of the admin cross-live gifters endpoint. The
   *  backend still gates on `is_public` for the queried host. */
  getRoomCrossLiveGifters(
    handle: string,
    opts?: {
      min_other_hosts?: number;
      q?: string;
      limit?: number;
      offset?: number;
    },
  ): Promise<import('@admin/services/tiktok').TikTokCrossLiveGiftersPage> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/cross-live-gifters`,
      params: opts,
    });
  },

  /** Public mirror of the admin common-gifter detail endpoint. Same
   *  deep-analysis payload — identity, cross-host totals, per-host
   *  breakdown, momentum / loyalty / tier mix / heatmap. Used by the
   *  Profile tab of the unified gifter modal on the public page. */
  getCommonGifterDetail(
    userId: string,
  ): Promise<import('@admin/services/tiktok').TikTokCommonGifterDetail> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/common-gifters/${encodeURIComponent(userId)}/detail`,
    });
  },

  getAggregatedBuckets(opts: {
    room_ids: string[];
    since: string;
    until: string;
    bucket_seconds?: number;
  }): Promise<{
    starts: string[];
    by_type: Record<string, number[]>;
    diamonds: number[];
    diamonds_total: number;
    bucket_seconds?: number;
  }> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/buckets/aggregated`,
      params: {
        room_ids: opts.room_ids.join(','),
        since: opts.since,
        until: opts.until,
        bucket_seconds: opts.bucket_seconds,
      },
    });
  },

  // ── Matches ──────────────────────────────────────────────────────

  listMatches(opts?: {
    handle?: string;
    room_id?: string;
    limit?: number;
  }): Promise<TikTokMatch[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches`,
      params: opts,
    });
  },

  listMatchesForRoom(roomId: string, limit = 50): Promise<TikTokMatch[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches`,
      params: { room_id: roomId, limit },
    });
  },

  getMatch(matchId: number): Promise<TikTokMatch> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches/${matchId}`,
    });
  },

  getMatchScoreTimeline(matchId: number): Promise<TikTokMatchScoreFrame[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches/${matchId}/score_timeline`,
    });
  },

  getMatchGiftersBySide(matchId: number): Promise<TikTokMatchGiftersBySide> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches/${matchId}/gifters_by_side`,
    });
  },

  getMatchHeadToHead(
    matchId: number,
    opts: { limit?: number } = {},
  ): Promise<TikTokMatchHeadToHeadRow[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches/${matchId}/head_to_head`,
      params: opts,
    });
  },

  getH2HCommonGifters(
    matchId: number,
    opts: { min_battles?: number; limit?: number } = {},
  ): Promise<TikTokH2HCommonGifter[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches/${matchId}/h2h_common_gifters`,
      params: opts,
    });
  },

  // ── Event search / count ─────────────────────────────────────────

  searchEvents(opts: {
    handle?: string;
    room_id?: string;
    room_ids?: string[];
    user_id?: string;
    match_id?: number;
    type?: string;
    since?: string;
    until?: string;
    q?: string;
    to_user_id?: string;
    min_diamonds?: number;
    limit?: number;
    before_id?: string;
    offset?: number;
  }): Promise<TikTokEvent[]> {
    // The public endpoint REQUIRES `room_ids` (the admin one allows the
    // singular `room_id` or omitting both). Many callers built around
    // the admin shape pass only `room_id` — promote it to `room_ids`
    // here so the public namespace receives the parameter shape it
    // demands. Admin path is unaffected (different client).
    const { room_id, room_ids, ...rest } = opts;
    const effectiveRoomIds =
      room_ids && room_ids.length > 0
        ? room_ids
        : room_id
          ? [room_id]
          : undefined;
    return apiRequest({
      method: 'GET',
      url: `${BASE}/events/search`,
      params: {
        ...rest,
        ...(effectiveRoomIds
          ? { room_ids: effectiveRoomIds.join(',') }
          : {}),
      },
    });
  },

  countEvents(opts: {
    handle?: string;
    room_id?: string;
    room_ids?: string[];
    user_id?: string;
    match_id?: number;
    type?: string;
    since?: string;
    until?: string;
    q?: string;
    to_user_id?: string;
    min_diamonds?: number;
  }): Promise<{ total: number }> {
    // See searchEvents — same room_id → room_ids defensive promotion.
    const { room_id, room_ids, ...rest } = opts;
    const effectiveRoomIds =
      room_ids && room_ids.length > 0
        ? room_ids
        : room_id
          ? [room_id]
          : undefined;
    return apiRequest({
      method: 'GET',
      url: `${BASE}/events/count`,
      params: {
        ...rest,
        ...(effectiveRoomIds
          ? { room_ids: effectiveRoomIds.join(',') }
          : {}),
      },
    });
  },

  // ── User-scoped lookups (gifter modal) ───────────────────────────

  listUserMatches(opts: {
    userId: string;
    roomIds?: string[];
    since?: string;
    until?: string;
    limit?: number;
    offset?: number;
  }): Promise<TikTokUserMatchesResponse> {
    const params: Record<string, string | number> = {
      limit: opts.limit ?? 25,
      offset: opts.offset ?? 0,
    };
    if (opts.roomIds && opts.roomIds.length > 0) {
      params.room_ids = opts.roomIds.join(',');
    }
    if (opts.since) params.since = opts.since;
    if (opts.until) params.until = opts.until;
    return apiRequest({
      method: 'GET',
      url: `${BASE}/users/${encodeURIComponent(opts.userId)}/matches`,
      params,
    });
  },

  /** Public mirror of the admin per-(user, host) daily-series
   *  endpoint. The backend gates the host on `is_public=True`. */
  getUserHostDailySeries(opts: {
    userId: string;
    handle: string;
    days?: number;
  }): Promise<Array<{ day: string; diamonds: number; gifts: number }>> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/users/${encodeURIComponent(opts.userId)}/host-daily-series`,
      params: {
        handle: opts.handle.replace(/^@/, ''),
        days: opts.days ?? 30,
      },
    });
  },
};

export type PublicTikTokApi = typeof publicTiktokApi;

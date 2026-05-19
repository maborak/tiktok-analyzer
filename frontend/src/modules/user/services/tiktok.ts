/**
 * User-facing TikTok monitoring API client.
 *
 * Mirrors the admin `tiktokApi` shape but talks to /tiktok/* (NOT
 * /admin/tiktok/*) — the user-facing namespace introduced 2026-05-18
 * as part of the per-user monetised monitoring pivot. Every endpoint
 * is ownership-gated at the backend: a regular user only ever sees
 * subscriptions whose `owner_user_id = current_user.id`.
 *
 * Adding a monitor costs 1 credit. Removing within 24 h refunds the
 * credit. The `add` call surfaces HTTP 402 (insufficient credits) +
 * HTTP 409 (handle already monitored by another user) so the UI can
 * render the correct message without a generic "something went wrong".
 */

import { apiRequest } from '@/api/client';

const BASE = '/tiktok';

export interface UserTikTokSubscription {
  // The DB row, returned as a plain dict from the user-route layer.
  unique_id: string;
  enabled: boolean;
  is_public: boolean;
  owner_user_id: number;
  added_at: string | null;
  // Public profile fields (cached on tiktok_subscriptions, refreshed
  // periodically by the worker). Nullable on a freshly-added handle
  // until the first refresh lands.
  nickname?: string | null;
  avatar_url?: string | null;
  follower_count?: number | null;
  bio?: string | null;
  verified?: boolean | null;
  is_live?: boolean | null;
  current_room_id?: string | number | null;
}

export interface AddMonitorResponse {
  sub: UserTikTokSubscription;
  credit_debited: boolean;  // false on idempotent re-add of own handle
}

export interface RemoveMonitorResponse {
  deleted: boolean;
  refunded: boolean;
}

export const userTikTokApi = {
  /** Current credit balance. Drives the "You have N credits" UI. */
  async getCredits(): Promise<{ balance: number }> {
    return apiRequest({ method: 'GET', url: `${BASE}/credits` });
  },

  /** List the authenticated user's monitored handles. */
  async listMyLives(): Promise<UserTikTokSubscription[]> {
    return apiRequest({ method: 'GET', url: `${BASE}/lives` });
  },

  /**
   * Rich card-grid payload: `{subs, summary, totals}`. Mirrors the
   * admin `/admin/tiktok/lives/bundle` shape so the grid components
   * can be data-driven (same rendering, ownership-scoped data).
   * `totals` is `null` on the user surface by design — admin's
   * totals are install-wide and would leak other users' activity.
   */
  async getLivesBundle(opts?: { tz?: string }): Promise<{
    subs: UserTikTokSubscription[];
    summary: Record<string, Record<string, unknown>>;
    totals: null;
  }> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/bundle`,
      params: opts?.tz ? { tz: opts.tz } : undefined,
    });
  },

  /**
   * Add a TikTok handle to the authenticated user's monitor list.
   * Throws on 402 (insufficient credits) and 409 (handle already
   * monitored by another user) — the caller should inspect
   * `error.response.status` to render the right message.
   */
  async addMonitor(
    username: string,
    profile?: Record<string, unknown> | null,
  ): Promise<AddMonitorResponse> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/lives`,
      data: { username, profile: profile ?? null },
    });
  },

  /** Remove a monitor. Refunds the credit if removed within 24 h. */
  async removeMonitor(handle: string): Promise<RemoveMonitorResponse> {
    return apiRequest({
      method: 'DELETE',
      url: `${BASE}/lives/${encodeURIComponent(handle)}`,
    });
  },

  /** Detail (sub + summary) for one owned handle. 404 if not owner. */
  async getMyLive(
    handle: string,
  ): Promise<{ sub: UserTikTokSubscription; summary: Record<string, unknown> }> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}`,
    });
  },

  /** Heatmap data — same shape as admin calendar. */
  async getMyLiveCalendar(
    handle: string,
    weeks: number = 26,
    tz: string = 'UTC',
  ): Promise<unknown> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/calendar`,
      params: { weeks, tz },
    });
  },

  /** Rooms list for one owned handle. */
  async getMyLiveRooms(
    handle: string,
    limit: number = 50,
  ): Promise<unknown[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/rooms`,
      params: { limit },
    });
  },

  /** Per-room stats. 404 if the room's host isn't owned by the user. */
  async getMyRoomStats(
    roomId: number | string,
    opts: { window_minutes?: number; bucket_seconds?: number } = {},
  ): Promise<unknown> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/rooms/${roomId}/stats`,
      params: opts,
    });
  },
};

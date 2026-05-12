import { apiRequest } from '@/api/client';
import { apiConfig } from '@/config/env';
import { tiktokTelemetry } from '@admin/services/tiktokTelemetry';

// ─── Types ──────────────────────────────────────────────────────────────────

export type SubscriptionState =
  | 'DISABLED'
  | 'DISCONNECTED'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'LIVE_ENDED'
  | 'ERROR';

// Note: room_id, user_id and event id are 64-bit BigInts on TikTok's side.
// Values exceed Number.MAX_SAFE_INTEGER (2^53), so the wire format is
// string-typed. Pass them through verbatim — never coerce to number.

export interface TikTokSubscription {
  unique_id: string;
  enabled: boolean;
  state: SubscriptionState;
  room_id: string | null;
  is_connected: boolean;
  created_at: string | null;
  updated_at: string | null;
  // Cached public-profile fields (refreshed by backend ~1h cadence).
  profile_user_id?: string | null;
  nickname?: string | null;
  avatar_url?: string | null;
  bio?: string | null;
  verified?: boolean | null;
  follower_count?: number | null;
  following_count?: number | null;
  profile_refreshed_at?: string | null;
  profile_error?: string | null;
  // Centralized live-status cache. Updated by the worker's scraper
  // task; surfaced here for the live-detail page's live indicator.
  is_live?: boolean | null;
  live_checked_at?: string | null;
  current_room_id?: string | null;
  /** When `true`, this subscription's sanitized headline scoreboard is
   *  exposed via the unauthenticated `/public/tiktok/lives` endpoint
   *  and rendered on the public home page. Operator-only signals
   *  (gifters, comments, listener state) stay private regardless. */
  is_public?: boolean;
}

// ─── Public (unauthenticated) view ──────────────────────────────────
//
// Sanitized, read-only shape returned by `/public/tiktok/lives`.
// Operator-only signals (top gifters, listener health, comments) are
// stripped server-side — the public page never sees PII-adjacent data.

export interface PublicLive {
  unique_id: string;
  nickname: string | null;
  avatar_url: string | null;
  follower_count: number | null;
  is_live: boolean;
  viewer_count: number | null;
  diamonds_session: number | null;
  started_at: string | null;        // ISO timestamp
  hourly_buckets: number[];         // length 60, oldest→newest, diamonds/min
}

export interface TikTokRoom {
  room_id: string;
  host_unique_id: string | null;
  host_user_id: string | null;
  title: string | null;
  started_at: string | null;
  ended_at: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  /** Per-room rollups returned by `/lives/{handle}/rooms`. Optional
   *  because some upstream endpoints build TikTokRoom from a single
   *  Room dataclass without computing totals. */
  diamonds?: number | null;
  matches?: number | null;
  likes?: number | null;
}

export interface TikTokEvent {
  id: string;
  room_id: string;
  user_id: string | null;
  ts: string;
  type: string;
  payload: Record<string, unknown>;
  match_id?: number | null;
}

export type TikTokSignProvider = 'euler' | 'session' | 'local';

export interface TikTokSignConfig {
  provider: TikTokSignProvider;
  /** Masked when fetched normally; full value when fetched with reveal=1. */
  euler_api_key: string | null;
  euler_api_key_set: boolean;
  session_id: string | null;
  session_id_set: boolean;
  session_tt_target_idc: string | null;
  local_sign_url: string | null;
}

export interface TikTokHandleLookup {
  handle: string;
  exists: boolean | null;
  // tri-state: true = confirmed live, false = confirmed offline,
  // null = TikTok refused our probe (typical when unauthenticated).
  is_live: boolean | null;
  nickname: string | null;
  user_id: string | null;
  avatar_url: string | null;
  bio: string | null;
  follower_count: number | null;
  following_count: number | null;
  room_id: string | null;
  title: string | null;
  viewer_count: number | null;
  source: 'tiktok' | 'cache' | null;
  error: string | null;
  warning: string | null;
  already_subscribed: boolean;
}

export interface TikTokGift {
  gift_id: string;
  name: string | null;
  diamond_count: number | null;
  icon_url: string | null;
  streakable: boolean | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface TikTokMatchOpponent {
  user_id?: string | null;
  unique_id?: string | null;
  nickname?: string | null;
  avatar_url?: string | null;
  team_id?: number | string | null;
  score?: number | null;
  tags?: Array<{ content: string; icon_url: string | null }>;
}

export interface TikTokUserMatchEntry {
  match_id: number;
  battle_id: string | null;
  room_id: string;
  host_unique_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  winner_user_id: string | null;
  opponents: TikTokMatchOpponent[];
  scores: Record<string, number>;
  /** This user's per-match gift contribution. */
  user_gifts: number;
  user_diamonds: number;
}

export interface TikTokUserMatchesResponse {
  items: TikTokUserMatchEntry[];
  total: number;
}

export interface TikTokMatchSettings {
  duration_seconds?: number | null;
  start_time_ms?: number | null;
  end_time_ms?: number | null;
  extra_duration_seconds?: number | null;
}

export type TikTokMatchResult = 'won' | 'lost' | 'draw' | 'ended' | 'ongoing';

export interface TikTokMatchScoreFrame {
  ts: string | null;
  scores: Record<string, number>;
}

export interface TikTokMatchSideGifter {
  user_id: string;
  unique_id: string | null;
  nickname: string | null;
  avatar_url: string | null;
  gifts: number;
  diamonds: number;
  largest_single: number;
  events: number;
}

export interface TikTokMatchGiftersBySide {
  host: TikTokMatchSideGifter[];
  opponent: TikTokMatchSideGifter[];
  unknown: TikTokMatchSideGifter[];
  totals: {
    host_gifters: number;
    host_diamonds: number;
    host_gifts: number;
    opponent_gifters: number;
    opponent_diamonds: number;
    opponent_gifts: number;
    unknown_diamonds: number;
    /** How many sibling `tiktok_matches` rows the backend merged into
     *  the opponent bucket — i.e. how many OTHER monitored hosts'
     *  WebSocket streams contributed gift events to the opponent side.
     *  0 means the opponent isn't being tracked, so the only opponent-
     *  side gifts in the panel are `to_user`-tagged multi-target gifts
     *  from the host's own stream. ≥1 means the opponent IS monitored
     *  and their stream's gifts are ingested too. Defaults to 0 on the
     *  legacy backend that doesn't emit it yet. */
    siblings_merged?: number;
    /** Room IDs of those sibling matches. When the user clicks an
     *  opponent-side donor row in the match modal, the gifter detail
     *  modal needs to query these rooms too — otherwise the donor's
     *  gift history sits in the rival's broadcast (a different
     *  room_id) and the modal renders empty. Passed as `extraRoomIds`
     *  to the unified `TikTokGifterDetailModal`. */
    sibling_room_ids?: string[];
  };
}

export interface TikTokMatchHeadToHeadRow {
  id: number;
  battle_id: string | null;
  room_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  opponents: TikTokMatchOpponent[];
  scores: Record<string, number>;
  winner_user_id: string | null;
  /** Resolved opponent unique_id of the winner (when known). */
  winner_unique_id?: string | null;
  diamonds_total: number;
  /** Pre-computed enrichments — see backend `get_match_head_to_head`.
   *  Avoids re-deriving on every render. */
  host_score?: number | null;
  opp_score?: number | null;
  margin?: number | null;
  outcome?: 'won' | 'lost' | 'draw' | 'ended';
  decisive_pct?: number | null;
  duration_seconds?: number | null;
  opponent_handles?: string[];
}

export interface TikTokLiveSummary {
  active_room_id?: string | null;
  live_started_at?: string | null;
  viewer_count?: number | null;
  /** Per-minute viewer count for the last 30 minutes, oldest→newest.
   *  Forward-filled (last-known-value) so brief gaps in the WS feed
   *  don't dip to zero. Length is variable: bounded by ≤30 and may
   *  be shorter when the broadcast is younger than 30 min. */
  viewer_history?: number[];
  diamonds_session?: number;
  hourly_buckets?: number[]; // length 60, oldest→newest, diamonds/min
  daily_buckets?: number[];  // length 24, oldest→newest, events/hour
  /** Single top contributor — kept for backward compat. Prefer
   *  `top_gifters` (top 3) which surfaces the "who's grouping up"
   *  signal that #1 alone misses. */
  top_gifter?: TikTokLiveTopGifter | null;
  top_gifters?: TikTokLiveTopGifter[];
  /** Distinct user_ids that gifted in the active session. */
  n_unique_gifters?: number;
  /** Of those, how many had no prior history with this host
   *  (`tiktok_user_host_summary` first_seen_at >= live_started_at). */
  n_first_time_gifters?: number;
  /** Comments per minute over last 5 vs last 60 — leading indicator
   *  for gifts. `recent / baseline > 2` ≈ room heating up. */
  comments_per_min_recent?: number;
  comments_per_min_baseline?: number;
  /** Seconds since the most-recent event of each type, scoped to
   *  the active room. Used to render "🔇 quiet 2m" when stale. */
  last_gift_age_s?: number | null;
  last_comment_age_s?: number | null;
  last_event_age_s?: number | null;
  /** Number of `live_pause` events fired during the current session.
   *  TikTok emits one when the creator pauses the broadcast (camera
   *  off / intermission). `last_pause_age_s` is seconds since the
   *  most recent pause. Note: TikTok does not reliably emit unpause
   *  events, so we don't surface "currently paused" — only count + age. */
  n_pauses?: number;
  last_pause_age_s?: number | null;
  /** Currently-running poll, when the host has one open. TikTok fires
   *  `message_type=2` events repeatedly while a poll is open; absence
   *  of a fresh mt=2 event for >60s implies the poll has dropped. */
  active_poll?: {
    title: string;
    poll_id: string | null;
    fresh_age_s: number;
  } | null;
  /** Red-envelope drops this session — separate from regular gifts.
   *  `n_envelopes_session` is count; `envelope_diamonds_session` is
   *  the sum of their diamond_count (some envelopes are free-promo
   *  with diamond_count=0, others carry 20-120+ each). */
  n_envelopes_session?: number;
  envelope_diamonds_session?: number;
  /** Favourite gifters present in the room (any event type within
   *  last 5 min). Pre-gift presence is the actual edge. */
  favorites_in_room?: Array<{
    user_id: string | null;
    unique_id: string | null;
    nickname: string | null;
    avatar_url: string | null;
    seen_age_s: number;
  }>;
  active_match?: {
    match_id: number;
    battle_id: string | null;
    /** Seconds remaining on the PK clock (settings.end_time_ms-now). */
    countdown_s?: number | null;
    opponents: Array<{
      user_id: string | null;
      unique_id: string | null;
      nickname: string | null;
      avatar_url: string | null;
      score: number;
    }>;
  } | null;
  /** Ratio: this session's diamonds vs this creator's median per-
   *  live over the last 30d. Null when there's no historical
   *  baseline. >1 = above typical, <1 = below. */
  diamonds_vs_typical?: number | null;
  median_diamonds_30d?: number | null;
  /** How many times the worker reconnected this listener in the
   *  last hour. >0 hints at instability. */
  reconnects_1h?: number;
  /** Scoreboard counters for the active broadcast — total events of
   *  each type, distinct commenters, biggest single gift, and the
   *  PK W-L-D ledger so far. Render as a number grid in the card. */
  session_stats?: {
    n_comments?: number;
    n_gifts?: number;
    n_likes?: number;
    n_joins?: number;
    n_follows?: number;
    n_shares?: number;
    n_unique_commenters?: number;
    largest_gift_diamonds?: number;
    n_battles?: number;
    session_w?: number;
    session_l?: number;
    session_d?: number;
  };
  /** Per-day rollup for the last 7 days. Index 0 = 7 days ago,
   *  index 6 = today (oldest→newest, matches the hourly sparkline
   *  reading order). Each entry carries rooms + duration + diamonds
   *  for that day. Drives the 7-cell heatmap strip on the lives
   *  index card. */
  week_calendar?: Array<{
    day_offset: number;
    rooms: number;
    duration_min: number;
    diamonds: number;
  }>;
  last_broadcasts?: Array<{
    room_id: string;
    started_at: string | null;
    /** `ended_at` is the room's `ended_at` column when set, falling
     *  back to `last_seen_at` when it isn't (the listener doesn't
     *  always flag a clean shutdown). When the fallback is used,
     *  `ended_inferred` is `true` so the UI can mark it (e.g. with
     *  a `~` prefix). */
    ended_at: string | null;
    ended_inferred?: boolean | null;
    duration_min: number | null;
    diamonds: number;
    /** Per-broadcast counters. Populated for `[0]` (the most recent
     *  broadcast) only — older entries report `0` since they're not
     *  rendered in the offline-card preview and the full multi-type
     *  scan would inflate the hot path. */
    n_gifts?: number;
    n_comments?: number;
    peak_viewers?: number;
  }>;
  avg_duration_min?: number | null;
  avg_diamonds?: number | null;
  n_rooms_30d?: number;
  momentum_label?: 'heating' | 'cooling' | 'steady' | 'silent' | null;
}

export interface TikTokLiveTopGifter {
  user_id: string | null;
  unique_id: string | null;
  nickname: string | null;
  avatar_url: string | null;
  diamonds: number;
  gifts?: number;
}

export interface TikTokLivesTotals {
  n_live: number;
  n_offline: number;
  n_total: number;
  diamonds_24h: number;
  events_per_min: number;
}

export interface TikTokNotification {
  id: number;
  ts: string | null;
  type: string;
  title: string;
  body: string | null;
  host_unique_id: string | null;
  user_id: string | null;
  payload: Record<string, unknown> | null;
  read: boolean;
  cleared: boolean;
}

export interface TikTokNotificationCreate {
  type: string;
  title: string;
  body?: string | null;
  host_unique_id?: string | null;
  user_id?: string | null;
  payload?: Record<string, unknown> | null;
  ts?: string | null;
}

export interface TikTokH2HCommonGifter {
  user_id: string;
  battles: number;
  diamonds: number;
  gifts: number;
  unique_id: string | null;
  nickname: string | null;
  avatar_url: string | null;
}

export interface TikTokMatch {
  id: number;
  room_id: string;
  battle_id: string;
  opponents: TikTokMatchOpponent[];
  scores: Record<string, number>;
  settings?: TikTokMatchSettings;
  winner_user_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  last_seen_at: string | null;
  diamonds_total: number;
  result: TikTokMatchResult;
}

export interface TikTokGifter {
  user_id: string | null;
  unique_id: string | null;
  nickname: string | null;
  /** Avatar URL — `tiktok_viewers.avatar_url` first; falls back to the
   *  most-recent gift event's payload `user.avatar_url`. May be empty
   *  when TikTok didn't supply one on the gift event. */
  avatar_url?: string | null;
  diamonds: number;
  gifts: number;
  comments: number;
  /** Snapshot of TikTok identity fields at the user's last gift event:
   *  is_moderator / is_subscribe / is_top_gifter / member_level /
   *  gifter_level / fans_club, etc. Consumed by `TikTokUserBadges`. */
  identity?: import('@admin/components/TikTokUserBadges').IdentityBlock | null;
}

export interface TikTokRoomGifters {
  items: TikTokGifter[];
  total: number;
  limit: number;
  offset: number;
}

/** Per-host contribution slice for a `TikTokCommonGifter`. `host` is
 *  the creator's `unique_id` (matches `TikTokSubscription.unique_id`);
 *  `diamonds` and `gifts` are summed across every room of that host
 *  the viewer ever gifted in. */
export interface TikTokCommonGifterHostSlice {
  host: string;
  diamonds: number;
  gifts: number;
}

/** Cross-creator gifter row returned by /admin/tiktok/common-gifters. */
export interface TikTokCommonGifter {
  user_id: string | null;
  unique_id: string | null;
  nickname: string | null;
  avatar_url?: string | null;
  /** Number of distinct hosts this viewer has gifted to. */
  host_count: number;
  /** Total diamonds across every host. */
  diamonds: number;
  /** Total individual gifts (repeats × distinct gift events). */
  gifts: number;
  hosts: TikTokCommonGifterHostSlice[];
}

export interface TikTokCommonGiftersPage {
  items: TikTokCommonGifter[];
  total: number;
  limit: number;
  offset: number;
  min_hosts: number;
}

/** Host-scoped cross-live gifter row returned by
 *  `/admin/tiktok/lives/{handle}/cross-live-gifters` and its
 *  public mirror. Carries here/elsewhere splits so the table can
 *  surface "spends X here, Y across N other lives" without a
 *  client-side recompute. */
export interface TikTokCrossLiveGifter {
  user_id: string | null;
  unique_id: string | null;
  nickname: string | null;
  avatar_url?: string | null;
  /** Total distinct hosts this viewer has gifted to (incl. queried). */
  host_count: number;
  diamonds_here: number;
  gifts_here: number;
  diamonds_elsewhere: number;
  gifts_elsewhere: number;
  /** Other hosts (excludes the queried host), sorted by diamonds desc. */
  other_hosts: TikTokCommonGifterHostSlice[];
}

export interface TikTokCrossLiveGiftersPage {
  items: TikTokCrossLiveGifter[];
  total: number;
  limit: number;
  offset: number;
  min_other_hosts: number;
  host: string;
}

/** Recent room a viewer gifted in for one host. */
export interface TikTokCommonGifterDetailRoom {
  room_id: string;
  title: string | null;
  started_at: string | null;
  ended_at: string | null;
  diamonds: number;
  gifts: number;
}

/** Top gift kind a viewer sent to one host. */
export interface TikTokCommonGifterDetailTopGift {
  gift_name: string;
  count: number;
  diamonds: number;
}

/** Per-host slice on the detail payload — fuller than the row's
 *  `TikTokCommonGifterHostSlice` (adds room/comment counts, recent
 *  rooms, top gift kinds). */
export interface TikTokCommonGifterDetailHost {
  host: string;
  diamonds: number;
  gifts: number;
  room_count: number;
  comment_count: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
  top_gifts: TikTokCommonGifterDetailTopGift[];
  rooms: TikTokCommonGifterDetailRoom[];
  /** Gifts this user sent during a PK/match in this host's rooms. */
  match_gifts?: number;
  match_diamonds?: number;
  /** Total rooms (broadcasts) ever recorded for this host. Combined
   *  with `room_count` to compute attendance %. */
  host_total_rooms?: number;
  attendance_pct?: number;
  /** Gift kind disproportionately sent to this host (lift ≥1.5×
   *  vs the user's overall mix). Surfaces "they send Roses 4× more
   *  to @host than baseline." */
  signature_gift?: {
    gift_name: string;
    lift: number;
    diamonds: number;
    count: number;
  } | null;
  /** Top-N targeted gift recipients in this host's rooms (multi-
   *  guest / PK lives where the gifter aimed at a specific person).
   *  Empty for purely solo-live histories. */
  recipients?: TikTokGiftRecipient[];
  /** PK partisanship for this host: of all gifts sent during a
   *  battle, how many went to the host vs to opponents/guests. Null
   *  when the user never gifted during a PK in this host's rooms. */
  pk_partisanship?: {
    to_host_gifts: number;
    to_host_diamonds: number;
    to_others_gifts: number;
    to_others_diamonds: number;
    to_host_pct: number;
    to_others_pct: number;
  } | null;
}

export interface TikTokGiftRecipient {
  unique_id: string | null;
  nickname: string | null;
  gifts: number;
  diamonds: number;
  pk_gifts: number;
  pk_diamonds: number;
  is_host: boolean;
}

/** One day×host row of the gifter's own host-side fan-rank state. */
export interface TikTokIdentityProgressionRow {
  day: string;
  host: string;
  member_level: number | null;
  gifter_level: number | null;
  fan_ticket_count: number | null;
  is_subscribe: boolean | null;
  fans_club_name: string | null;
  fans_club_level: number | null;
}

/** One cell of the gifter's hour×day-of-week activity heatmap.
 *  `dow` is 0–6 (0=Sun per Postgres EXTRACT(DOW)). */
export interface TikTokCommonGifterHeatmapCell {
  dow: number;
  hour: number;
  gifts: number;
  diamonds: number;
}

/** Daily diamond/gift contribution to one host. */
export interface TikTokCommonGifterDailyPoint {
  day: string;
  host: string;
  diamonds: number;
  gifts: number;
}

/** Recent-activity feed item (gift / comment / join / etc). */
export interface TikTokCommonGifterActivityItem {
  id: number;
  ts: string | null;
  type: string;
  host: string | null;
  room_id: string | null;
  gift_name?: string | null;
  repeat_count?: number | null;
  diamond_count?: number | null;
  text?: string;
}

/** Co-gifter — another viewer who appeared in ≥3 of the same rooms. */
export interface TikTokCommonGifterCoGifter {
  user_id: string;
  unique_id: string | null;
  nickname: string | null;
  avatar_url: string | null;
  shared_rooms: number;
  diamonds_in_overlap: number;
}

export interface TikTokCommonGifterDetail {
  user_id: number;
  unique_id: string | null;
  nickname: string | null;
  avatar_url: string | null;
  identity?: import('@admin/components/TikTokUserBadges').IdentityBlock | null;
  totals: {
    diamonds: number;
    gifts: number;
    host_count: number;
    room_count: number;
    comment_count: number;
    first_seen_at: string | null;
    last_seen_at: string | null;
  };
  hosts: TikTokCommonGifterDetailHost[];
  /** Counts of every event type this user generated, system-wide.
   *  `{ gift: 12, comment: 50, join: 19, ... }`. Drives the
   *  behavioral-mix donut on the Profile tab. */
  behavior?: Record<string, number>;
  /** Hour×DOW activity grid (gifts only). */
  heatmap?: TikTokCommonGifterHeatmapCell[];
  /** Per-day, per-host gift series (last 90 days). */
  daily_series?: TikTokCommonGifterDailyPoint[];
  /** Streak / gap / biggest-session stats. */
  intensity?: {
    biggest_session?: {
      room_id: string | null;
      host: string | null;
      title: string | null;
      diamonds: number;
      gifts: number;
    };
    active_days?: number;
    longest_streak_days?: number;
    longest_gap_days?: number;
    first_active_day?: string;
    last_active_day?: string;
  };
  /** Where this user sits among the global common-gifter pool. */
  rank?: {
    pool_size: number;
    by_diamonds: number;
    by_host_count: number;
    by_gifts: number;
  };
  /** Last 100 events of any type. */
  recent_activity?: TikTokCommonGifterActivityItem[];
  /** Other viewers who gifted in ≥3 of the same rooms. */
  co_gifters?: TikTokCommonGifterCoGifter[];
  /** Bucketed gift-tier distribution (tiny/small/medium/large by per-event diamond_count). */
  tier_mix?: { tier: 'tiny' | 'small' | 'medium' | 'large'; gifts: number; diamonds: number }[];
  /** Combo / streak character of their gifting. */
  streakiness?: {
    avg_repeat: number;
    max_repeat: number;
    streak_event_pct: number;
    total_gift_events: number;
  };
  /** Comment-around-gift coupling — % of gifts paired with a comment within ±60s. */
  coupling?: {
    gift_events: number;
    coupled_gifts: number;
    coupling_pct: number;
  };
  /** Time-to-first-gift after joining a room. */
  ttfg?: {
    median_seconds: number;
    avg_seconds: number;
    min_seconds: number;
    rooms_with_both: number;
  };
  /** Top-5 rooms ranked by share of room's total diamonds this user drove. */
  whale_sessions?: {
    room_id: string | null;
    host: string | null;
    title: string | null;
    started_at: string | null;
    user_diamonds: number;
    user_gifts: number;
    room_diamonds: number;
    share_pct: number;
  }[];
  /** Histogram of host anchor_levels this user gifts to. */
  anchor_hist?: { anchor_level: number; gifts: number }[];
  /** Concentration of diamond spend across hosts. */
  loyalty?: {
    gini: number;
    top1_pct: number;
    top_host: string | null;
  };
  /** 7d-vs-28d momentum classification. */
  momentum?: {
    label: 'heating' | 'cooling' | 'steady' | 'silent';
    ratio: number;
    diamonds_7d: number;
    diamonds_28d: number;
  };
  /** Daily MAX of the gifter's own host-side fan-rank fields per
   *  (day, host). Drives the per-host fan-rank trajectory plot. */
  identity_progression?: TikTokIdentityProgressionRow[];
}

export interface TikTokRoomRecipient {
  user_id: string | null;
  unique_id: string | null;
  nickname: string | null;
  diamonds: number;
  gifts: number;
}

export interface TikTokRoomRecipients {
  items: TikTokRoomRecipient[];
  total_diamonds: number;
  limit: number;
}

export interface TikTokRoomStats {
  room: TikTokRoom | null;
  window_minutes: number;
  bucket_seconds: number;
  since: string;
  now: string;
  counts_window: Record<string, number>;
  counts_total: Record<string, number>;
  top_gifters: TikTokGifter[];
  diamonds_total: number;
  active_match: TikTokMatch | null;
  buckets: {
    starts: string[];
    by_type: Record<string, number[]>;
    diamonds: number[];
  };
}

export interface TikTokDashboardStats {
  since: string;
  now: string;
  since_hours: number;
  bucket_seconds: number;
  creators: Array<{
    host_unique_id: string;
    total: number;
    by_type: Record<string, number>;
  }>;
  buckets: Array<{
    bucket: string;
    host_unique_id: string;
    type: string;
    count: number;
  }>;
}

const BASE = '/admin/tiktok';

// ─── API client ─────────────────────────────────────────────────────────────

export const tiktokApi = {
  // Subscriptions

  listLives(): Promise<TikTokSubscription[]> {
    return apiRequest({ method: 'GET', url: `${BASE}/lives` });
  },

  /** Single-handle lookup. No dedicated admin endpoint — filter from
   *  `listLives()`. Mirrors the shape of `publicTiktokApi.getLiveByHandle`
   *  so the shared live-detail component (used by both admin and public
   *  routes via the `TikTokApiContext`) can fetch the host record
   *  uniformly without branching on the active namespace. */
  getLiveByHandle(handle: string): Promise<TikTokSubscription> {
    return apiRequest<TikTokSubscription[]>({
      method: 'GET',
      url: `${BASE}/lives`,
    }).then((rows) => {
      const needle = handle.toLowerCase();
      const found = rows.find((r) => (r.unique_id || '').toLowerCase() === needle);
      if (!found) {
        const err = new Error(`Host @${handle} not found`);
        (err as Error & { status?: number }).status = 404;
        throw err;
      }
      return found;
    });
  },

  lookupHandle(handle: string): Promise<TikTokHandleLookup> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lookup`,
      params: { handle },
    });
  },

  createLive(username: string, enabled = true): Promise<TikTokSubscription> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/lives`,
      data: { username, enabled },
    });
  },

  setEnabled(handle: string, enabled: boolean): Promise<TikTokSubscription> {
    return apiRequest({
      method: 'PATCH',
      url: `${BASE}/lives/${encodeURIComponent(handle)}`,
      data: { enabled },
    });
  },

  /** Mark / unmark a subscription as publicly visible. When public,
   *  the host's sanitized headline scoreboard is exposed via the
   *  unauthenticated `/public/tiktok/lives` endpoint. Operator-only
   *  signals are stripped server-side regardless of this flag. */
  setLivePublic(handle: string, isPublic: boolean): Promise<void> {
    return apiRequest({
      method: 'PATCH',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/public`,
      data: { is_public: isPublic },
    });
  },

  refreshProfile(handle: string): Promise<TikTokSubscription> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/refresh`,
    });
  },

  deleteLive(handle: string): Promise<{ ok: boolean }> {
    return apiRequest({
      method: 'DELETE',
      url: `${BASE}/lives/${encodeURIComponent(handle)}`,
    });
  },

  /** Force the worker to teardown + restart this handle's listener,
   *  cutting short any parked backoff sleep (AgeRestricted / sign
   *  rate limit / etc.). Also clears the stale `is_live` cache so the
   *  UI's LIVE pill drops immediately. */
  reconnectLive(handle: string): Promise<{ ok: boolean }> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/reconnect`,
    });
  },

  // Rooms + events

  listHostRooms(handle: string, limit = 50): Promise<TikTokRoom[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/rooms`,
      params: { limit },
    });
  },

  getRoom(roomId: string): Promise<TikTokRoom> {
    return apiRequest({ method: 'GET', url: `${BASE}/rooms/${roomId}` });
  },

  listRoomEvents(
    roomId: string,
    opts?: { type?: string; limit?: number; before_id?: string }
  ): Promise<TikTokEvent[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/rooms/${roomId}/events`,
      params: opts,
    });
  },

  // Stats / dashboard

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

  getRoomStats(
    roomId: string,
    opts?: {
      window_minutes?: number;
      bucket_seconds?: number;
      since?: string;
      until?: string;
    }
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
      // Day-aggregate view: extra room ids whose gifters should be
      // summed alongside the path roomId. Backend de-duplicates.
      extra_room_ids?: string[];
    }
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

  /** Deep-analysis payload for a single common gifter. */
  getCommonGifterDetail(userId: string): Promise<TikTokCommonGifterDetail> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/common-gifters/${encodeURIComponent(userId)}/detail`,
    });
  },

  /** Cross-live gifters scoped to one host: viewers who've gifted to
   *  this host AND to >= `min_other_hosts` other hosts we track. Powers
   *  the "Cross-live" tab on the live detail page. */
  getRoomCrossLiveGifters(
    handle: string,
    opts?: {
      min_other_hosts?: number;
      q?: string;
      limit?: number;
      offset?: number;
    },
  ): Promise<TikTokCrossLiveGiftersPage> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/${encodeURIComponent(handle)}/cross-live-gifters`,
      params: opts,
    });
  },

  // ── Favourite gifters ─────────────────────────────────────────────

  listFavoriteGifters(opts?: {
    q?: string;
    limit?: number;
    offset?: number;
  }): Promise<{
    items: Array<TikTokCommonGifter & { note: string | null; added_at: string | null }>;
    total: number;
    limit: number;
    offset: number;
  }> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/favorite-gifters`,
      params: opts,
    });
  },

  /** Bare id list — kept for callers that just want ids. */
  listFavoriteGifterIds(): Promise<{ ids: string[] }> {
    return apiRequest({ method: 'GET', url: `${BASE}/favorite-gifters/ids` });
  },

  /** Per-favourite notify config — drives the WS-toast filter so
   *  each event type (gift / comment / join) can be opted in/out
   *  per favourite. */
  listFavoriteGifterNotifyConfig(): Promise<{
    items: Array<{
      user_id: string;
      notify_gift: boolean;
      notify_comment: boolean;
      notify_join: boolean;
    }>;
  }> {
    return apiRequest({ method: 'GET', url: `${BASE}/favorite-gifters/notify-config` });
  },

  isFavoriteGifter(userId: string): Promise<{ user_id: string; is_favorite: boolean }> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/favorite-gifters/${encodeURIComponent(userId)}`,
    });
  },

  addFavoriteGifter(
    userId: string,
    opts?: {
      note?: string;
      notify_gift?: boolean;
      notify_comment?: boolean;
      notify_join?: boolean;
    },
  ): Promise<{ ok: boolean; is_favorite: boolean }> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/favorite-gifters/${encodeURIComponent(userId)}`,
      data: opts ?? {},
    });
  },

  /** Update notify toggles / note on an existing favourite. UPSERT
   *  semantics on the backend — call this whether or not the
   *  favourite already exists. */
  updateFavoriteGifter(
    userId: string,
    opts: {
      note?: string;
      notify_gift?: boolean;
      notify_comment?: boolean;
      notify_join?: boolean;
    },
  ): Promise<{ ok: boolean; is_favorite: boolean }> {
    return apiRequest({
      method: 'PATCH',
      url: `${BASE}/favorite-gifters/${encodeURIComponent(userId)}`,
      data: opts,
    });
  },

  removeFavoriteGifter(userId: string): Promise<{ ok: boolean; is_favorite: boolean }> {
    return apiRequest({
      method: 'DELETE',
      url: `${BASE}/favorite-gifters/${encodeURIComponent(userId)}`,
    });
  },

  /** Cross-creator gifter leaderboard: who's gifted to >=`min_hosts`
   *  distinct creators we track. Paginated, supports nickname /
   *  @unique_id substring search. */
  getCommonGifters(opts?: {
    min_hosts?: number;
    q?: string;
    limit?: number;
    offset?: number;
  }): Promise<TikTokCommonGiftersPage> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/common-gifters`,
      params: opts,
    });
  },

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
      url: `${BASE}/lives/${handle}/calendar`,
      params: { weeks, tz },
    });
  },

  getRoomRecipients(
    roomId: string,
    opts?: {
      since?: string;
      until?: string;
      limit?: number;
    }
  ): Promise<TikTokRoomRecipients> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/rooms/${roomId}/recipients`,
      params: opts,
    });
  },

  getDashboard(opts?: {
    since_hours?: number;
    bucket_seconds?: number;
    tz?: string;
  }): Promise<TikTokDashboardStats> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/dashboard`,
      params: opts,
    });
  },

  listGifts(limit = 200): Promise<TikTokGift[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/gifts`,
      params: { limit },
    });
  },

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

  /** Fetch a single match enriched with diamonds_total + result —
   *  same shape as `listMatches` rows. Used by the debug "open by
   *  match id" form so the operator can deep-link any battle. */
  getMatch(matchId: number): Promise<TikTokMatch> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches/${matchId}`,
    });
  },

  /** Decoded score timeline for a single PK battle.
   *  Returns rows in ascending ts order; each row carries the score
   *  map at that instant, keyed by `team_id` (string for JS BigInt
   *  safety). Drives the dual-line score chart on the match-detail
   *  Score Timeline tab. */
  getMatchScoreTimeline(matchId: number): Promise<TikTokMatchScoreFrame[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches/${matchId}/score_timeline`,
    });
  },

  /** Top gifters during a match split by which side they backed
   *  (host / opponent / unknown). The `unknown` bucket captures
   *  gifts where the lib didn't surface a recipient — useful as a
   *  data-quality indicator on the modal. */
  getMatchGiftersBySide(matchId: number): Promise<TikTokMatchGiftersBySide> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches/${matchId}/gifters_by_side`,
    });
  },

  /** Prior PK battles between this host and (any of) the same
   *  opponents. Used to build the Head-to-Head context tab. */
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

  // ─── Lives row enrichment ─────────────────────────────────────

  livesTotals(): Promise<TikTokLivesTotals> {
    return apiRequest({ method: 'GET', url: `${BASE}/lives/totals` });
  },

  livesSummary(handles?: string[]): Promise<Record<string, TikTokLiveSummary>> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/lives/summary`,
      params: handles && handles.length > 0 ? { handles: handles.join(',') } : {},
    });
  },

  // ─── Notifications history ────────────────────────────────────

  listNotifications(opts: {
    since?: string;
    until?: string;
    type?: string;
    handle?: string;
    unread_only?: boolean;
    include_cleared?: boolean;
    limit?: number;
    offset?: number;
  } = {}): Promise<TikTokNotification[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/notifications`,
      params: opts,
    });
  },

  unreadNotificationsCount(): Promise<{ unread: number }> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/notifications/unread_count`,
    });
  },

  createNotification(n: TikTokNotificationCreate): Promise<{ id: number }> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/notifications`,
      data: n,
    });
  },

  markNotificationRead(
    id: number,
    read = true,
  ): Promise<{ ok: boolean }> {
    return apiRequest({
      method: 'PATCH',
      url: `${BASE}/notifications/${id}/read`,
      params: { read },
    });
  },

  markAllNotificationsRead(): Promise<{ updated: number }> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/notifications/mark_all_read`,
    });
  },

  clearNotification(id: number): Promise<{ ok: boolean }> {
    return apiRequest({
      method: 'DELETE',
      url: `${BASE}/notifications/${id}`,
    });
  },

  clearAllNotifications(): Promise<{ cleared: number }> {
    return apiRequest({
      method: 'DELETE',
      url: `${BASE}/notifications`,
    });
  },

  /** Viewers who gifted in ≥`min_battles` of the H2H set for this
   *  match. Drives the "regulars / common gifters" bench section. */
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

  listMatchesForRoom(roomId: string, limit = 50): Promise<TikTokMatch[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/matches`,
      params: { room_id: roomId, limit },
    });
  },

  /** Matches a specific user contributed gifts to, scoped by a room
   *  set + optional time window. Powers the gifter modal's Matches
   *  tab. Omit `roomIds` for cross-host (every match the user ever
   *  gifted in). */
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

  // Sign-engine config

  getSignConfig(reveal = false): Promise<TikTokSignConfig> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/sign/config`,
      params: reveal ? { reveal: 1 } : undefined,
    });
  },

  saveSignConfig(body: {
    provider: TikTokSignProvider;
    euler_api_key?: string;
    session_id?: string;
    session_tt_target_idc?: string;
    local_sign_url?: string;
  }): Promise<TikTokSignConfig> {
    return apiRequest({
      method: 'PUT',
      url: `${BASE}/sign/config`,
      data: body,
    });
  },

  testSignConfig(): Promise<{
    ok: boolean;
    user_id: string | null;
    nickname: string | null;
    unique_id: string | null;
    sec_uid: string | null;
    follower_count: number | null;
    error: string | null;
  }> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/sign/test`,
    });
  },

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
    /** Filter to gift events whose `payload.to_user.user_id` matches.
     *  Used by the match-detail Activity tab "side" filter. */
    to_user_id?: string;
    /** Filter to gift events whose total diamond value (per-event
     *  diamond_count × repeat_count) is at least this much. */
    min_diamonds?: number;
    limit?: number;
    before_id?: string;
    offset?: number;
  }): Promise<TikTokEvent[]> {
    const { room_ids, ...rest } = opts;
    return apiRequest({
      method: 'GET',
      url: `${BASE}/events/search`,
      params: {
        ...rest,
        ...(room_ids && room_ids.length > 0
          ? { room_ids: room_ids.join(',') }
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
    const { room_ids, ...rest } = opts;
    return apiRequest({
      method: 'GET',
      url: `${BASE}/events/count`,
      params: {
        ...rest,
        ...(room_ids && room_ids.length > 0
          ? { room_ids: room_ids.join(',') }
          : {}),
      },
    });
  },

  // ─── Listener-pool status + control ────────────────────────────────
  listenerStatus(): Promise<TikTokListenerStatus> {
    return apiRequest({ method: 'GET', url: `${BASE}/listener/status` });
  },
  listenerPause(): Promise<{ ok: boolean; pid?: number; detail?: string }> {
    return apiRequest({ method: 'POST', url: `${BASE}/listener/pause` });
  },
  listenerResume(): Promise<{ ok: boolean; pid?: number; detail?: string }> {
    return apiRequest({ method: 'POST', url: `${BASE}/listener/resume` });
  },
  listenerKill(): Promise<{ ok: boolean; pid?: number; signal?: string }> {
    return apiRequest({ method: 'POST', url: `${BASE}/listener/kill` });
  },

  /** Recent worker_log rows. Pass `handle` to filter to one creator,
   *  `event_prefix` to grep by event tag (e.g. "profile_probe"). */
  listenerLog(opts: {
    worker_id?: number;
    handle?: string;
    event_prefix?: string;
    limit?: number;
  } = {}): Promise<TikTokWorkerLogEntry[]> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/listener/log`,
      params: opts,
    });
  },
};

export type TikTokWorkerLogEntry = {
  id: number;
  worker_id: number | null;
  ts: string | null;
  level: string;
  event: string;
  handle: string | null;
  detail: Record<string, unknown> | null;
};

export type TikTokListenerSession = {
  handle: string;
  state: string;
  events_total: number;
  last_event_at: string | null;
  last_event_age_s: number | null;
  /** Seconds remaining before the offline-recycle hysteresis kicks
   *  in and the worker releases this session's slot. `null` means the
   *  session isn't being watched for release (live, connected, or the
   *  central is_live probe hasn't classified it yet). The dashboard
   *  ticks this down once a second so the admin can see capacity
   *  about to free up. */
  recycle_release_in_s?: number | null;
  // Loss-detection metrics (worker mode).
  messages_observed?: number | null;
  gaps_count?: number | null;
  gaps_total_missed?: number | null;
  last_gap_size?: number | null;
  last_gap_age_s?: number | null;
  disconnect_count?: number | null;
  connect_count?: number | null;
  connection_uptime_s?: number | null;
};

export type TikTokRedisStatus = {
  available: boolean;
  url: string | null;
  error: string | null;
  required_for_live_updates: boolean;
};

export type TikTokWorkerRow = {
  id: number;
  worker_key: string;
  host: string;
  pid: number;
  status: 'running' | 'paused' | 'stopped' | 'stale' | string;
  capacity: number;
  sessions_count: number;
  /** Subset of sessions in CONNECTED state. Lets the dashboard show
   *  "12 live / 30 slots" instead of the bare slot count, which made
   *  the worker look stuck even when capacity was healthy and the
   *  imbalance was just offline subs sitting in cheap-poll. */
  connected_session_count?: number | null;
  started_at: string | null;
  last_heartbeat_at: string | null;
  heartbeat_age_s: number | null;
  alive: boolean;
  sessions: TikTokListenerSession[];
};

export type TikTokListenerStatus = {
  mode: 'in_process' | 'worker';
  api_passive: boolean;
  worker_alive: boolean | null;
  worker_pid: number | null;
  worker_uptime_s: number | null;
  worker_paused: boolean | null;
  worker_heartbeat_age_s: number | null;
  worker_heartbeat_source: 'redis' | 'file' | 'db' | null;
  sessions: TikTokListenerSession[];
  redis: TikTokRedisStatus;
  workers: TikTokWorkerRow[];
};

// ─── Real-time WebSocket helper ─────────────────────────────────────────────

export type TikTokWsEvent = {
  type: string;
  /** Host (creator) handle — the broadcast this event came from. */
  unique_id: string;
  room_id: string | null;
  /** Actor's TikTok user_id (gifter / commenter / joiner). Null on
   *  events that don't have an actor (live_end, room_info, etc.).
   *  Stringified to dodge JS BigInt lossiness. */
  user_id: string | null;
  payload: Record<string, unknown>;
};

/**
 * Open a WebSocket to the live-events fan-out endpoint.
 *
 * The backend is on a different origin than the Vite dev server, so we
 * derive the WS URL from the configured API base (e.g. http://localhost:8000)
 * rather than `window.location` — otherwise the WS connect goes to the
 * dev server (5173) where there's no proxy and silently fails.
 *
 * Includes the JWT (if any) as a query param, since browsers don't allow
 * setting the Authorization header on a WebSocket. The backend already
 * accepts auth via OAuth2 query token on this endpoint via the same
 * scheme used by FastAPI's OAuth2PasswordBearer.
 *
 * Optional `handles` filter: send a `{type:"subscribe", handles:[...]}`
 * control message immediately on open so the server only forwards events
 * for those creators. Pass undefined / `["*"]` for "everything".
 */
export function openTikTokWebSocket(
  onMessage: (e: TikTokWsEvent) => void,
  onError?: (err: Event) => void,
  options?: {
    handles?: string[] | '*';
    /** Which backend endpoint to connect to. `"admin"` (default) hits
     *  `/admin/tiktok/ws` with the local-storage JWT — every event for
     *  every tracked subscription. `"public"` hits `/public/tiktok/ws`
     *  with no auth — server filters to events for `is_public=True`
     *  handles only, so an anonymous viewer can stream only what the
     *  operator explicitly opted in to. */
    audience?: 'admin' | 'public';
  }
): WebSocket {
  const audience = options?.audience ?? 'admin';
  const baseUrl = apiConfig.baseUrl || window.location.origin;
  const wsBase = baseUrl.replace(/^http(s?):/i, 'ws$1:');
  // Admin WS requires the JWT (browsers can't set Authorization on
  // WS; we put it in the query). Public WS is anonymous — no token
  // appended. The browser's same-origin policy + the backend's
  // public-handle filter is the whole trust model.
  const path = audience === 'admin' ? '/admin/tiktok/ws' : '/public/tiktok/ws';
  let url = `${wsBase}${path}`;
  if (audience === 'admin') {
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    if (token) url += `?token=${encodeURIComponent(token)}`;
  }
  // Tell the telemetry singleton a WS attempt is starting. This is
  // what powers the realtime-status pill in the page header. We
  // call before the constructor so the pill flips to "connecting"
  // immediately, not after the first JS task break.
  tiktokTelemetry.noteWsAttempt();
  // Diagnostic logging — emit a structured record per WS lifecycle
  // event. Keep the token truncated (last 6 chars) so the log isn't
  // a secret leak when shared. Toggle with `localStorage.setItem(
  // 'TIKTOK_WS_DEBUG', '1')` if the console gets too noisy; default
  // ON in dev so the very first WS lifecycle the user looks at is
  // already explained.
  const debugWs = (() => {
    try {
      const v = localStorage.getItem('TIKTOK_WS_DEBUG');
      if (v === '0') return false;
      return true;
    } catch { return true; }
  })();
  const tokenTail = audience === 'admin'
    ? (localStorage.getItem('token') || sessionStorage.getItem('token') || '')
        .slice(-6) || '(none)'
    : '(public — no token)';
  if (debugWs) {
    // eslint-disable-next-line no-console
    console.info('[tiktok-ws] open →', { url: url.split('?')[0], audience, tokenTail });
  }
  const ws = new WebSocket(url);
  ws.addEventListener('open', () => {
    tiktokTelemetry.noteWsOpen();
    if (debugWs) {
      // eslint-disable-next-line no-console
      console.info('[tiktok-ws] OPEN', { url: url.split('?')[0], audience });
    }
  }, { once: true });
  ws.addEventListener('close', (ev) => {
    tiktokTelemetry.noteWsClosed();
    if (debugWs) {
      // WS close codes worth recognising at a glance:
      //   1000 normal, 1001 going-away, 1006 abnormal (no close frame
      //   received — what you see when the server rejects the upgrade
      //   before accepting), 4401 unauthenticated, 4403 forbidden.
      // eslint-disable-next-line no-console
      console.warn('[tiktok-ws] CLOSE', {
        url: url.split('?')[0],
        audience,
        code: ev.code,
        reason: ev.reason || '(none)',
        wasClean: ev.wasClean,
        hint: ev.code === 1006
          ? 'abnormal — usually means the server rejected the upgrade (auth fail) OR the network dropped'
          : ev.code === 4401
            ? 'unauthenticated — token missing or expired'
            : ev.code === 4403
              ? 'forbidden — token valid but lacks admin permission'
              : undefined,
      });
    }
  }, { once: true });
  ws.addEventListener('error', (ev) => {
    tiktokTelemetry.noteWsClosed();
    if (debugWs) {
      // eslint-disable-next-line no-console
      console.warn('[tiktok-ws] ERROR', {
        url: url.split('?')[0],
        audience,
        event: ev,
      });
    }
  }, { once: true });

  // React StrictMode double-invokes effects in dev — the cleanup
  // runs while the socket is still CONNECTING, producing the noisy
  // "WebSocket is closed before the connection is established"
  // warning. The same race exists in prod when a user navigates
  // away within ~100ms of mount (just less commonly visible). Wrap
  // `close` so it defers until the socket is actually OPEN (or
  // errors out) — semantically what the caller wanted anyway.
  const origClose = ws.close.bind(ws);
  ws.close = (code?: number, reason?: string) => {
    if (ws.readyState === WebSocket.CONNECTING) {
      const finish = () => { try { origClose(code, reason); } catch { /* ignore */ } };
      ws.addEventListener('open', finish, { once: true });
      ws.addEventListener('error', finish, { once: true });
      return;
    }
    if (ws.readyState === WebSocket.OPEN) {
      try { origClose(code, reason); } catch { /* ignore */ }
    }
    // CLOSING / CLOSED: nothing to do.
  };

  ws.onmessage = (e) => {
    // Count every well-formed event before the caller's handler so
    // the status pill ticks even if the caller's handler throws.
    try {
      const parsed = JSON.parse(e.data) as TikTokWsEvent;
      tiktokTelemetry.noteEvent();
      onMessage(parsed);
    } catch {
      /* malformed message; ignore */
    }
  };
  if (onError) ws.onerror = onError;
  if (options?.handles !== undefined) {
    ws.addEventListener('open', () => {
      try {
        ws.send(
          JSON.stringify({
            type: 'subscribe',
            handles: options.handles,
          })
        );
      } catch {
        /* WS not yet ready — ignore */
      }
    });
  }
  return ws;
}

// ─── Electron client detection ─────────────────────────────────────────────

declare global {
  interface Window {
    api?: {
      sendComment?: (text: string) => Promise<unknown>;
      login?: () => Promise<unknown>;
      logout?: () => Promise<unknown>;
      isLoggedIn?: () => Promise<boolean>;
      navigateToLive?: (username: string) => Promise<unknown>;
      /** Read the persisted TikTok session cookie + companion fields.
       *  Available only when running inside the Electron client. */
      getSessionCookies?: () => Promise<{
        session_id: string | null;
        tt_target_idc: string | null;
      }>;
    };
  }
}

export const isElectronClient = (): boolean =>
  typeof window !== 'undefined' && Boolean(window.api?.sendComment);

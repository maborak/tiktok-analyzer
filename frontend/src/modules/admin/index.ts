export { AdminQuickLogin } from './components/AdminQuickLogin';
export { adminTicketsApi } from './services/tickets';
export type * from './types';

// Public-page reuse: the unauthenticated `/lives` page renders the
// same `SubscriptionCard` with `readOnly`. `TikTokGifterDetailModal`
// is intentionally NOT re-exported here — both surfaces lazy-load it
// via `import('@admin/components/TikTokGifterDetailModal')` so the
// echarts-heavy chunk doesn't land in either main bundle. Keeping
// it out of the barrel prevents it from being statically pulled
// back into the main chunk by an unaware caller.
export { SubscriptionCard } from './pages/TikTokLives';
export type {
  TikTokSubscription,
  TikTokLiveSummary,
  TikTokLiveTopGifter,
  PublicLive,
  SubscriptionState,
  // Re-exported for the public live-detail page so `publicTiktokApi`
  // can declare the same response shapes as the admin namespace
  // without piercing the @admin/services boundary.
  TikTokRoom,
  TikTokRoomStats,
  TikTokRoomGifters,
  TikTokRoomRecipient,
  TikTokRoomRecipients,
  TikTokMatch,
  TikTokMatchOpponent,
  TikTokMatchScoreFrame,
  TikTokMatchGiftersBySide,
  TikTokMatchSideGifter,
  TikTokMatchHeadToHeadRow,
  TikTokH2HCommonGifter,
  TikTokEvent,
  TikTokGifter,
  TikTokUserMatchesResponse,
  TikTokUserMatchEntry,
} from './services/tiktok';

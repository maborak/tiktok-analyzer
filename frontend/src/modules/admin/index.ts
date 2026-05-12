export { AdminQuickLogin } from './components/AdminQuickLogin';
export { adminTicketsApi } from './services/tickets';
export type * from './types';

// Public-page reuse: the unauthenticated `/` page renders the same
// `SubscriptionCard` and `TikTokGifterDetailModal` as `/admin/tiktok`,
// with admin-side actions hidden via `readOnly`. Exposing through the
// barrel keeps the public-module → admin-internals boundary clean
// (eslint `no-restricted-imports`).
export { SubscriptionCard } from './pages/TikTokLives';
export { TikTokGifterDetailModal } from './components/TikTokGifterDetailModal';
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

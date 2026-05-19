/**
 * User-facing /tiktok/$handle detail route.
 *
 * Reuses the admin `TikTokLiveDetail` component wrapped in a
 * `TikTokApiProvider` that points at the user-scoped API namespace
 * (`/tiktok/*`). The admin component is namespace-agnostic — it pulls
 * methods via `useTikTokApi()` — so the same 5,000-line page tree
 * renders against any API shape that satisfies the read-side
 * structural subset. The user API surface mirrors
 * `publicTiktokApi` (which is already proven to drive the same
 * component on the public detail page).
 *
 * Ownership gating happens at the BACKEND route layer — every user
 * /tiktok/* endpoint verifies `owner_user_id = current_user.id`
 * before returning data. A non-owner hitting this route sees an
 * "Not in your monitors" empty state from the resolver's 404.
 */
import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokLiveDetail } from '@admin/pages/TikTokLiveDetail'
import { TikTokApiProvider } from '@admin/contexts/TikTokApiContext'
import { userTikTokApi } from '../../../modules/user/services/tiktok'

function UserTikTokDetailRoute() {
  return (
    <TikTokApiProvider value={userTikTokApi as any}>
      <TikTokLiveDetail />
    </TikTokApiProvider>
  )
}

export const Route = createLazyFileRoute('/_app/tiktok/$handle')({
  component: UserTikTokDetailRoute,
})

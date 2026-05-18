import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokAllSubscriptions } from '@admin/pages/TikTokAllSubscriptions'

export const Route = createLazyFileRoute('/_app/admin/tiktok/all-subscriptions')({
  component: TikTokAllSubscriptions,
})

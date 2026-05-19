import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokHistory } from '@admin/pages/TikTokHistory'

export const Route = createLazyFileRoute('/_app/admin/tiktok/history')({
  component: TikTokHistory,
})

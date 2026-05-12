import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokSettings } from '@admin/pages/TikTokSettings'

export const Route = createLazyFileRoute('/_app/admin/tiktok/settings')({
  component: TikTokSettings,
})

import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokDashboard } from '@admin/pages/TikTokDashboard'

export const Route = createLazyFileRoute('/_app/admin/tiktok/dashboard')({
  component: TikTokDashboard,
})

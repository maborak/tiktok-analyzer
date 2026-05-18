import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokEnigmas } from '@admin/pages/TikTokEnigmas'

export const Route = createLazyFileRoute('/_app/admin/tiktok/enigmas')({
  component: TikTokEnigmas,
})

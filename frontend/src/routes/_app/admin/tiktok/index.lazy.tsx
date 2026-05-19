import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokLives } from '@admin/pages/TikTokLives'

export const Route = createLazyFileRoute('/_app/admin/tiktok/')({
  component: TikTokLives,
})

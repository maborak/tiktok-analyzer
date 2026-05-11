import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokGifts } from '@admin/pages/TikTokGifts'

export const Route = createLazyFileRoute('/_app/admin/tiktok/gifts')({
  component: TikTokGifts,
})

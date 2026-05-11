import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokLiveDetail } from '@admin/pages/TikTokLiveDetail'

export const Route = createLazyFileRoute('/_app/admin/tiktok/$handle')({
  component: TikTokLiveDetail,
})

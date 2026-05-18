import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokPerfTraces } from '@admin/pages/TikTokPerfTraces'

export const Route = createLazyFileRoute('/_app/admin/tiktok/perf')({
  component: TikTokPerfTraces,
})

import { createLazyFileRoute } from '@tanstack/react-router'
import { TikTokSignConfig } from '@admin/pages/TikTokSignConfig'

export const Route = createLazyFileRoute('/_app/admin/tiktok/sign-config')({
  component: TikTokSignConfig,
})

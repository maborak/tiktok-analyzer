import { createLazyFileRoute } from '@tanstack/react-router'
import { UserTikTokLives } from '../../../modules/user/pages/UserTikTokLives'

export const Route = createLazyFileRoute('/_app/tiktok/')({
  component: UserTikTokLives,
})

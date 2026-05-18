import { createLazyFileRoute } from '@tanstack/react-router'
import { UserTikTokLiveDetail } from '../../../modules/user/pages/UserTikTokLiveDetail'

export const Route = createLazyFileRoute('/_app/tiktok/$handle')({
  component: UserTikTokLiveDetail,
})

import { createLazyFileRoute } from '@tanstack/react-router'
import { LiveChatAdmin } from '@admin/pages/LiveChatAdmin'

export const Route = createLazyFileRoute('/_app/admin/livechat/')({
  component: LiveChatAdmin,
})

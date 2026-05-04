import { createLazyFileRoute } from '@tanstack/react-router'
import { LiveChatAdminConsole } from '@admin/pages/LiveChatAdminConsole'

export const Route = createLazyFileRoute('/_app/admin/livechat/$id')({
  component: LiveChatAdminConsole,
})

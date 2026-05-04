import { createLazyFileRoute } from '@tanstack/react-router'
import { TicketDetail } from '@admin/pages/TicketDetail'

export const Route = createLazyFileRoute('/_app/admin/tickets/$id')({
  component: TicketDetail,
})

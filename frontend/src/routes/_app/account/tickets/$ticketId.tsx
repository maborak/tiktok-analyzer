import { createFileRoute } from '@tanstack/react-router'
import { TicketDetail } from '@user/pages/TicketDetail'

export const Route = createFileRoute('/_app/account/tickets/$ticketId')({
  component: TicketDetail,
})

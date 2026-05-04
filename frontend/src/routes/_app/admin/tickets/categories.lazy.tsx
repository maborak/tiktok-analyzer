import { createLazyFileRoute } from '@tanstack/react-router'
import { TicketCategories } from '@admin/pages/TicketCategories'

export const Route = createLazyFileRoute('/_app/admin/tickets/categories')({
  component: TicketCategories,
})

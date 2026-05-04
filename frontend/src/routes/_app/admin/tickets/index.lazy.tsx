import { createLazyFileRoute } from '@tanstack/react-router'
import { Tickets } from '@admin/pages/Tickets'

export const Route = createLazyFileRoute('/_app/admin/tickets/')({
  component: Tickets,
})

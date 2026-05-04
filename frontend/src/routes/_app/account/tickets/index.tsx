import { createFileRoute } from '@tanstack/react-router'
import { Tickets } from '@user/pages/Tickets'

export const Route = createFileRoute('/_app/account/tickets/')({
  component: Tickets,
})

import { createFileRoute } from '@tanstack/react-router'
import { Orders } from '@user/pages/billing/Orders'

export const Route = createFileRoute('/_app/account/billing/orders')({
  component: Orders,
})

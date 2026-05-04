import { createLazyFileRoute } from '@tanstack/react-router'
import { PendingPayments } from '@admin/pages/billing/PendingPayments'

export const Route = createLazyFileRoute('/_app/admin/billing/pending-payments')({
  component: PendingPayments,
})

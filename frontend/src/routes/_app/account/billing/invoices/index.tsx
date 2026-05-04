import { createFileRoute } from '@tanstack/react-router'
import { Invoices } from '@user/pages/billing/Invoices'

export const Route = createFileRoute('/_app/account/billing/invoices/')({
  component: Invoices,
})

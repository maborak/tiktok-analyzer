import { createFileRoute } from '@tanstack/react-router'
import { InvoiceDetail } from '@user/pages/billing/InvoiceDetail'

export const Route = createFileRoute('/_app/account/billing/invoices/$invoiceId')({
  component: InvoiceDetail,
})

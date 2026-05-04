import { createLazyFileRoute } from '@tanstack/react-router'
import { PaymentGateways } from '@admin/pages/billing/PaymentGateways'

export const Route = createLazyFileRoute('/_app/admin/billing/payment-gateways')({
  component: PaymentGateways,
})

import { createFileRoute } from '@tanstack/react-router'
import { PaymentSuccess } from '@user/pages/billing/PaymentSuccess'

export const Route = createFileRoute('/_app/account/billing/success')({
  component: PaymentSuccess,
})

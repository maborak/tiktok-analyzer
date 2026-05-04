import { createFileRoute } from '@tanstack/react-router'
import { CreditHistory } from '@user/pages/billing/CreditHistory'

export const Route = createFileRoute('/_app/account/billing/credit-history')({
  component: CreditHistory,
})

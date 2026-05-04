import { createFileRoute } from '@tanstack/react-router'
import { Checkout } from '@user/pages/billing/Checkout'

export const Route = createFileRoute('/_app/account/billing/checkout')({
  component: Checkout,
})

import { createFileRoute } from '@tanstack/react-router'
import { Packages } from '@user/pages/billing/Packages'

export const Route = createFileRoute('/_app/account/billing/packages')({
  component: Packages,
})

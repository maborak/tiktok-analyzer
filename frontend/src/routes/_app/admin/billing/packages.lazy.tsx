import { createLazyFileRoute } from '@tanstack/react-router'
import { Packages } from '@admin/pages/billing/Packages'

export const Route = createLazyFileRoute('/_app/admin/billing/packages')({
  component: Packages,
})

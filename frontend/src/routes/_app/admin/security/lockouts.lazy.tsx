import { createLazyFileRoute } from '@tanstack/react-router'
import { AccountLockouts } from '@admin/pages/security/AccountLockouts'

export const Route = createLazyFileRoute('/_app/admin/security/lockouts')({
  component: AccountLockouts,
})

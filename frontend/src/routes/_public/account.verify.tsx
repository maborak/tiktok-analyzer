import { createFileRoute } from '@tanstack/react-router'
import { VerifyAccount } from '@auth/pages/VerifyAccount'

export const Route = createFileRoute('/_public/account/verify')({
  component: VerifyAccount,
})

import { createFileRoute } from '@tanstack/react-router'
import { VerifyRecipient } from '@user/pages/VerifyRecipient'

export const Route = createFileRoute('/_public/account/verify-recipient')({
  component: VerifyRecipient,
})

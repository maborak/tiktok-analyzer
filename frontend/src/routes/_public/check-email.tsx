import { createFileRoute } from '@tanstack/react-router'
import { CheckEmail } from '@auth/pages/CheckEmail'

export const Route = createFileRoute('/_public/check-email')({
  component: CheckEmail,
})

import { createFileRoute } from '@tanstack/react-router'
import { ResetPassword } from '@auth/pages/ResetPassword'

export const Route = createFileRoute('/_public/account/reset-password')({
  component: ResetPassword,
})

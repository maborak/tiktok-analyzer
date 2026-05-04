import { createFileRoute } from '@tanstack/react-router'
import { ForgotPassword } from '@auth/pages/ForgotPassword'

export const Route = createFileRoute('/_auth/forgot-password')({
  component: ForgotPassword,
})

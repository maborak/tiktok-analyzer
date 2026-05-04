import { createFileRoute } from '@tanstack/react-router'
import { RegistrationSuccess } from '@auth/pages/RegistrationSuccess'

export const Route = createFileRoute('/_public/registration-success')({
  component: RegistrationSuccess,
})

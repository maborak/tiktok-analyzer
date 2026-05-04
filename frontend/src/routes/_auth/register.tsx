import { createFileRoute } from '@tanstack/react-router'
import { Register } from '@auth/pages/Register'

export const Route = createFileRoute('/_auth/register')({
  component: Register,
})

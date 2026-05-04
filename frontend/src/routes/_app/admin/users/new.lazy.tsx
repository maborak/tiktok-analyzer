import { createLazyFileRoute } from '@tanstack/react-router'
import { UserForm } from '@admin/pages/users/UserForm'

export const Route = createLazyFileRoute('/_app/admin/users/new')({
  component: UserForm,
})

import { createLazyFileRoute } from '@tanstack/react-router'
import { UsersList } from '@admin/pages/users/UsersList'

export const Route = createLazyFileRoute('/_app/admin/users/')({
  component: UsersList,
})

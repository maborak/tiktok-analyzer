import { createLazyFileRoute } from '@tanstack/react-router'
import { UserDetail } from '@admin/pages/users/UserDetail'

export const Route = createLazyFileRoute('/_app/admin/users/$id')({
  component: UserDetail,
})

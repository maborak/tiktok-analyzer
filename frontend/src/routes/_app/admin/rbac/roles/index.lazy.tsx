import { createLazyFileRoute } from '@tanstack/react-router'
import { RolesList } from '@admin/pages/rbac/RolesList'

export const Route = createLazyFileRoute('/_app/admin/rbac/roles/')({
  component: RolesList,
})

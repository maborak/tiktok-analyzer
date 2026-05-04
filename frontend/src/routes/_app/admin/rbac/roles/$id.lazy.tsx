import { createLazyFileRoute } from '@tanstack/react-router'
import { RoleDetail } from '@admin/pages/rbac/RoleDetail'

export const Route = createLazyFileRoute('/_app/admin/rbac/roles/$id')({
  component: RoleDetail,
})

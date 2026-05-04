import { createLazyFileRoute } from '@tanstack/react-router'
import { PermissionsList } from '@admin/pages/rbac/PermissionsList'

export const Route = createLazyFileRoute('/_app/admin/rbac/permissions/')({
  component: PermissionsList,
})

import { createLazyFileRoute } from '@tanstack/react-router'
import { PermissionDetail } from '@admin/pages/rbac/PermissionDetail'

export const Route = createLazyFileRoute('/_app/admin/rbac/permissions/$id')({
  component: PermissionDetail,
})

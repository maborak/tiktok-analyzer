import { createLazyFileRoute } from '@tanstack/react-router'
import { PermissionForm } from '@admin/pages/rbac/PermissionForm'

export const Route = createLazyFileRoute('/_app/admin/rbac/permissions/$id/edit')({
  component: PermissionForm,
})

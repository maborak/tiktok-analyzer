import { createLazyFileRoute } from '@tanstack/react-router'
import { RoleForm } from '@admin/pages/rbac/RoleForm'

export const Route = createLazyFileRoute('/_app/admin/rbac/roles/new')({
  component: RoleForm,
})

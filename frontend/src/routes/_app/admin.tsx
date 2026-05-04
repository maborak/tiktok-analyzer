import { createFileRoute, Outlet } from '@tanstack/react-router'
import { RequireAdmin } from '@/components/guards/RequireAdmin'

export const Route = createFileRoute('/_app/admin')({
  component: AdminLayout,
})

function AdminLayout() {
  return (
    <RequireAdmin>
      <Outlet />
    </RequireAdmin>
  )
}

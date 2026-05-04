import { createFileRoute, Outlet } from '@tanstack/react-router'
import { RequireGuest } from '@/components/guards/RequireGuest'

export const Route = createFileRoute('/_auth')({
  component: AuthLayout,
})

function AuthLayout() {
  return (
    <RequireGuest>
      <Outlet />
    </RequireGuest>
  )
}

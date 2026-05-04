import { createFileRoute, Outlet } from '@tanstack/react-router'
import { RequireAuth } from '@/components/guards/RequireAuth'

export const Route = createFileRoute('/_app/account')({
  component: AccountLayout,
})

function AccountLayout() {
  return (
    <RequireAuth>
      <Outlet />
    </RequireAuth>
  )
}

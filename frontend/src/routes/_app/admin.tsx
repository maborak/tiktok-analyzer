import { createFileRoute, Outlet } from '@tanstack/react-router'
import { RequireAdmin } from '@/components/guards/RequireAdmin'
import { TikTokFavoritesWatcher } from '@admin/components/TikTokFavoritesWatcher'
import { TikTokNotificationsCenter } from '@admin/components/TikTokNotificationsCenter'

export const Route = createFileRoute('/_app/admin')({
  component: AdminLayout,
})

function AdminLayout() {
  return (
    <RequireAdmin>
      {/* Side-effect-only: opens a single WS subscribed to every
          tracked creator and fires a toast when a favourited viewer
          gifts. Mounted at the admin shell so the alert fires on
          every admin page — TikTok tabs, live-detail, billing,
          users, settings, anything — not just /admin/tiktok. */}
      <TikTokFavoritesWatcher />
      {/* Floating bell + slide-in drawer for persistent notification
          history. Mounts the useNotifications hook (server-backed +
          localStorage cache) and surfaces unread count on the bell. */}
      <TikTokNotificationsCenter />
      <Outlet />
    </RequireAdmin>
  )
}

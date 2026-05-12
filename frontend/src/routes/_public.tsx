import { createFileRoute } from '@tanstack/react-router'
import { Layout } from '@/components/Layout'

/** Layout for unauthenticated routes (`_public/*`).
 *
 *  Uses the same `Layout` chrome (sidebar + top header) as the
 *  authenticated `_app` group. The Sidebar component itself
 *  degrades for `isAuthenticated=false`: it hides the admin /
 *  user / billing sections and renders a "Sign In / Register"
 *  button in the footer slot. So anonymous viewers at `/` still
 *  see the global "Home" entry + theme toggle + version + sign-in
 *  CTA instead of the bare Outlet they got before.
 *
 *  Auth-flow pages under this group (`auth/*`, `check-email`,
 *  `account.*`, `registration-success`) render *inside* the same
 *  chrome but already center their own card via PageShell, so
 *  they read the same as before just with the sidebar visible. */
export const Route = createFileRoute('/_public')({
  component: Layout,
})

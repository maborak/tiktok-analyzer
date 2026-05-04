import { createLazyFileRoute } from '@tanstack/react-router'
import { EventMonitor } from '@admin/pages/EventMonitor'

export const Route = createLazyFileRoute('/_app/admin/monitoring/events')({
  component: EventMonitor,
})

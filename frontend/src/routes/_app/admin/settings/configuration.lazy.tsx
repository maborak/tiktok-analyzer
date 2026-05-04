import { createLazyFileRoute } from '@tanstack/react-router'
import { Configuration } from '@admin/pages/Configuration'

export const Route = createLazyFileRoute('/_app/admin/settings/configuration')({
  component: Configuration,
})

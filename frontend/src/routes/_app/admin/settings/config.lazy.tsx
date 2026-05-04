import { createLazyFileRoute } from '@tanstack/react-router'
import { AppConfig } from '@admin/pages/AppConfig'

export const Route = createLazyFileRoute('/_app/admin/settings/config')({
  component: AppConfig,
})

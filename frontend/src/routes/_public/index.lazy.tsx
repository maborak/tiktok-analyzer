import { createLazyFileRoute } from '@tanstack/react-router'
import { Landing } from '@/modules/public/pages/Landing'

export const Route = createLazyFileRoute('/_public/')({
  component: Landing,
})

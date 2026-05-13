import { createLazyFileRoute } from '@tanstack/react-router'
import { PublicLives } from '@/modules/public/pages/PublicLives'

export const Route = createLazyFileRoute('/_public/lives/')({
  component: PublicLives,
})

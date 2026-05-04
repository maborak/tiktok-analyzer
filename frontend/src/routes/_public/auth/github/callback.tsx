import { createFileRoute } from '@tanstack/react-router'
import { GitHubCallback } from '@auth/pages/GitHubCallback'

export const Route = createFileRoute('/_public/auth/github/callback')({
  component: GitHubCallback,
})

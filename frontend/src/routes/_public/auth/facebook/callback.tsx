import { createFileRoute } from '@tanstack/react-router'
import { FacebookCallback } from '@auth/pages/FacebookCallback'

export const Route = createFileRoute('/_public/auth/facebook/callback')({
  component: FacebookCallback,
})

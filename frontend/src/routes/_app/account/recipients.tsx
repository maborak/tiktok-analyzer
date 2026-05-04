import { createFileRoute } from '@tanstack/react-router'
import { Recipients } from '@user/pages/Recipients'

export const Route = createFileRoute('/_app/account/recipients')({
  component: Recipients,
})

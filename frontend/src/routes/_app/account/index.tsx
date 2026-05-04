import { createFileRoute } from '@tanstack/react-router'
import { MyAccount } from '@user/pages/MyAccount'

export const Route = createFileRoute('/_app/account/')({
  component: MyAccount,
})

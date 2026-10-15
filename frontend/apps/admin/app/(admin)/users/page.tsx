import { AdminUsersClient } from "./AdminUsersClient"

export const metadata = {
  robots: { index: false, follow: false },
}

export default function AdminUsersPage() {
  return <AdminUsersClient />
}
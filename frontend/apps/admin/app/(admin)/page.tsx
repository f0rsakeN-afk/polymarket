import { AdminDashboardClient } from "./AdminDashboardClient"

export const metadata = {
  robots: { index: false, follow: false },
}

export default function AdminDashboardPage() {
  return <AdminDashboardClient />
}

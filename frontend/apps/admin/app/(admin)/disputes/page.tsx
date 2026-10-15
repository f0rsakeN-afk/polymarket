import { AdminDisputesClient } from "./AdminDisputesClient"

export const metadata = {
  robots: { index: false, follow: false },
}

export default function AdminDisputesPage() {
  return <AdminDisputesClient />
}
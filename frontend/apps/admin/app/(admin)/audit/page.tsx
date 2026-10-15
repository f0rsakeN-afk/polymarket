import { AdminAuditClient } from "./AdminAuditClient"

export const metadata = {
  robots: { index: false, follow: false },
}

export default function AdminAuditPage() {
  return <AdminAuditClient />
}
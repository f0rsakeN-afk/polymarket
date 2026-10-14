import { AdminShell } from "./AdminShell"

export const metadata = {
  title: "Admin",
  // An operator surface has no business in a search index.
  robots: { index: false, follow: false },
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>
}
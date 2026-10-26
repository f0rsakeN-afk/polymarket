import { AdminShell } from "@/components/admin-shell"

export default function AdminSectionLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <AdminShell>{children}</AdminShell>
}
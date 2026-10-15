import { AdminUserDetailClient } from "./AdminUserDetailClient"

export const metadata = {
  robots: { index: false, follow: false },
}

export default async function AdminUserPage({
  params,
}: {
  // Next 16: `params` is a Promise on server components and must be awaited.
  params: Promise<{ userId: string }>
}) {
  const { userId } = await params
  return <AdminUserDetailClient userId={userId} />
}
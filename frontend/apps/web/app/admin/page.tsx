import { redirect } from "next/navigation"

import { useCurrentUser } from "@/hooks/use-auth"

/**
 * `/admin` itself.
 *
 * Redirects to `/admin/users` rather than rendering its own dashboard. A landing
 * page that duplicates the first section's content is a second thing to keep
 * honest, and an operator who types `/admin` wants somewhere to start, not a
 * screen of counters they have to learn the meaning of.
 */
export default function AdminIndex() {
  return <AdminLanding />
}

function AdminLanding() {
  const { data: user, isLoading } = useCurrentUser()

  if (!isLoading) {
    if (!user?.is_admin) redirect("/")
    redirect("/admin/users")
  }
  // While loading, render nothing: redirecting to "/" on `!user` would bounce a
  // real admin out during the probe, and the auth gate deliberately does not
  // retry, so there would be no second chance.
  return null
}
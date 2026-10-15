"use client"

import { redirect } from "next/navigation"

import { useCurrentUser } from "@/hooks/use-auth"

/**
 * `/admin` itself.
 *
 * Redirects to `/users` rather than rendering its own dashboard. A landing
 * page that duplicates the first section's content is a second thing to keep
 * honest, and an operator who types this address wants somewhere to start, not a
 * screen of counters they have to learn the meaning of.
 *
 * A client component because the gate reads the session through a hook, and this
 * file spent one build failing exactly that way: as a server component calling
 * `useCurrentUser()`. The typecheck, the linter and the unit tests all accepted
 * it, and only the *production* build rejected it at prerender time.
 */
export default function AdminIndex() {
  const { data: user, isLoading } = useCurrentUser()

  // While loading, render nothing: redirecting out on `!user` would bounce a
  // real admin during the probe, and the gate does retry a transient failure -
  // so there would be a second chance, but only for blips, not for the probe
  // itself.
  if (isLoading) return null

  if (!user?.is_admin) redirect(process.env.NEXT_PUBLIC_SITE_URL ?? "/")
  redirect("/users")
}
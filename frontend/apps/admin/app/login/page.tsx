import type { Metadata } from "next"

import { AdminLoginClient } from "./AdminLoginClient"

export const metadata: Metadata = {
  title: "Sign in • Admin",
  robots: { index: false, follow: false },
}

interface LoginParams {
  /** Set by the proxy when the session is valid but the account is not an admin. */
  reason?: string
  /** Where to return to after signing in. Same-origin paths only. */
  next?: string
}

/**
 * Outside the `(admin)` route group on purpose.
 *
 * The group wraps every page in `AdminShell`, which gates on "is this account an
 * admin" and renders "Admin access required" to anyone else. A signed-out
 * operator is not an authorised non-admin — they are someone who has not signed in
 * yet, and gating the sign-in form behind the check it exists to satisfy means
 * there is no way in at all.
 */
export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<LoginParams>
}) {
  // Read on the server and passed down, rather than `useSearchParams()` in the
  // client component.
  //
  // `useSearchParams` forces a client-side bailout, and a page that opts out of
  // static prerendering has to be wrapped in a `<Suspense>` boundary to build at
  // all. Two of these values arriving as props means the login page stays
  // prerendered, the redirect decision is made before any JavaScript runs, and
  // there is no boundary to get wrong later.
  const params = await searchParams
  return <AdminLoginClient reason={params.reason} next={params.next} />
}
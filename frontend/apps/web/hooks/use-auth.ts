"use client"

import { useQuery } from "@tanstack/react-query"
import { authApi } from "@/lib/api/auth"
import { isUnauthorized } from "@/lib/api/client"
import { queryKeys } from "@/lib/api/queryKeys"

// Single source of truth: MUST be queryKeys.me() so profile mutations
// (verify-email / password change / 2FA toggle) invalidate the same cache entry.
const ME_QUERY_KEY = queryKeys.me()

/**
 * Retry `/auth/me` on a *transient* failure, never on a verdict.
 *
 * `retry: false` was correct about 401 and wrong about everything else. A 401 is
 * the server's answer - the session is gone - and retrying it is the 401 storm
 * this replaced. But a 5xx, a 429, or a dropped connection is not an answer, and
 * treating it as one is far worse than useless here, because this query is the
 * auth *gate*: every private query in the app is `enabled: !!user`. So a single
 * transient failure doesn't fail one request, it silently disables the entire
 * authenticated surface for the rest of the page's life - wallet, positions and
 * orders all sit at a spinner that never resolves, on a session that was valid
 * the whole time.
 *
 * It reproduces intermittently, which is why it survived: the same test run
 * passes, then fails with no `/wallet` request ever issued. Nothing errors, so
 * there is nothing to notice except a balance that never arrives.
 *
 * Retry budget is small and backoff-delayed. This is a metadata call on every
 * private page, not a data fetch, so the goal is to ride out a blip - not to
 * paper over an outage.
 */
function shouldRetryMe(failureCount: number, error: unknown): boolean {
  // 401/403 is a verdict, not a fault: the session is absent, expired or revoked
  // and cannot come back on its own. Asking again is how you get a refresh storm.
  if (isUnauthorized(error)) return false
  return failureCount < 3
}

export function useCurrentUser() {
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: () => authApi.me().then((r) => r.data),
    retry: shouldRetryMe,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    // Always refetch to get the authoritative answer from the server.
    // staleTime: 0 ensures the previous user data (e.g. after logout or
    // cookie change) is not shown while a fresh fetch is in flight.
    staleTime: 0,
  })
}

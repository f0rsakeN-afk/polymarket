"use client"

import { useQuery } from "@tanstack/react-query"
import { api, isUnauthorized } from "@workspace/api-client/client"

import { queryKeys } from "@/lib/queryKeys"
import type { NormalizedResponse } from "@workspace/api-client/client"

export interface MeResponse {
  id: string
  email: string
  username: string
  is_admin: boolean
}

/**
 * The session, and the only thing this app is gated on.
 *
 * Duplicated from `apps/web` rather than shared, and that is a deliberate choice
 * worth defending: the two apps have different failure modes. The consumer gate
 * failing open would show a blank wallet to a signed-in user; the admin gate
 * failing open would show an operator surface to someone who is not one. That
 * asymmetry is why the shared transport is a package and this policy is not -
 * "extract it because it is duplicated" is exactly how a safety decision gets
 * averaged away between two callers that do not mean the same thing by it.
 */
function shouldRetryMe(failureCount: number, error: unknown): boolean {
  // A 401/403 is the server's answer, not a fault: the session is gone and
  // cannot come back on its own. Asking again is how you get a refresh storm.
  if (isUnauthorized(error)) return false
  return failureCount < 3
}

export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: () =>
      api
        .get<NormalizedResponse<MeResponse>>("/api/v1/auth/me")
        .then((r) => r.data),
    // Not `retry: false`, as the consumer app's first version was. A transient
    // 5xx here must not permanently disable the gate: without a session there is
    // no admin app at all, so a blip would log an operator out mid-investigation.
    // 401/403 still does not retry.
    retry: shouldRetryMe,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    staleTime: 0,
  })
}
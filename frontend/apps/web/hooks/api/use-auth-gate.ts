"use client"
import { useCurrentUser } from "@/hooks/use-auth"

/**
 * `enabled` for any query that reads user-private data.
 *
 * Auth is cookie-based, so a 401 is the *expected* answer for a logged-out
 * visitor, not a fault worth retrying or logging. Every hook in this folder that
 * fetches private data must gate on this • `trade-form.tsx` sits on the **public**
 * market page, so its ungated wallet fetch produced a `No access token provided`
 * on every anonymous page view.
 *
 * The gate lives here rather than at each call site so a new component cannot
 * reintroduce the bug by forgetting it, and so the fix applies to every existing
 * caller at once.
 */
export function useAuthGate(): { enabled: boolean; isAuthLoading: boolean } {
  const { data: user, isLoading } = useCurrentUser()
  return { enabled: !!user, isAuthLoading: isLoading }
}

/**
 * A React Query `isLoading` that stays true while the gate is still deciding.
 *
 * A disabled query reports `isLoading: false` (it is pending but not fetching),
 * so without this an authed page would flash its empty state for the few
 * milliseconds `/auth/me` takes to answer.
 */
export function useLoadingWithGate(
  queryLoading: boolean,
  isAuthLoading: boolean,
  enabled: boolean
): boolean {
  return queryLoading || (isAuthLoading && !enabled)
}

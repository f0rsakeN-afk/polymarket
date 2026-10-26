import type { QueryClient } from "@tanstack/react-query"
import { queryKeys } from "@/lib/api/queryKeys"

/**
 * The private socket's "you may have missed something" signal.
 *
 * `/ws/notifications/{uid}` is the one feed that cannot detect its own gaps:
 * `user:{uid}:fills` and `user:{uid}:notifications` are not sequenced, so
 * there is nothing to diff a client against and no way to notice a loss locally.
 * The one moment we *know* something was missed is the reconnect itself, so the
 * hook emits this frame then and the only correct response is to re-read
 * everything the feed is responsible for keeping current.
 *
 * Centralised rather than handled per-consumer, because there are five call
 * sites with slightly different query keys and a missed one is a page that
 * silently shows stale numbers - exactly the failure this whole layer exists to
 * eliminate. Every consumer of `useUserSocket` calls this first.
 *
 * Invalidation is cheap for the keys a page does not mount: React Query only
 * refetches queries that have observers, so marking `positions` stale from the
 * notification bell costs nothing.
 *
 * Returns true when the frame was a resync, so the caller can early-return and
 * skip its own handling.
 */
export const WS_RESYNC = "__ws_resync__"

/** Everything the private feed is responsible for keeping live. */
export function applyPrivateFeedResync(qc: QueryClient, payload: unknown): boolean {
  const msg = payload as { type?: string } | null
  if (msg?.type !== WS_RESYNC) return false

  qc.invalidateQueries({ queryKey: queryKeys.positions() })
  qc.invalidateQueries({ queryKey: queryKeys.orders() })
  qc.invalidateQueries({ queryKey: queryKeys.wallet() })
  qc.invalidateQueries({ queryKey: ["notifications"] })
  return true
}
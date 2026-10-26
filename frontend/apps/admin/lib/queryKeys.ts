/**
 * Query keys for the admin app.
 *
 * Separate from `apps/web`'s on purpose: two apps, two cache roots, so a
 * shared list would invite invalidating across a boundary that means nothing.
 *
 * `adminRoot` exists so a mutation can refresh every admin list at once.
 * Without it, banning a user refreshes the list but not the detail view they are
 * looking at, and the operator sees a stale status until they navigate.
 */

export const queryKeys = {
  me: () => ["auth", "me"] as const,
  adminRoot: () => ["admin"] as const,
  /**
   * Every parameter that changes the result is in the key. `sort` was missing
   * once, and the failure was quiet: the trigger updated to the new option, the
   * component state changed, and React Query handed back the cached page for the
   * old ordering because the key still matched. The control looked like it
   * worked and did nothing.
   */
  adminUsers: (page: number, search: string, status: string, sort: string) =>
    ["admin", "users", page, search, status, sort] as const,
  adminUser: (userId: string, include?: string[]) =>
    ["admin", "user", userId, ...(include ?? [])] as const,
  /** The treasury movement history - a distinct key so invalidating the balance
   *  does not discard the list that explains it. */
  treasuryLogs: (page: number) => ["admin", "treasury-logs", page] as const,
  adminMarkets: (status: string, page: number) =>
    ["admin", "markets", status, page] as const,
  adminActions: (page: number, filters: Record<string, string | undefined>) =>
    ["admin", "actions", page, filters] as const,
  adminDisputes: (status: string, page: number, search: string) =>
    ["admin", "disputes", status, page, search] as const,
  adminDispute: (disputeId: string) => ["admin", "dispute", disputeId] as const,
  /**
   * Not under the `admin` root on purpose. A treasury read is served from
   * `GET /treasury`, which is the same read a settlement job makes - and
   * invalidating the whole admin cache would refetch every operator list because
   * a balance changed. Keyed by what it *is*, so only things that can actually
   * move a balance invalidate it.
   */
  treasury: () => ["treasury", "summary"] as const,
  /** The signed-in operator's own state — not a target record, so not `admin`. */
  sessions: () => ["auth", "sessions"] as const,
  twoFactor: () => ["auth", "2fa", "status"] as const,
}

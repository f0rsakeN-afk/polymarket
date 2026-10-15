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
  adminUsers: (page: number, search: string) =>
    ["admin", "users", page, search] as const,
  adminUser: (userId: string, include?: string[]) =>
    ["admin", "user", userId, ...(include ?? [])] as const,
  adminMarkets: (status: string, page: number) =>
    ["admin", "markets", status, page] as const,
  adminActions: (page: number, filters: Record<string, string | undefined>) =>
    ["admin", "actions", page, filters] as const,
}

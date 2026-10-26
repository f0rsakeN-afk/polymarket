import { describe, expect, it } from "vitest"
import { queryKeys } from "@/lib/api/queryKeys"

/**
 * Query keys are matched by prefix, segment for segment.
 *
 * That is the whole reason the bare form of every parametrised key must be a
 * *shorter* array rather than the same array with a hole in it. `["orders"]`
 * prefix-matches `["orders", { status: "all" }]`; `["orders", undefined]` does
 * not, because `undefined` is a value like any other and it is not that object.
 *
 * Getting this wrong is the quietest failure in the whole cache layer. Every
 * step of an update is individually correct - the socket frame arrives, the
 * handler matches its type, `invalidateQueries` is called, react-query
 * evaluates the predicate - and the net result is that nothing refreshes and
 * nothing logs. It cost the orders page its entire private feed for exactly
 * that reason: users were filled and the page never moved.
 *
 * It also meant `removeQueries` on logout matched nothing, so the previous
 * user's orders and notifications stayed in the cache, readable by whoever
 * signed in next on the same browser.
 *
 * So these are asserted against react-query's own matcher rather than against
 * how the keys look. A key that is missing a segment and a key with an
 * `undefined` segment read almost identically in a diff; only one of them works.
 */

// The subset of keys that take an optional trailing argument, and a
// representative parameterised form of each.
const PARAMETRISED: Array<{
  name: string
  bare: () => readonly unknown[]
  scoped: (...args: never[]) => readonly unknown[]
  args: readonly unknown[]
}> = [
  {
    name: "markets",
    bare: queryKeys.markets as () => readonly unknown[],
    scoped: queryKeys.markets as (...a: never[]) => readonly unknown[],
    args: [{ category: "crypto" }],
  },
  {
    name: "orders",
    bare: queryKeys.orders as () => readonly unknown[],
    scoped: queryKeys.orders as (...a: never[]) => readonly unknown[],
    args: [{ status: "all" }],
  },
  {
    name: "notifications",
    bare: queryKeys.notifications as () => readonly unknown[],
    scoped: queryKeys.notifications as (...a: never[]) => readonly unknown[],
    args: [{ page: 1, page_size: 30 }],
  },
  {
    name: "globalTrades",
    bare: queryKeys.globalTrades as () => readonly unknown[],
    scoped: queryKeys.globalTrades as (...a: never[]) => readonly unknown[],
    args: ["bitcoin-100k-2024"],
  },
  {
    name: "treasuryLogs",
    bare: queryKeys.treasuryLogs as () => readonly unknown[],
    scoped: queryKeys.treasuryLogs as (...a: never[]) => readonly unknown[],
    args: [{ page: 2 }],
  },
  {
    name: "priceHistory",
    bare: () => queryKeys.priceHistory("bitcoin-100k-2024"),
    scoped: queryKeys.priceHistory as (...a: never[]) => readonly unknown[],
    args: ["bitcoin-100k-2024", "1d"],
  },
]

/** react-query's `partialMatchKey`: is `partial` a prefix of `key`? */
function partialMatchKey(partial: readonly unknown[], key: readonly unknown[]): boolean {
  if (partial.length > key.length) return false
  return partial.every((segment, i) =>
    typeof segment === "object" && segment !== null
      ? Object.is(segment, key[i])
      : Object.is(segment, key[i]),
  )
}

describe("queryKeys", () => {
  describe.each(PARAMETRISED)("$name", ({ bare, scoped, args }) => {
    it("matches its own parameterised form when called with no params", () => {
      // This is the assertion that failed silently in production. The bare key is
      // what every `invalidateQueries({ queryKey: queryKeys.x() })` call site
      // passes, and it has to reach queries that *were* created with params.
      expect(partialMatchKey(bare(), scoped(...(args as never[])))).toBe(true)
    })

    it("omits the segment rather than emitting undefined", () => {
      expect(bare()).not.toContain(undefined)
      expect(bare()).toHaveLength(scoped(...(args as never[])).length - 1)
    })
  })

  it("keeps market keys distinct per filter, so filtered caches do not collide", () => {
    // Dropping the segment must not collapse distinct queries onto one key:
    // "all markets" and "crypto only" are different data with different
    // freshness, and sharing a cache entry would serve one as the other.
    const crypto = queryKeys.markets({ category: "crypto" })
    const sports = queryKeys.markets({ category: "sports" })
    expect(crypto).not.toEqual(sports)
    expect(crypto).not.toEqual(queryKeys.markets())
  })

  it("prefix-matches the orders key used by the private-feed invalidation", () => {
    // Spelled out against the real page query, because this pairing is the
    // regression that made /orders look broken: the page queries
    // `orders({ status: "all" })` and invalidates `orders()`.
    const pageQuery = queryKeys.orders({ status: "all" })
    expect(partialMatchKey(queryKeys.orders(), pageQuery)).toBe(true)
  })

  it("does not let the bare key match a different resource", () => {
    // The flip side: prefix matching must not be so loose that invalidating
    // orders also nukes order detail, which is fetched fresh on navigation.
    expect(partialMatchKey(queryKeys.orders(), [queryKeys.order("abc")])).toBe(false)
  })
})
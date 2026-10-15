// Typed query key factory • use these instead of inline arrays in hooks

export const queryKeys = {
  // Auth
  me: () => ["auth", "me"] as const,
  sessions: () => ["auth", "sessions"] as const,
  twoFactorStatus: () => ["auth", "2fa", "status"] as const,

  // Account
  deletionImpact: () => ["account", "deletion-impact"] as const,

  // Admin query keys live in `apps/admin`, which owns them. Duplicating
  // them here would be two lists to keep in step, and the admin app has no
  // use for the consumer keys above.

  // Markets
  /**
 * Params are omitted from the key entirely when absent - never `undefined`.
 *
 * `["orders", undefined]` looks interchangeable with `["orders"]` and is not.
 * react-query matches keys by prefix, segment for segment, and `undefined`
 * does not equal `{ status: "all" }`. So a helper called with no params
 * produces a key that cannot prefix-match any real query, and
 * `invalidateQueries`/`removeQueries` against it silently matches nothing
 * while appearing to have worked.
 *
 * That is not theoretical. It cost the orders page its entire private feed:
 * a fill arrived, the handler matched it, and the invalidation targeted a key
 * no query in the app could ever have - so the page never updated and nothing
 * errored, because every individual step was correct. It also meant logout
 * failed to clear the orders and notifications caches, leaving the previous
 * user's data readable by the next user of a shared browser.
 *
 * The bare `["orders"]` is the correct spelling of "every orders query,
 * whatever its filters", which is what these call sites always mean.
 */
  markets: (p?: Record<string, unknown>) =>
    p ? (["markets", p] as const) : (["markets"] as const),
  market: (slug: string) => ["market", slug] as const,
  marketActivity: (slug: string) => ["market-activity", slug] as const,
  marketTrades: (slug: string) => ["market-trades", slug] as const,
  globalTrades: (marketSlug?: string) =>
    marketSlug ? (["global-trades", marketSlug] as const) : (["global-trades"] as const),
  // Non-infinite variants of the same feeds • MUST be distinct keys from the
  // infinite queries above: they cache a single page object, not {pages, pageParams}.
  // The "…", "simple" segment keeps them out of each other's exact-key lookups while
  // still matching prefix invalidations like ["market-trades"].
  marketTradesPage: (slug: string, params?: Record<string, unknown>) =>
    ["market-trades", slug, "simple", params] as const,
  globalTradesPage: (marketSlug?: string, params?: Record<string, unknown>) =>
    ["global-trades", marketSlug, "simple", params] as const,
  comments: (slug: string) => ["comments", slug] as const,
  faqs: (slug: string) => ["faqs", slug] as const,
  relatedMarkets: (slug: string) => ["related-markets", slug] as const,
  priceHistory: (slug: string, interval?: string) =>
    interval ? (["price-history", slug, interval] as const) : (["price-history", slug] as const),
  marketCategories: () => ["market-categories"] as const,
  orderBook: (slug: string) => ["orderbook", slug] as const,

  // Orders
  /** See `markets` - same prefix-matching trap, and it cost the orders feed. */
  orders: (p?: Record<string, unknown>) =>
    p ? (["orders", p] as const) : (["orders"] as const),
  order: (id: string) => ["order", id] as const,
  quote: (key: string) => ["quote", key] as const,

  // Wallet
  wallet: () => ["wallet"] as const,
  transactions: () => ["transactions"] as const,

  // Positions
  positions: () => ["positions"] as const,

  // Trades
  trades: () => ["trades"] as const,

  // Notifications
  notifications: (params?: Record<string, unknown>) =>
    params ? (["notifications", params] as const) : (["notifications"] as const),
  notificationPreferences: () => ["notification-preferences"] as const,

  // Alerts
  alerts: () => ["alerts"] as const,

  // Disputes
  disputes: (marketId?: string) => (marketId ? (["disputes", marketId] as const) : (["disputes"] as const)),

  // Flags
  flags: (marketId?: string) => (marketId ? (["flags", marketId] as const) : (["flags"] as const)),

  // Liquidity
  lpAnalytics: () => ["lp-analytics"] as const,
  lpPosition: (marketId: string) => ["lp-position", marketId] as const,

  // Split/Merge
  splitMerge: () => ["split-merge"] as const,

  // Referrals
  referrals: () => ["referrals"] as const,
  referralCode: () => ["referral-code"] as const,
  referralStats: () => ["referral-stats"] as const,

  // Treasury
  treasury: () => ["treasury"] as const,
  treasuryLogs: (params?: Record<string, unknown>) =>
    params ? (["treasury-logs", params] as const) : (["treasury-logs"] as const),
} as const

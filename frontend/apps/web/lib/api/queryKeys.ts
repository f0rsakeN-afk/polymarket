// Typed query key factory — use these instead of inline arrays in hooks

export const queryKeys = {
  // Auth
  me: () => ["auth", "me"] as const,
  sessions: () => ["auth", "sessions"] as const,
  twoFactorStatus: () => ["auth", "2fa", "status"] as const,

  // Markets
  markets: (params?: Record<string, unknown>) => ["markets", params] as const,
  market: (slug: string) => ["market", slug] as const,
  marketActivity: (slug: string) => ["market-activity", slug] as const,
  marketTrades: (slug: string) => ["market-trades", slug] as const,
  globalTrades: (marketSlug?: string) => ["global-trades", marketSlug] as const,
  comments: (slug: string) => ["comments", slug] as const,
  faqs: (slug: string) => ["faqs", slug] as const,
  relatedMarkets: (slug: string) => ["related-markets", slug] as const,
  priceHistory: (slug: string, interval?: string) => ["price-history", slug, interval] as const,
  marketCategories: () => ["market-categories"] as const,
  orderBook: (slug: string) => ["orderbook", slug] as const,

  // Orders
  orders: (filters?: Record<string, unknown>) => ["orders", filters] as const,
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
  notifications: (params?: Record<string, unknown>) => ["notifications", params] as const,
  notificationPreferences: () => ["notification-preferences"] as const,

  // Alerts
  alerts: () => ["alerts"] as const,

  // Disputes
  disputes: (marketId: string) => ["disputes", marketId] as const,

  // Flags
  flags: (marketId: string) => ["flags", marketId] as const,

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
  treasuryLogs: (params?: Record<string, unknown>) => ["treasury-logs", params] as const,
} as const

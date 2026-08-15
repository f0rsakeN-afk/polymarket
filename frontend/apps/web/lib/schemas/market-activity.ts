import { z } from "zod"

export const holderSchema = z.object({
  user_id: z.string(),
  username: z.string(),
  shares_held: z.string(), // ponytail: string — Decimal serialized from backend
  average_price: z.string(), // ponytail: string — Decimal serialized from backend
  realized_pnl: z.string(), // ponytail: string — Decimal serialized from backend
})

export const marketStatsSchema = z.object({
  total_volume: z.string(), // ponytail: string — Decimal serialized from backend
  total_liquidity: z.string(), // ponytail: string — Decimal serialized from backend
  num_trades: z.string(), // ponytail: string — Decimal serialized from backend
  yes_price: z.string(), // ponytail: string — Decimal serialized from backend
  no_price: z.string(), // ponytail: string — Decimal serialized from backend
  spread: z.string(), // ponytail: string — Decimal serialized from backend
  yes_liquidity: z.string(), // ponytail: string — Decimal serialized from backend
  no_liquidity: z.string(), // ponytail: string — Decimal serialized from backend
  status: z.string(),
})

export const marketTradeSchema = z.object({
  id: z.string(),
  outcome: z.string(),
  side: z.string(),
  price: z.string(), // ponytail: string — Decimal serialized from backend
  amount: z.string(), // ponytail: string — Decimal serialized from backend
  executed_at: z.string(),
  username: z.string(),
})

export const commentActivitySchema = z.object({
  id: z.string(),
  user_id: z.string(),
  username: z.string(),
  content: z.string(),
  depth: z.number(),
  created_at: z.string(),
})

export const marketActivitySchema = z.object({
  market_stats: marketStatsSchema,
  top_holders_by_outcome: z.record(z.string(), z.array(holderSchema)),
  recent_trades: z.array(marketTradeSchema),
  recent_comments: z.array(commentActivitySchema),
})

export type Holder = z.infer<typeof holderSchema>
export type MarketStats = z.infer<typeof marketStatsSchema>
export type MarketTrade = z.infer<typeof marketTradeSchema>
export type CommentActivity = z.infer<typeof commentActivitySchema>
export type MarketActivity = z.infer<typeof marketActivitySchema>

import { z } from "zod"

export const holderSchema = z.object({
  user_id: z.string(),
  username: z.string(),
  shares_held: z.number(),
  average_price: z.number(),
  realized_pnl: z.number(),
})

export const marketStatsSchema = z.object({
  total_volume: z.number(),
  total_liquidity: z.number(),
  num_trades: z.number(),
  yes_price: z.number(),
  no_price: z.number(),
  spread: z.number(),
  yes_liquidity: z.number(),
  no_liquidity: z.number(),
  status: z.string(),
})

export const marketTradeSchema = z.object({
  id: z.string(),
  outcome: z.string(),
  side: z.string(),
  price: z.number(),
  amount: z.number(),
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

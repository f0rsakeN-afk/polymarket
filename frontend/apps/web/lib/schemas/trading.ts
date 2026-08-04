import { z } from "zod"

export const placeOrderSchema = z.object({
  market_id: z.string(),
  outcome: z.string(),
  side: z.enum(["buy", "sell"]),
  order_type: z.enum(["market", "limit", "fill_or_kill"]),
  amount: z.number().min(0.01),
  price: z.number().min(0.001).max(0.999).optional(),
  post_only: z.boolean(),
  expires_at: z.string().optional(),
  client_order_id: z.string().optional(),
  max_slippage: z.number().min(0.001).max(0.5),
  min_shares_out: z.number().min(0).optional(),
  quote_id: z.string().optional(),
})

export const depositSchema = z.object({
  amount: z.number().min(1),
})

export const withdrawSchema = z.object({
  amount: z.number().min(1),
})

export type PlaceOrderInput = z.infer<typeof placeOrderSchema>
export type DepositInput = z.infer<typeof depositSchema>
export type WithdrawInput = z.infer<typeof withdrawSchema>

import { z } from "zod"

// ─── Place Order ──────────────────────────────────────────────────────────────

export const placeOrderSchema = z.object({
  market_id: z.string(),
  outcome: z.string(),
  side: z.enum(["buy", "sell"]),
  order_type: z.enum(["market", "limit", "fill_or_kill"]),
  amount: z.number().min(0.00000001),
  price: z.number().min(0).max(1).nullable().optional(),
  post_only: z.boolean(),
  expires_at: z.string().optional(),
  client_order_id: z.string().optional(),
  max_slippage: z.number().min(0).max(1).optional(),
  min_shares_out: z.number().min(0).optional(),
  quote_id: z.string().optional(),
})

export type PlaceOrderInput = z.infer<typeof placeOrderSchema>

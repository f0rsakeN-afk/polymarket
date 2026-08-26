import { z } from "zod"
export { z }

// Accept both string (API response) and number (form input)
// Conversion to backend string format happens in the API layer
const moneyField = z.union([z.string(), z.number()])

export const placeOrderSchema = z.object({
  market_id: z.string(),
  outcome: z.string(),
  side: z.enum(["buy", "sell"]),
  order_type: z.enum(["market", "limit", "fill_or_kill"]).default("market"),
  amount: moneyField,
  price: moneyField.nullable().optional(),
  post_only: z.boolean().default(false),
  expires_at: z.string().optional(),
  client_order_id: z.string().optional(),
  max_slippage: moneyField.optional(),
  min_shares_out: moneyField.optional(),
  quote_id: z.string().optional(),
})

export type PlaceOrderInput = z.infer<typeof placeOrderSchema>

import { z } from "zod"

// Backend Decimal fields are serialized as strings
const moneyField = z.string()

export const getQuoteSchema = z.object({
  market_id: z.string(),
  outcome: z.string(),
  side: z.enum(["buy", "sell"]),
  amount: z.string().min(1, "Amount must be greater than 0"),
})

/**
 * POST /api/v1/orders/quote payload • mirrors
 * hooks/api/types/order.ts::QuoteResponse (OrderService.compute_quote).
 * Kept in sync manually; there is no `price` field.
 */
export const quoteResponseSchema = z.object({
  quote_id: z.string(),
  user_id: z.string(),
  market_id: z.string(),
  outcome: z.string(),
  side: z.string(),
  amount: moneyField,
  price_before: moneyField,
  price_after: moneyField,
  slippage: moneyField,
  yes_price: moneyField,
  no_price: moneyField,
  expires_at: z.number(), // unix timestamp float
})

export type GetQuoteInput = z.infer<typeof getQuoteSchema>
export type QuoteResponse = z.infer<typeof quoteResponseSchema>

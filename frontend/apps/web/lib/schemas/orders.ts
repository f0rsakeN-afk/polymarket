import { z } from "zod"

export const placeOrderSchema = z.object({
  market_id: z.string(),
  outcome: z.string().default("yes"),
  side: z.enum(["buy", "sell"]).default("buy"),
  order_type: z.enum(["market", "limit", "fill_or_kill"]).default("market"),
  amount: z.number().min(0.01),
  price: z.number().min(0.001).max(0.999).optional(),
  expires_at: z.string().optional(),
  post_only: z.boolean().default(false),
  client_order_id: z.string().optional(),
  max_slippage: z.number().min(0).max(1).optional(),
  min_shares_out: z.number().min(0).optional(),
  quote_id: z.string().optional(),
})

export const cancelOrderSchema = z.object({})

export const listOrdersSchema = z.object({
  page: z.number().int().positive().optional(),
  page_size: z.number().int().positive().max(100).optional(),
  status: z.string().optional(),
  side: z.string().optional(),
  order_type: z.string().optional(),
  market_id: z.string().optional(),
  date_from: z.string().optional(),
  date_to: z.string().optional(),
})

export const getQuoteSchema = z.object({
  market_id: z.string(),
  outcome: z.string(),
  side: z.enum(["buy", "sell"]),
  amount: z.number().min(0.01),
})

export type PlaceOrderInput = z.infer<typeof placeOrderSchema>
export type ListOrdersInput = z.infer<typeof listOrdersSchema>
export type GetQuoteInput = z.infer<typeof getQuoteSchema>

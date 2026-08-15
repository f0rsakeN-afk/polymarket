import { z } from "zod"

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
  amount: z.string(), // ponytail: string — Decimal serialized from backend
})

export const orderResponseSchema = z.object({
  id: z.string(),
  market_id: z.string(),
  outcome: z.string(),
  side: z.string(),
  order_type: z.string(),
  status: z.string(),
  amount: z.string(), // ponytail: string — Decimal serialized from backend
  price: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  filled_amount: z.string(), // ponytail: string — Decimal serialized from backend
  avg_fill_price: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  quote_id: z.string().nullable(),
  client_order_id: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  expires_at: z.string().nullable(),
})

export const quoteResponseSchema = z.object({
  quote_id: z.string(),
  market_id: z.string(),
  outcome: z.string(),
  side: z.string(),
  amount: z.string(), // ponytail: string — Decimal serialized from backend
  price: z.string(), // ponytail: string — Decimal serialized from backend
  min_shares_out: z.string(), // ponytail: string — Decimal serialized from backend
  max_slippage: z.string(), // ponytail: string — Decimal serialized from backend
  expires_at: z.string(),
  created_at: z.string(),
})

export type ListOrdersInput = z.infer<typeof listOrdersSchema>
export type GetQuoteInput = z.infer<typeof getQuoteSchema>
export type OrderResponse = z.infer<typeof orderResponseSchema>
export type QuoteResponse = z.infer<typeof quoteResponseSchema>

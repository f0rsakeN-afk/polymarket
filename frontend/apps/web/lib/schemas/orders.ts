import { z } from "zod"

// Backend Decimal fields are serialized as strings
const moneyField = z.string()
const positiveMoney = z.string()

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
  amount: z.string().min(1, "Amount must be greater than 0"),
})

export const quoteResponseSchema = z.object({
  quote_id: z.string(),
  market_id: z.string(),
  outcome: z.string(),
  side: z.string(),
  amount: moneyField,
  price: moneyField,
  slippage: moneyField,
  yes_price: moneyField,
  no_price: moneyField,
  expires_at: z.number(), // unix timestamp float
})

export const orderResponseSchema = z.object({
  id: z.string(),
  market_id: z.string(),
  outcome: z.string(),
  side: z.string(),
  order_type: z.string(),
  status: z.string(),
  amount: moneyField,
  price: moneyField.nullable(),
  shares_bought: moneyField.nullable().optional(),
  shares_sold: moneyField.nullable().optional(),
  fee: moneyField.nullable().optional(),
  quote_id: z.string().nullable().optional(),
  client_order_id: z.string().nullable().optional(),
  created_at: z.string(),
  expires_at: z.string().nullable().optional(),
})

export type ListOrdersInput = z.infer<typeof listOrdersSchema>
export type GetQuoteInput = z.infer<typeof getQuoteSchema>
export type OrderResponse = z.infer<typeof orderResponseSchema>
export type QuoteResponse = z.infer<typeof quoteResponseSchema>

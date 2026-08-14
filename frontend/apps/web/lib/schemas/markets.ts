import { z } from "zod"

export const listMarketsSchema = z.object({
  q: z.string().optional(),
  category: z.string().optional(),
  status: z.string().optional(),
  page: z.number().int().positive().optional(),
  page_size: z.number().int().positive().max(100).optional(),
})

export const marketResponseSchema = z.object({
  id: z.string(),
  slug: z.string(),
  question: z.string(),
  description: z.string(),
  category: z.string(),
  subcategory: z.string().nullable(),
  image_url: z.string().nullable(),
  currency: z.string(),
  market_slug: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  resolved_at: z.string().nullable(),
  closing_date: z.string().nullable(),
  market_type: z.string(),
  price_low: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  price_high: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  question_details: z.string().nullable(),
  tags: z.array(z.string()),
  total_volume: z.string(), // ponytail: string — Decimal serialized from backend
  liquidity: z.string(), // ponytail: string — Decimal serialized from backend
  num_scopes: z.number().int(),
  spread: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  yes_price: z.string(), // ponytail: string — Decimal serialized from backend
  no_price: z.string(), // ponytail: string — Decimal serialized from backend
  status: z.string(),
  outcomes: z.array(z.string()),
  outcome_prices: z.record(z.string(), z.string()), // ponytail: string — Decimal serialized from backend
  my_shares: z.record(z.string(), z.string()).nullable(), // ponytail: string — Decimal serialized from backend
  is_watched: z.boolean(),
  user_max_win: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  user_max_loss: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  last_trade: z.string().nullable(), // ponytail: string — Decimal serialized from backend
})

export const marketDetailResponseSchema = z.object({
  id: z.string(),
  slug: z.string(),
  question: z.string(),
  description: z.string(),
  category: z.string(),
  subcategory: z.string().nullable(),
  image_url: z.string().nullable(),
  currency: z.string(),
  market_slug: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  resolved_at: z.string().nullable(),
  closing_date: z.string().nullable(),
  market_type: z.string(),
  price_low: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  price_high: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  question_details: z.string().nullable(),
  tags: z.array(z.string()),
  total_volume: z.string(), // ponytail: string — Decimal serialized from backend
  liquidity: z.string(), // ponytail: string — Decimal serialized from backend
  num_scopes: z.number().int(),
  spread: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  yes_price: z.string(), // ponytail: string — Decimal serialized from backend
  no_price: z.string(), // ponytail: string — Decimal serialized from backend
  status: z.string(),
  outcomes: z.array(z.string()),
  outcome_prices: z.record(z.string(), z.string()), // ponytail: string — Decimal serialized from backend
  my_shares: z.record(z.string(), z.string()).nullable(), // ponytail: string — Decimal serialized from backend
  is_watched: z.boolean(),
  user_max_win: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  user_max_loss: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  last_trade: z.string().nullable(), // ponytail: string — Decimal serialized from backend
  faqs: z.array(z.object({
    question: z.string(),
    answer: z.string(),
  })).optional(),
})

export const priceHistoryPointSchema = z.object({
  timestamp: z.string(),
  price: z.string(), // ponytail: string — Decimal serialized from backend
  volume: z.string(), // ponytail: string — Decimal serialized from backend
})

export const faqSchema = z.object({
  question: z.string(),
  answer: z.string(),
})

export type ListMarketsInput = z.infer<typeof listMarketsSchema>
export type MarketResponse = z.infer<typeof marketResponseSchema>
export type MarketDetailResponse = z.infer<typeof marketDetailResponseSchema>
export type PriceHistoryPoint = z.infer<typeof priceHistoryPointSchema>
export type FAQ = z.infer<typeof faqSchema>

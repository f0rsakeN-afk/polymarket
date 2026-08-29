import { z } from "zod"

// ─── Market List Query ─────────────────────────────────────────────────────────

export const listMarketsSchema = z.object({
  q: z.string().optional(),
  category: z.string().optional(),
  status: z.string().optional(),
  sort: z.string().optional(),
  page: z.number().int().positive().optional(),
  page_size: z.number().int().positive().max(100).optional(),
})

// ─── Backend-aligned response schemas ─────────────────────────────────────────

export const outcomeResponseSchema = z.object({
  id: z.string(),
  name: z.string(),
  outcome_index: z.number().int().min(0).max(1),
})

export const marketResponseSchema = z.object({
  id: z.string(),
  slug: z.string(),
  question: z.string(),
  description: z.string().nullable(),
  category: z.string().nullable(),
  status: z.string(),
  total_liquidity: z.string(), // Decimal → string
  total_volume: z.string(),    // Decimal → string
  yes_price: z.string(),       // Decimal → string
  no_price: z.string(),         // Decimal → string
  closes_at: z.string().datetime(),
  winning_outcome_id: z.string().nullable(),
  winning_outcome_name: z.string().nullable(),
  outcomes: z.array(outcomeResponseSchema).nullable(),
})

export const marketDetailResponseSchema = marketResponseSchema.extend({
  spread: z.string(),      // Decimal → string
  created_at: z.string().datetime(),
})

export const priceHistoryPointSchema = z.object({
  timestamp: z.string(),
  outcomes: z.array(z.object({
    id: z.string(),
    name: z.string(),
    price: z.string(),
  })),
  total_volume: z.string(),
})

export const faqSchema = z.object({
  id: z.string(),
  question: z.string(),
  answer: z.string(),
  display_order: z.number().int(),
})

export const faqsResponseSchema = z.object({
  success: z.literal(true).default(true),
  data: z.array(faqSchema),
})

// ─── Order Book (frontend-specific) ─────────────────────────────────────────

export const orderBookEntrySchema = z.object({
  price: z.string(),
  size: z.string(),
})

export const orderBookSchema = z.object({
  outcomes: z.record(z.string(), z.object({
    bids: z.array(orderBookEntrySchema),
    asks: z.array(orderBookEntrySchema),
  })),
})

// ─── Create / Resolve ─────────────────────────────────────────────────────────

export const marketOutcomeCreateSchema = z.object({
  name: z.string().min(1).max(100),
  outcome_index: z.number().int().min(0).max(1),
})

export const createMarketRequestSchema = z.object({
  question: z.string().min(5).max(1000),
  description: z.string().max(5000).optional(),
  category: z.string().max(100).optional(),
  slug: z.string().min(3).max(255),
  closes_at: z.string().datetime(),
  initial_liquidity: z.string().optional(), // Decimal, ge=0
  initial_probability: z.string().optional(), // Decimal, ge=0.01, le=0.99
  outcomes_create: z.array(marketOutcomeCreateSchema).optional(),
})

export const resolveMarketRequestSchema = z.object({
  winning_outcome_id: z.string(),
})

export const claimResponseSchema = z.object({
  claimed: z.string(),
})

// ─── Types ─────────────────────────────────────────────────────────────────────

export type ListMarketsInput = z.infer<typeof listMarketsSchema>
export type MarketResponse = z.infer<typeof marketResponseSchema>
export type MarketDetailResponse = z.infer<typeof marketDetailResponseSchema>
export type PriceHistoryPoint = z.infer<typeof priceHistoryPointSchema>
export type FAQ = z.infer<typeof faqSchema>
export type CreateMarketInput = z.infer<typeof createMarketRequestSchema>
export type ResolveMarketInput = z.infer<typeof resolveMarketRequestSchema>
export type ClaimResponse = z.infer<typeof claimResponseSchema>

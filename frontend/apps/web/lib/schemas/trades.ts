import { z } from "zod"

export const tradeSchema = z.object({
  id: z.string(),
  market_id: z.string(),
  market_slug: z.string(),
  market_question: z.string(),
  outcome: z.string(),
  side: z.string(),
  price: z.number(),
  amount: z.number(),
  executed_at: z.string().datetime(),
  username: z.string(),
})

export const listTradesSchema = z.object({
  page: z.number().int().positive().optional(),
  page_size: z.number().int().positive().max(100).optional(),
  market_slug: z.string().optional(),
})

export type Trade = z.infer<typeof tradeSchema>
export type ListTradesInput = z.infer<typeof listTradesSchema>

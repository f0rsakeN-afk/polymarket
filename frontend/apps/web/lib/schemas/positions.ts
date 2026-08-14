import { z } from "zod"

export const listPositionsSchema = z.object({
  page: z.number().int().positive().optional(),
  page_size: z.number().int().positive().max(100).optional(),
})

export const positionResponseSchema = z.object({
  id: z.string(),
  market_id: z.string(),
  market_question: z.string().nullable(),
  outcome: z.string(),
  shares_held: z.string(), // ponytail: string — Decimal serialized from backend
  average_price: z.string(), // ponytail: string — Decimal serialized from backend
  realized_pnl: z.string(), // ponytail: string — Decimal serialized from backend
  unrealized_pnl: z.string(), // ponytail: string — Decimal serialized from backend
})

export type ListPositionsInput = z.infer<typeof listPositionsSchema>
export type PositionResponse = z.infer<typeof positionResponseSchema>

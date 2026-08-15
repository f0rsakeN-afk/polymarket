import { z } from "zod"

export const createAlertSchema = z.object({
  market_id: z.string(),
  outcome: z.enum(["yes", "no"]).optional(),
  condition: z.enum(["above", "below"]),
  trigger_price: z.string(), // ponytail: string — Decimal serialized from backend
})

export type CreateAlertInput = z.infer<typeof createAlertSchema>

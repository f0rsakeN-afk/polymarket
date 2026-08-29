import { z } from "zod"

export const createAlertSchema = z.object({
  market_id: z.string(),
  outcome: z.enum(["yes", "no"]).optional(),
  condition: z.enum(["above", "below"]),
  trigger_price: z.string(),
})

export type CreateAlertInput = z.infer<typeof createAlertSchema>

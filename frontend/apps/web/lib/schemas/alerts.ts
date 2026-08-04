import { z } from "zod"

export const createAlertSchema = z.object({
  market_id: z.string(),
  outcome: z.enum(["yes", "no"]).optional(),
  condition: z.enum(["above", "below"]),
  trigger_price: z.number().min(0.01, "Min 0.01").max(0.99, "Max 0.99"),
})

export type CreateAlertInput = z.infer<typeof createAlertSchema>

import { z } from "zod"

// ─── Flags ────────────────────────────────────────────────────────────────────

export const createFlagSchema = z.object({
  market_id: z.string(),
  reason: z.string().min(5).max(1000),
})

export const flagResponseSchema = z.object({
  id: z.string(),
  market_id: z.string(),
  user_id: z.string(),
  reason: z.string(),
  status: z.string(),
  created_at: z.string(),
})

export const resolveFlagSchema = z.object({
  status: z.enum(["resolved", "dismissed"]),
})

export type CreateFlagInput = z.infer<typeof createFlagSchema>
export type FlagResponse = z.infer<typeof flagResponseSchema>
export type ResolveFlagInput = z.infer<typeof resolveFlagSchema>

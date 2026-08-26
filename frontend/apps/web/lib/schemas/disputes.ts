import { z } from "zod"

// ─── Disputes ─────────────────────────────────────────────────────────────────

export const createDisputeSchema = z.object({
  market_id: z.string().min(1),
  evidence: z.string().min(10).max(5000),
  evidence_url: z.string().url().max(1000).optional(),
})

export const disputeResponseSchema = z.object({
  id: z.string(),
  market_id: z.string(),
  user_id: z.string(),
  evidence: z.string(),
  evidence_url: z.string().nullable(),
  status: z.string(),
  created_at: z.string(),
})

export const proposeResolutionSchema = z.object({
  market_id: z.string().min(1),
  outcome_id: z.string().min(1),
  resolution_source: z.string().min(10).max(1000),
})

export const adjudicateDisputeSchema = z.object({
  ruling: z.enum(["upheld", "dismissed"]),
  admin_note: z.string().max(2000).optional(),
})

export type CreateDisputeInput = z.infer<typeof createDisputeSchema>
export type DisputeResponse = z.infer<typeof disputeResponseSchema>
export type ProposeResolutionInput = z.infer<typeof proposeResolutionSchema>
export type AdjudicateDisputeInput = z.infer<typeof adjudicateDisputeSchema>

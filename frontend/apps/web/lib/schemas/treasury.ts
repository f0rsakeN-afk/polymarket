import { z } from "zod"

// ─── Treasury ────────────────────────────────────────────────────────────────

const moneyField = z.string()

export const treasuryResponseSchema = z.object({
  id: z.string(),
  balance: moneyField,
  total_fees_collected: moneyField,
  total_fees_distributed: moneyField,
})

export const treasuryLogResponseSchema = z.object({
  id: z.string(),
  event: z.string(),
  amount: moneyField,
  reference_type: z.string().nullable(),
  reference_id: z.string().nullable(),
  created_at: z.string(),
})

export type TreasuryResponse = z.infer<typeof treasuryResponseSchema>
export type TreasuryLogResponse = z.infer<typeof treasuryLogResponseSchema>

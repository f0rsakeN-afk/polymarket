import { z } from "zod"

// marketId goes in the URL path, not the body — backend AddLiquidityRequest only has 'amount'
// Accept both string (form input) and number (parseFloat result) — backend Decimal coerces either
export const addLiquiditySchema = z.object({
  amount: z.union([z.string(), z.number()]),
})

// marketId goes in the URL path, not the body — backend RemoveLiquidityRequest only has 'lp_tokens'
export const removeLiquiditySchema = z.object({
  lp_tokens: z.union([z.string(), z.number()]),
})

export const lpPositionResponseSchema = z.object({
  lp_tokens: z.string(), // ponytail: string — Decimal serialized from backend
  collateral_deposited: z.string(), // ponytail: string — Decimal serialized from backend
  pool_lp_token_supply: z.string(), // ponytail: string — Decimal serialized from backend
  pool_yes_shares: z.string(), // ponytail: string — Decimal serialized from backend
  pool_no_shares: z.string(), // ponytail: string — Decimal serialized from backend
})

export type AddLiquidityInput = z.infer<typeof addLiquiditySchema>
export type RemoveLiquidityInput = z.infer<typeof removeLiquiditySchema>
export type LPPositionResponse = z.infer<typeof lpPositionResponseSchema>

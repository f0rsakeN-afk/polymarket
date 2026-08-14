import { z } from "zod"

export const addLiquiditySchema = z.object({
  marketId: z.string(),
  amount: z.string(), // ponytail: string — Decimal serialized from backend
})

export const removeLiquiditySchema = z.object({
  marketId: z.string(),
  lpTokens: z.string(), // ponytail: string — Decimal serialized from backend
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

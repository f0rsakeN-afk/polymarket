import { z } from "zod"

export const addLiquiditySchema = z.object({
  marketId: z.string(),
  amount: z.number().min(1, "Minimum liquidity is $1"),
})

export const removeLiquiditySchema = z.object({
  marketId: z.string(),
  lpTokens: z.number().min(0.0001, "Minimum LP tokens required"),
})

export type AddLiquidityInput = z.infer<typeof addLiquiditySchema>
export type RemoveLiquidityInput = z.infer<typeof removeLiquiditySchema>

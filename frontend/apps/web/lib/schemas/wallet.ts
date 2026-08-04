import { z } from "zod"

export const depositSchema = z.object({
  amount: z.number().min(1, "Minimum deposit is $1"),
})

export const withdrawSchema = z.object({
  amount: z.number().min(1, "Minimum withdrawal is $1"),
})

export type DepositInput = z.infer<typeof depositSchema>
export type WithdrawInput = z.infer<typeof withdrawSchema>

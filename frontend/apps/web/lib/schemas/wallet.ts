import { z } from "zod"

export const depositSchema = z.object({
  amount: z.number().min(1, "Minimum deposit is $1"),
})

export const withdrawSchema = z.object({
  amount: z.number().min(1, "Minimum withdrawal is $1"),
})

export const walletResponseSchema = z.object({
  balance: z.string(), // ponytail: string — Decimal serialized from backend
  locked_balance: z.string(), // ponytail: string — Decimal serialized from backend
  available_balance: z.string(), // ponytail: string — Decimal serialized from backend
  currency: z.string(),
})

export const transactionResponseSchema = z.object({
  id: z.string(),
  type: z.string(),
  amount: z.string(), // ponytail: string — Decimal serialized from backend
  balance_after: z.string(), // ponytail: string — Decimal serialized from backend
  status: z.string(),
  created_at: z.string(),
})

export type DepositInput = z.infer<typeof depositSchema>
export type WithdrawInput = z.infer<typeof withdrawSchema>
export type WalletResponse = z.infer<typeof walletResponseSchema>
export type TransactionResponse = z.infer<typeof transactionResponseSchema>

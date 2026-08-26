import { z } from "zod"

const positiveMoney = z.string() // gt=0, Decimal serialized as string

export const depositSchema = z.object({
  amount: positiveMoney,
})

export const withdrawSchema = z.object({
  amount: positiveMoney,
  idempotency_key: z.string().max(64).optional(),
})

export const depositResponseSchema = z.object({
  client_secret: z.string(),
  payment_intent_id: z.string(),
  amount: z.string(),
  currency: z.string(),
})

export const walletResponseSchema = z.object({
  balance: z.string(),
  locked_balance: z.string(),
  available_balance: z.string(),
  currency: z.string(),
})

export const transactionResponseSchema = z.object({
  id: z.string(),
  type: z.string(),
  amount: z.string(),
  balance_after: z.string(),
  status: z.string(),
  created_at: z.string(),
})

export type DepositInput = z.infer<typeof depositSchema>
export type WithdrawInput = z.infer<typeof withdrawSchema>
export type DepositResponse = z.infer<typeof depositResponseSchema>
export type WalletResponse = z.infer<typeof walletResponseSchema>
export type TransactionResponse = z.infer<typeof transactionResponseSchema>

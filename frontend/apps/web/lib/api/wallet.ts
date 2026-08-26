import { api } from "./client"
import type { MutationResponse } from "@/lib/api/client"
import { z } from "zod"
import { depositSchema, withdrawSchema } from "@/lib/schemas/wallet"
import type { Wallet, TransactionsResponse } from "@/hooks/api/types/wallet"

export function getWallet() {
  return api.get<{ success: boolean; data: Wallet }>("/api/v1/wallet/")
}

export interface DepositResponse {
  client_secret: string
  amount: string
  currency: string
  message?: string
}

export interface WithdrawResponse {
  withdrawal_id: string
  amount: string
  status: string
  message?: string
}

export function deposit(data: z.infer<typeof depositSchema>) {
  return api.post<MutationResponse<DepositResponse>>(
    "/api/v1/wallet/deposit",
    depositSchema.parse(data)
  )
}

export function withdraw(data: z.infer<typeof withdrawSchema>) {
  return api.post<MutationResponse<WithdrawResponse>>(
    "/api/v1/wallet/withdraw",
    withdrawSchema.parse(data)
  )
}

export function listTransactions(params?: { page?: number; page_size?: number }) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<TransactionsResponse>(
    `/api/v1/wallet/transactions${query ? `?${query}` : ""}`
  )
}

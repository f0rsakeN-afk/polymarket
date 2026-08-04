import { api } from "./client"
import { z } from "zod"
import { depositSchema, withdrawSchema } from "@/lib/schemas/trading"
import type { Wallet, TransactionsResponse } from "@/hooks/api/types/wallet"

export function getWallet() {
  return api.get<Wallet>("/api/v1/wallet/")
}

export function deposit(data: z.infer<typeof depositSchema>) {
  return api.post<{ success: boolean; data: { client_secret: string; amount: number; currency: string } }>(
    "/api/v1/wallet/deposit",
    depositSchema.parse(data)
  )
}

export function withdraw(data: z.infer<typeof withdrawSchema>) {
  return api.post<{ success: boolean }>(
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

import { api } from "./client"
import type { Wallet, TransactionsResponse, Transaction } from "../types/api"

export function getWallet() {
  return api.get<Wallet>("/api/v1/wallet/")
}

export function deposit(amount: number) {
  return api.post<{ client_secret: string }>("/api/v1/wallet/deposit", {
    amount,
  })
}

export function withdraw(amount: number) {
  return api.post<{ success: boolean }>("/api/v1/wallet/withdraw", { amount })
}

export function listTransactions(params?: {
  page?: number
  page_size?: number
}) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<TransactionsResponse>(
    `/api/v1/wallet/transactions${query ? `?${query}` : ""}`
  )
}

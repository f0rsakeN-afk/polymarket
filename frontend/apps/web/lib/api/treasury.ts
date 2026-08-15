import { api } from "./client"

export interface TreasuryResponse {
  success: boolean
  data: {
    id: string
    balance: string
    total_fees_collected: string
    total_fees_distributed: string
  }
}

export interface TreasuryLogEntry {
  id: string
  event: string
  amount: string
  reference_type: string | null
  reference_id: string | null
  created_at: string
}

export interface TreasuryLogsResponse {
  data: TreasuryLogEntry[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export function getTreasury() {
  return api.get<TreasuryResponse>("/api/v1/treasury")
}

export function getTreasuryLogs(params?: { page?: number; page_size?: number; event?: string }) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  if (params?.event) qs.set("event", params.event)
  const query = qs.toString()
  return api.get<TreasuryLogsResponse>(
    `/api/v1/treasury/logs${query ? `?${query}` : ""}`
  )
}

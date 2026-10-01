import { api, MutationResponse } from "./client"
import type {
  MarketListResponse,
  MarketDetailResponse,
  MarketActivity,
  FAQ,
  MarketResponse,
  PriceHistoryPoint,
} from "@/hooks/api/types/market"

export function listMarkets(params?: {
  q?: string
  category?: string
  status?: string
  sort?: string
  page?: number
  page_size?: number
}) {
  const qs = new URLSearchParams()
  if (params?.q) qs.set("q", params.q)
  if (params?.category) qs.set("category", params.category)
  if (params?.status) qs.set("status", params.status)
  if (params?.sort) qs.set("sort", params.sort)
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<MarketListResponse>(`/api/v1/markets/${query ? `?${query}` : ""}`)
}

export function getMarket(slug: string) {
  return api.get<{ success: boolean; data: MarketDetailResponse }>(
    `/api/v1/markets/${slug}`
  )
}

// Trades feeds live in `lib/api/trades.ts` (listMarketTrades).

export function getMarketActivity(slug: string, limit = 20) {
  return api.get<{ success: boolean; data: MarketActivity }>(
    `/api/v1/markets/${slug}/activity?limit=${limit}`
  )
}

// Comment CRUD lives in `lib/api/comments.ts`.

export function getMarketFAQs(slug: string) {
  return api.get<{ success: boolean; data: FAQ[] }>(`/api/v1/markets/${slug}/faqs`)
}

export function getPriceHistory(slug: string, params?: { interval?: string; from_date?: string; to_date?: string }) {
  const qs = new URLSearchParams()
  if (params?.interval) qs.set("interval", params.interval)
  if (params?.from_date) qs.set("from_date", params.from_date)
  if (params?.to_date) qs.set("to_date", params.to_date)
  const query = qs.toString()
  return api.get<{ success: boolean; data: PriceHistoryPoint[] }>(
    `/api/v1/markets/${slug}/price-history${query ? `?${query}` : ""}`
  )
}

export function getRelatedMarkets(slug: string, limit = 5) {
  return api.get<{ success: boolean; data: MarketResponse[] }>(
    `/api/v1/markets/${slug}/related?limit=${limit}`
  )
}

export function resolveMarket(slug: string, winning_outcome_id: string) {
  return api.post<MutationResponse<{ slug: string; winning_outcome_id: string; winning_outcome_name: string }>>(
    `/api/v1/markets/${slug}/resolve`,
    { winning_outcome_id }
  )
}

export function createMarket(data: {
  question: string
  description?: string
  category?: string
  slug: string
  closes_at: string
  initial_liquidity?: number
  initial_probability?: number
  outcomes_create?: { name: string; outcome_index: number }[]
}) {
  return api.post<MutationResponse<{ slug: string; id: string }>>(
    "/api/v1/markets/",
    data
  )
}

// Global trade feed lives in `lib/api/trades.ts` (listTrades).

export interface OrderBookEntry {
  price: string
  size: string
}

export interface OrderBook {
  outcomes: Record<string, { bids: OrderBookEntry[]; asks: OrderBookEntry[] }>
}

export function getOrderBook(slug: string) {
  return api.get<{ success: boolean; data: OrderBook }>(`/api/v1/markets/${slug}/orderbook`)
}

export interface ClaimResponse {
  claimed: string
}

export function claimWinnings(slug: string) {
  return api.post<MutationResponse<ClaimResponse>>(
    `/api/v1/markets/${slug}/claim`
  )
}

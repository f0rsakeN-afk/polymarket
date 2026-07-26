import { api } from "./client"
import type {
  MarketListResponse,
  MarketDetailResponse,
  TradesResponse,
  MarketActivity,
  CommentsResponse,
  Comment,
  FAQ,
  MarketResponse,
  PriceHistoryPoint,
} from "../types/api"

export function listMarkets(params?: {
  q?: string
  category?: string
  status?: string
  page?: number
  page_size?: number
}) {
  const qs = new URLSearchParams()
  if (params?.q) qs.set("q", params.q)
  if (params?.category) qs.set("category", params.category)
  if (params?.status) qs.set("status", params.status)
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

export function getMarketTrades(slug: string, params?: { page?: number; page_size?: number }) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<TradesResponse>(
    `/api/v1/markets/${slug}/trades${query ? `?${query}` : ""}`
  )
}

export function getMarketActivity(slug: string, limit = 20) {
  return api.get<{ success: boolean; data: MarketActivity }>(
    `/api/v1/markets/${slug}/activity?limit=${limit}`
  )
}

export function getMarketComments(
  slug: string,
  params?: { page?: number; page_size?: number }
) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<CommentsResponse>(
    `/api/v1/markets/${slug}/comments${query ? `?${query}` : ""}`
  )
}

export function getMarketCommentReplies(slug: string, commentId: string) {
  return api.get<{ success: boolean; data: { replies: Comment[]; page: number; page_size: number } }>(
    `/api/v1/markets/${slug}/comments/${commentId}/replies`
  )
}

export function updateComment(slug: string, commentId: string, content: string) {
  return api.patch<{ success: boolean; data: { id: string; content: string } }>(
    `/api/v1/markets/${slug}/comments/${commentId}`, { content }
  )
}

export function deleteComment(slug: string, commentId: string) {
  return api.delete<{ success: boolean; data: { id: string; status: string } }>(
    `/api/v1/markets/${slug}/comments/${commentId}`
  )
}

export function postComment(slug: string, content: string, parent_id?: string) {
  return api.post<{ success: boolean; data: Comment }>(`/api/v1/markets/${slug}/comments`, {
    content,
    parent_id: parent_id ?? null,
  })
}

export function getMarketFAQs(slug: string) {
  return api.get<{ success: boolean; data: FAQ[] }>(`/api/v1/markets/${slug}/faqs/`)
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
    `/api/v1/markets/${slug}/related/?limit=${limit}`
  )
}

export function getGlobalTrades(params?: {
  page?: number
  page_size?: number
  market_slug?: string
}) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  if (params?.market_slug) qs.set("market_slug", params.market_slug)
  const query = qs.toString()
  return api.get<TradesResponse>(`/api/v1/trades${query ? `?${query}` : ""}`)
}

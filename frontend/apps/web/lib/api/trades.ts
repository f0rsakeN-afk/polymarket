import { z } from "zod"
import { api } from "./client"
import { tradeSchema } from "@/lib/schemas/trades"

export function listTrades(params?: {
  page?: number
  page_size?: number
  market_slug?: string
}) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  if (params?.market_slug) qs.set("market_slug", params.market_slug)
  const query = qs.toString()
  return api.get<{ success: boolean; data: { trades: z.infer<typeof tradeSchema>[]; page: number; page_size: number } }>(
    `/api/v1/trades${query ? `?${query}` : ""}`
  )
}

export function listMarketTrades(slug: string, params?: { page?: number; page_size?: number }) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<{ success: boolean; data: { trades: z.infer<typeof tradeSchema>[]; page: number; page_size: number } }>(
    `/api/v1/markets/${slug}/trades${query ? `?${query}` : ""}`
  )
}

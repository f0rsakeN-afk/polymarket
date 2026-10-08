import { api } from "./client"
import type { TradesResponse } from "@/hooks/api/types/market"

/**
 * GET /api/v1/trades and GET /api/v1/markets/{slug}/trades.
 *
 * Single implementation for both feed endpoints • they share one response
 * shape (`TradesResponse`) and accept the same parameters.
 *
 * Backend supports two pagination modes:
 *  - `page`/`page_size` (offset), hard-capped past offset 1000
 *  - `cursor` (opaque keyset token from `next_cursor`) • preferred for
 *    infinite scroll; it overrides `page` and never hits the cap.
 */
export interface TradeQuery {
  page?: number
  page_size?: number
  market_slug?: string
  /** Opaque token from a previous response's `data.next_cursor`. */
  cursor?: string
}

function toQuery(params?: TradeQuery) {
  const qs = new URLSearchParams()
  if (params?.cursor) qs.set("cursor", params.cursor)
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  if (params?.market_slug) qs.set("market_slug", params.market_slug)
  return qs.toString()
}

export function listTrades(params?: TradeQuery) {
  const query = toQuery(params)
  return api.get<TradesResponse>(`/api/v1/trades${query ? `?${query}` : ""}`)
}

export function listMarketTrades(
  slug: string,
  params?: Omit<TradeQuery, "market_slug">
) {
  const query = toQuery(params)
  return api.get<TradesResponse>(`/api/v1/markets/${slug}/trades${query ? `?${query}` : ""}`)
}

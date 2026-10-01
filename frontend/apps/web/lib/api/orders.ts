import { api } from "./client"
import type { MutationResponse } from "@/lib/api/client"
import { z } from "zod"
import { placeOrderSchema } from "@/lib/schemas/trading"
import { getQuoteSchema } from "@/lib/schemas/orders"
import type {
  OrdersResponse,
  PlaceOrderResponse,
  QuoteResponse,
  SingleOrder,
} from "@/hooks/api/types/order"

export type { OrdersResponse, PlaceOrderResponse, QuoteResponse }

export type PlaceOrderPayload = z.infer<typeof placeOrderSchema>

/**
 * GET /api/v1/orders/ — keyset pagination. Pass the previous page's
 * `next_cursor` back as `cursor`; there is no `page` parameter.
 */
export function listOrders(params?: {
  cursor?: string
  page_size?: number
  status?: string
  side?: string
  order_type?: string
  market_id?: string
  date_from?: string
  date_to?: string
}) {
  const qs = new URLSearchParams()
  if (params?.cursor) qs.set("cursor", params.cursor)
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  if (params?.status) qs.set("status", params.status)
  if (params?.side) qs.set("side", params.side)
  if (params?.order_type) qs.set("order_type", params.order_type)
  if (params?.market_id) qs.set("market_id", params.market_id)
  if (params?.date_from) qs.set("date_from", params.date_from)
  if (params?.date_to) qs.set("date_to", params.date_to)
  const query = qs.toString()
  return api.get<OrdersResponse>(`/api/v1/orders/${query ? `?${query}` : ""}`)
}

export function getOrder(orderId: string) {
  return api.get<MutationResponse<SingleOrder>>(`/api/v1/orders/${orderId}`)
}

export function placeOrder(order: PlaceOrderPayload) {
  return api.post<MutationResponse<PlaceOrderResponse>>(
    "/api/v1/orders/",
    placeOrderSchema.parse(order)
  )
}

export function cancelOrder(orderId: string) {
  return api.delete<MutationResponse<{ order_id: string; status: string }>>(
    `/api/v1/orders/${orderId}`
  )
}

export function getQuote(params: { market_id: string; outcome: string; side: "buy" | "sell"; amount: string | number }) {
  return api.post<MutationResponse<QuoteResponse>>(
    "/api/v1/orders/quote",
    getQuoteSchema.parse(params)
  )
}

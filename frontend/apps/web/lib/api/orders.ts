import { api } from "./client"
import { z } from "zod"
import { placeOrderSchema } from "@/lib/schemas/trading"
import { getQuoteSchema } from "@/lib/schemas/orders"
import type { OrdersResponse } from "@/hooks/api/types/order"

export type PlaceOrderPayload = z.infer<typeof placeOrderSchema>

export function listOrders(params?: {
  page?: number
  page_size?: number
  status?: string
  side?: string
  order_type?: string
  market_id?: string
  date_from?: string
  date_to?: string
}) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
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

export interface PlaceOrderResponse {
  order_id: string
  status: string
  side: string
  outcome: string
  shares: string
  price: string
  price_before: string
  price_after: string
  yes_price_after: string
  no_price_after: string
  slippage: string
  fee: string
  wallet_balance: string
  duplicate?: boolean
}

export interface SingleOrderResponse {
  id: string
  market_id: string
  outcome: string
  side: string
  order_type: string
  status: string
  amount: string
  price: string
  shares_bought: string | null
  shares_sold: string | null
  fee: string | null
  quote_id: string | null
  client_order_id: string | null
  created_at: string
  expires_at: string | null
}

export function getOrder(orderId: string) {
  return api.get<{ success: boolean; data: SingleOrderResponse }>(`/api/v1/orders/${orderId}`)
}

export function placeOrder(order: PlaceOrderPayload) {
  return api.post<{ success: boolean; data: PlaceOrderResponse }>(
    "/api/v1/orders/",
    placeOrderSchema.parse(order)
  )
}

export function cancelOrder(orderId: string) {
  return api.delete<{ success: boolean }>(`/api/v1/orders/${orderId}`)
}

export function getQuote(params: { market_id: string; outcome: string; side: "buy" | "sell"; amount: string | number }) {
  return api.post<{ success: boolean; data: import("@/lib/schemas/orders").QuoteResponse }>(
    "/api/v1/orders/quote",
    getQuoteSchema.parse(params)
  )
}

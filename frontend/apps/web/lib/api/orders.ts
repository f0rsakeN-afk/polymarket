import { api } from "./client"
import type { OrdersResponse, Order } from "../types/api"

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

export function getOrder(orderId: string) {
  return api.get<Order>(`/api/v1/orders/${orderId}`)
}

export function placeOrder(order: {
  market_id: string
  outcome: string
  side: "buy" | "sell"
  order_type?: "market" | "limit" | "fill_or_kill"
  amount: number
  price?: number
  expires_at?: string
  post_only?: boolean
  client_order_id?: string
}) {
  return api.post<Order>("/api/v1/orders/", order)
}

export function cancelOrder(orderId: string) {
  return api.delete<{ success: boolean }>(`/api/v1/orders/${orderId}`)
}

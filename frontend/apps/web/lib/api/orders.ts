import { api } from "./client"
import type { OrdersResponse, Order } from "../types/api"

export function listOrders(params?: { page?: number; page_size?: number }) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
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

import { api } from "./client"
import { z } from "zod"
import { placeOrderSchema } from "@/lib/schemas/trading"
import type { OrdersResponse, Order, QuoteResponse } from "@/hooks/api/types/order"

export type PlaceOrderPayload = z.infer<typeof placeOrderSchema>

export function parseOrder(data: unknown): PlaceOrderPayload {
  return placeOrderSchema.parse(data)
}

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
  shares: number
  price: number
  price_before: number
  price_after: number
  yes_price_after: number
  no_price_after: number
  slippage: number
  fee: number
  wallet_balance: number
  duplicate?: boolean
}

export interface SingleOrderResponse {
  id: string
  market_id: string
  market_slug: string
  outcome: string
  side: string
  order_type: string
  amount: number
  remaining_amount: number
  price: number
  status: string
  shares_bought: number | null
  shares_sold: number | null
  fees_paid: number | null
  created_at: string
  executed_at: string | null
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

export function getQuote(params: {
  market_id: string
  outcome: string
  side: "buy" | "sell"
  amount: number
}) {
  return api.post<{ success: boolean; data: QuoteResponse }>("/api/v1/orders/quote", params)
}

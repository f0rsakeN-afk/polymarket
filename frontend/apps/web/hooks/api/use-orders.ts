"use client"

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { listOrders, placeOrder, cancelOrder } from "@/lib/api/orders"
import { sileo } from "sileo"
import type { Order } from "@/hooks/api/types/order"

export function useOrders(filters?: {
  status?: string
  side?: string
  order_type?: string
  market_id?: string
}) {
  return useInfiniteQuery({
    queryKey: ["orders", filters?.status, filters?.side, filters?.order_type, filters?.market_id] as const,
    queryFn: ({ pageParam }) => listOrders({ page: pageParam, page_size: 20, ...filters }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage?.data?.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      orders: data.pages.flatMap((p) => p.data.orders ?? []) as Order[],
      hasMore: data.pages[data.pages.length - 1]?.data?.has_more ?? false,
    }),
  })
}

export function usePlaceOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: placeOrder,
    onSuccess: (res) => {
      if (res.data.duplicate) {
        sileo.info({ title: res.message ?? "Duplicate order", description: "This order was already placed." })
        qc.invalidateQueries({ queryKey: ["orders"] })
        return
      }
      sileo.success({ title: res.message ?? "Order placed", description: "Your order has been submitted." })
      qc.invalidateQueries({ queryKey: ["orders"] })
      qc.invalidateQueries({ queryKey: ["wallet"] })
      qc.invalidateQueries({ queryKey: ["positions"] })
    },
    onError: (err) => {
      const apiErr = err as { error_code?: string; message: string }
      switch (apiErr.error_code) {
        case "SLIPPAGE_EXCEEDED":
          sileo.error({ title: "Slippage exceeded", description: "Price moved too much — try increasing slippage tolerance or reducing the order size." })
          break
        case "INSUFFICIENT_BALANCE":
          sileo.error({ title: "Insufficient balance", description: "Not enough funds — deposit more to continue trading." })
          break
        case "INSUFFICIENT_SHARES":
          sileo.error({ title: "Insufficient shares", description: "You don't hold enough shares for this sell order." })
          break
        case "MARKET_CLOSED":
          sileo.error({ title: "Market closed", description: "This market is no longer active for trading." })
          break
        case "POST_ONLY_WOULD_CROSS":
          sileo.error({ title: "Post-only order rejected", description: "Order would cross the spread — try increasing your limit price." })
          break
        default:
          sileo.error({ title: apiErr.message || "Order failed" })
      }
    },
  })
}

export function useCancelOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: cancelOrder,
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Order cancelled" })
      qc.invalidateQueries({ queryKey: ["orders"] })
      qc.invalidateQueries({ queryKey: ["wallet"] })
      qc.invalidateQueries({ queryKey: ["positions"] })
    },
    onError: (err) => {
      const apiErr = err as { error_code?: string; message: string }
      switch (apiErr.error_code) {
        case "NOT_FOUND":
          sileo.error({ title: "Order not found", description: "This order may have already been cancelled or filled." })
          break
        default:
          sileo.error({ title: apiErr.message || "Cancel failed" })
      }
    },
  })
}

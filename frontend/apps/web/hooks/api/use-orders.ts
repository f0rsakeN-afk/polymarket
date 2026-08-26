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
      lastPage.data.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      orders: data.pages.flatMap((p) => p.data.orders) as Order[],
      hasMore: data.pages[data.pages.length - 1]?.data.has_more ?? false,
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
      sileo.error({ title: err instanceof Error ? err.message : "Order failed" })
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
      sileo.error({ title: err instanceof Error ? err.message : "Cancel failed" })
    },
  })
}

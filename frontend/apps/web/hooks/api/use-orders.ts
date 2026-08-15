"use client"

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { listOrders, placeOrder, cancelOrder } from "@/lib/api/orders"
import type { Order } from "@/hooks/api/types/order"

export function useOrders(filters?: {
  status?: string
  side?: string
  order_type?: string
  market_id?: string
}) {
  return useInfiniteQuery({
    queryKey: ["orders", filters] as const,
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["orders"] })
      qc.invalidateQueries({ queryKey: ["wallet"] })
      qc.invalidateQueries({ queryKey: ["positions"] })
    },
  })
}

export function useCancelOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: cancelOrder,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["orders"] })
      qc.invalidateQueries({ queryKey: ["wallet"] })
      qc.invalidateQueries({ queryKey: ["positions"] })
    },
  })
}

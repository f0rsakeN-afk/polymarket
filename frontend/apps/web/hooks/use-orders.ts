"use client"

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { listOrders, placeOrder, cancelOrder } from "@/lib/api/orders"
import type { Order } from "@/lib/types/api"

export function useOrders() {
  return useInfiniteQuery({
    queryKey: ["orders"] as const,
    queryFn: ({ pageParam }) => listOrders({ page: pageParam, page_size: 20 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      orders: data.pages.flatMap((p) => p.data) as Order[],
      hasMore: data.pages[data.pages.length - 1]?.has_more ?? false,
    }),
  })
}

export function usePlaceOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: placeOrder,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  })
}

export function useCancelOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: cancelOrder,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  })
}

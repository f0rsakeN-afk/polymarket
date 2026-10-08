"use client"

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { listOrders, placeOrder, cancelOrder } from "@/lib/api/orders"
import { queryKeys } from "@/lib/api/queryKeys"
import { apiErrorCode, apiErrorMessage } from "@/lib/api/client"
import { sileo } from "sileo"
import { useAuthGate } from "./use-auth-gate"

export function useOrders(filters?: {
  status?: string
  side?: string
  order_type?: string
  market_id?: string
}) {
  const { enabled } = useAuthGate()
  return useInfiniteQuery({
    queryKey: queryKeys.orders(filters),
    // Backend is keyset-paginated: `cursor`, never `page`.
    queryFn: ({ pageParam }) => listOrders({ cursor: pageParam, page_size: 20, ...filters }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.data.next_cursor ?? undefined,
    select: (data) => ({
      orders: data.pages.flatMap((p) => p.data.orders),
      hasMore: data.pages[data.pages.length - 1]?.data.has_more ?? false,
    }),
    enabled,
  })
}

export function usePlaceOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: placeOrder,
    // Success toasts are owned by the caller (`MarketDetailClient`), which
    // knows the shares/price context; errors are owned HERE so every caller
    // gets the same code-aware message from the backend envelope.
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.orders() })
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
    },
    onError: (err) => {
      switch (apiErrorCode(err)) {
        case "SLIPPAGE_EXCEEDED":
          sileo.error({ title: "Price moved", description: apiErrorMessage(err, "The price changed more than expected. Please review and try again.") })
          break
        case "INSUFFICIENT_BALANCE":
          sileo.error({ title: "Insufficient balance", description: apiErrorMessage(err, "You don't have enough funds for this order.") })
          break
        case "INSUFFICIENT_SHARES":
          sileo.error({ title: "Insufficient shares", description: apiErrorMessage(err, "You don't hold enough shares for this sell order.") })
          break
        case "MARKET_CLOSED":
          sileo.error({ title: "Market closed", description: apiErrorMessage(err, "This market is no longer active for trading.") })
          break
        case "POST_ONLY_WOULD_CROSS":
          sileo.error({ title: "Post-only order rejected", description: apiErrorMessage(err, "Order would cross the spread • try increasing your limit price.") })
          break
        default:
          sileo.error({ title: "Trade failed", description: apiErrorMessage(err, "Your order could not be placed.") })
      }
    },
  })
}

export function useCancelOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: cancelOrder,
    // Single toast owner • callers only manage their local UI state.
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Order cancelled" })
      qc.invalidateQueries({ queryKey: queryKeys.orders() })
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
    },
    onError: (err) => {
      switch (apiErrorCode(err)) {
        case "NOT_FOUND":
          sileo.error({ title: "Order not found", description: apiErrorMessage(err, "This order may have already been cancelled or filled.") })
          break
        default:
          sileo.error({ title: "Cancel failed", description: apiErrorMessage(err, "The order could not be cancelled.") })
      }
    },
  })
}

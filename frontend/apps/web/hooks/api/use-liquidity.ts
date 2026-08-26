"use client"

import { useQuery } from "@tanstack/react-query"
import { getLPAnalytics, getLPPosition } from "@/lib/api/liquidity"
import { queryKeys } from "@/lib/api/queryKeys"

export function useLPAnalytics() {
  return useQuery({
    queryKey: queryKeys.lpAnalytics(),
    queryFn: () => getLPAnalytics().then((r) => r.data),
    staleTime: 30_000,
  })
}

export function useLPPosition(marketId: string) {
  return useQuery({
    queryKey: queryKeys.lpPosition(marketId),
    queryFn: () => getLPPosition(marketId).then((r) => r.data),
    enabled: !!marketId,
    staleTime: 10_000,
  })
}

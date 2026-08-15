"use client"

import { useQuery } from "@tanstack/react-query"
import { getLPAnalytics } from "@/lib/api/liquidity"

export function useLPAnalytics() {
  return useQuery({
    queryKey: ["lp-analytics"] as const,
    queryFn: () => getLPAnalytics().then((r) => r.data),
    staleTime: 30_000,
  })
}

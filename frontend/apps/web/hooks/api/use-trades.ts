"use client"

import { useQuery } from "@tanstack/react-query"
import { listTrades, listMarketTrades } from "@/lib/api/trades"
import { queryKeys } from "@/lib/api/queryKeys"

export function useSimpleGlobalTrades(params?: { page?: number; page_size?: number; market_slug?: string }) {
  return useQuery({
    queryKey: queryKeys.globalTrades(params?.market_slug),
    queryFn: () => listTrades(params),
    select: (res) => res.data,
    staleTime: 10_000,
  })
}

export function useSimpleMarketTrades(slug: string, params?: { page?: number; page_size?: number }) {
  return useQuery({
    queryKey: queryKeys.marketTrades(slug),
    queryFn: () => listMarketTrades(slug, params),
    select: (res) => res.data,
    enabled: !!slug,
    staleTime: 10_000,
  })
}

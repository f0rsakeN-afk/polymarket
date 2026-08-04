"use client"

import { useQuery } from "@tanstack/react-query"
import { listTrades, listMarketTrades } from "@/lib/api/trades"

export function useGlobalTrades(params?: { page?: number; page_size?: number; market_slug?: string }) {
  return useQuery({
    queryKey: ["global-trades", params],
    queryFn: () => listTrades(params),
    select: (res) => res.data,
  })
}

export function useMarketTrades(slug: string, params?: { page?: number; page_size?: number }) {
  return useQuery({
    queryKey: ["market-trades", slug, params],
    queryFn: () => listMarketTrades(slug, params),
    select: (res) => res.data,
    enabled: !!slug,
  })
}

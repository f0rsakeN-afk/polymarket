"use client"

import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  listMarkets,
  getMarket,
  getMarketActivity,
  getMarketTrades,
  getGlobalTrades,
  getMarketFAQs,
  getRelatedMarkets,
  getPriceHistory,
  resolveMarket,
  createMarket,
  claimWinnings,
  getOrderBook,
} from "@/lib/api/markets"
import { api } from "@/lib/api/client"
import { queryKeys } from "@/lib/api/queryKeys"
import type { MarketResponse, MarketDetailResponse, MarketActivity, Trade } from "@/hooks/api/types/market"

// ─── Markets List ─────────────────────────────────────────────────────────────

export function useMarkets(params?: { q?: string; category?: string; status?: string; sort?: string }) {
  return useInfiniteQuery({
    queryKey: queryKeys.markets(params),
    queryFn: ({ pageParam = 1 }) => listMarkets({ ...params, page: pageParam, page_size: 20 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      markets: data.pages.flatMap((p) => p.data) as MarketResponse[],
      hasMore: data.pages[data.pages.length - 1]?.has_more ?? false,
    }),
    staleTime: 30_000,
  })
}

// ─── Market Detail ───────────────────────────────────────────────────────────

export function useMarket(slug: string) {
  return useQuery({
    queryKey: queryKeys.market(slug),
    queryFn: () => getMarket(slug).then((r) => r.data as MarketDetailResponse),
    enabled: !!slug,
    staleTime: 30_000,
  })
}

// ─── Market Activity ─────────────────────────────────────────────────────────

export function useMarketActivity(slug: string) {
  return useQuery({
    queryKey: queryKeys.marketActivity(slug),
    queryFn: () => getMarketActivity(slug).then((r) => r.data as MarketActivity),
    enabled: !!slug,
    staleTime: 15_000,
  })
}

// ─── Market Trades (infinite) ─────────────────────────────────────────────────

export function useMarketTrades(slug: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.marketTrades(slug),
    queryFn: ({ pageParam }) => getMarketTrades(slug, { page: pageParam, page_size: 50 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.data.trades.length === 50 ? lastPageParam + 1 : undefined,
    enabled: !!slug,
    select: (data) => ({
      trades: data.pages.flatMap((p) => p.data.trades) as Trade[],
      hasMore: data.pages[data.pages.length - 1]?.data.trades.length === 50,
    }),
    staleTime: 10_000,
  })
}

// ─── Global Trades (infinite) ─────────────────────────────────────────────────

export function useGlobalTrades(params?: { market_slug?: string }) {
  return useInfiniteQuery({
    queryKey: queryKeys.globalTrades(params?.market_slug),
    queryFn: ({ pageParam }) => getGlobalTrades({ ...params, page: pageParam, page_size: 50 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.data.trades.length === 50 ? lastPageParam + 1 : undefined,
    select: (data) => ({
      trades: data.pages.flatMap((p) => p.data.trades) as Trade[],
      hasMore: data.pages[data.pages.length - 1]?.data.trades.length === 50,
    }),
    staleTime: 10_000,
  })
}

// ─── FAQs ─────────────────────────────────────────────────────────────────────

export function useFAQs(slug: string) {
  return useQuery({
    queryKey: queryKeys.faqs(slug),
    queryFn: () => getMarketFAQs(slug).then((r) => r.data),
    enabled: !!slug,
    staleTime: 60_000,
  })
}

// ─── Related Markets ─────────────────────────────────────────────────────────

export function useRelatedMarkets(slug: string) {
  return useQuery({
    queryKey: queryKeys.relatedMarkets(slug),
    queryFn: () => getRelatedMarkets(slug).then((r) => r.data),
    enabled: !!slug,
    staleTime: 60_000,
  })
}

// ─── Price History ───────────────────────────────────────────────────────────

export function usePriceHistory(slug: string, interval = "5m") {
  return useQuery({
    queryKey: queryKeys.priceHistory(slug, interval),
    queryFn: () => getPriceHistory(slug, { interval }).then((r) => r.data),
    enabled: !!slug,
    refetchInterval: 300_000,
    staleTime: 300_000,
  })
}

// ─── Order Book ──────────────────────────────────────────────────────────────

export function useOrderBook(slug: string) {
  return useQuery({
    queryKey: queryKeys.orderBook(slug),
    queryFn: () => getOrderBook(slug).then((r) => r.data),
    enabled: !!slug,
    staleTime: 5_000,
  })
}

// ─── Market Categories ────────────────────────────────────────────────────────

export function useMarketCategories() {
  return useQuery({
    queryKey: queryKeys.marketCategories(),
    queryFn: () =>
      api.get<{ success: boolean; data: { categories: string[] } }>("/api/v1/markets/categories").then(
        (r) => r.data?.categories ?? []
      ),
    staleTime: 300_000,
  })
}

// ─── Create / Resolve / Claim ────────────────────────────────────────────────

export function useCreateMarket() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Parameters<typeof createMarket>[0]) => createMarket(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.markets() })
    },
  })
}

export function useResolveMarket() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, winning_outcome_id }: { slug: string; winning_outcome_id: string }) =>
      resolveMarket(slug, winning_outcome_id),
    onSuccess: (_, { slug }) => {
      qc.invalidateQueries({ queryKey: queryKeys.market(slug) })
      qc.invalidateQueries({ queryKey: queryKeys.marketActivity(slug) })
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
      qc.invalidateQueries({ queryKey: queryKeys.markets() })
    },
  })
}

export function useClaimWinnings(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => claimWinnings(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.market(slug) })
    },
  })
}

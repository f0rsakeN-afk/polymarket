"use client"

import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  listMarkets,
  getMarket,
  getMarketActivity,
  getMarketFAQs,
  getRelatedMarkets,
  getPriceHistory,
  resolveMarket,
  createMarket,
  claimWinnings,
  getOrderBook,
} from "@/lib/api/markets"
import { listMarketTrades, listTrades } from "@/lib/api/trades"
import { api } from "@/lib/api/client"
import { queryKeys } from "@/lib/api/queryKeys"
import type { MarketListResponse, MarketResponse, TradesResponse } from "@/hooks/api/types/market"

// ─── Markets List ─────────────────────────────────────────────────────────────

export function useMarkets(
  params?: { q?: string; category?: string; status?: string; sort?: string },
  initialPage?: MarketListResponse,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.markets(params),
    queryFn: ({ pageParam = 1 }) => listMarkets({ ...params, page: pageParam, page_size: 20 }),
    initialPageParam: 1,
    ...(initialPage ? { initialData: { pages: [initialPage], pageParams: [1] } } : {}),
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage?.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      markets: data.pages.flatMap((p) => p.data ?? []) as MarketResponse[],
      hasMore: data.pages[data.pages.length - 1]?.has_more ?? false,
    }),
    staleTime: 30_000,
  })
}

// ─── Market Detail ───────────────────────────────────────────────────────────

export function useMarket(slug: string) {
  return useQuery({
    queryKey: queryKeys.market(slug),
    queryFn: () => getMarket(slug).then((r) => r.data),
    enabled: !!slug,
    staleTime: 30_000,
  })
}

// ─── Market Activity ─────────────────────────────────────────────────────────

export function useMarketActivity(slug: string) {
  return useQuery({
    queryKey: queryKeys.marketActivity(slug),
    queryFn: () => getMarketActivity(slug).then((r) => r.data),
    enabled: !!slug,
    staleTime: 15_000,
  })
}

// ─── Market Trades (infinite) ─────────────────────────────────────────────────

export function useMarketTrades(slug: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.marketTrades(slug),
    // Keyset pagination: feed the previous `next_cursor` back in.
    queryFn: ({ pageParam }) => listMarketTrades(slug, { cursor: pageParam, page_size: 50 }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.data.next_cursor ?? undefined,
    enabled: !!slug,
    select: (data) => ({
      trades: data.pages.flatMap((p) => p.data.trades),
      hasMore: data.pages[data.pages.length - 1]?.data.has_more ?? false,
    }),
    staleTime: 10_000,
  })
}

// ─── Global Trades (infinite) ─────────────────────────────────────────────────

export function useGlobalTrades(params?: { market_slug?: string }, initialPage?: TradesResponse) {
  return useInfiniteQuery({
    queryKey: queryKeys.globalTrades(params?.market_slug ?? undefined),
    queryFn: ({ pageParam }) =>
      listTrades({ market_slug: params?.market_slug, cursor: pageParam, page_size: 50 }),
    ...(initialPage
      ? { initialData: { pages: [initialPage], pageParams: [undefined as string | undefined] } }
      : {}),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.data.next_cursor ?? undefined,
    select: (data) => ({
      trades: data.pages.flatMap((p) => p.data.trades),
      hasMore: data.pages[data.pages.length - 1]?.data.has_more ?? false,
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
    queryFn: () => getOrderBook(slug).then((r) => {
      if (!r.success || !r.data) throw new Error("Failed to load order book")
      return r.data
    }),
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

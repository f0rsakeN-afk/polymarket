"use client"

import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { listMarkets, getMarket, getMarketActivity, getMarketTrades, getGlobalTrades, getMarketComments, postComment, updateComment, deleteComment, getMarketFAQs, getRelatedMarkets, getPriceHistory, resolveMarket } from "@/lib/api/markets"
import type { MarketResponse, MarketDetailResponse, MarketActivity, Trade, Comment } from "@/lib/types/api"

// ─── Markets List ─────────────────────────────────────────────────────────────

export function useMarkets(params?: { q?: string; category?: string; status?: string }) {
  return useInfiniteQuery({
    queryKey: ["markets", params] as const,
    queryFn: ({ pageParam = 1 }) => listMarkets({ ...params, page: pageParam, page_size: 20 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      markets: data.pages.flatMap((p) => p.data) as MarketResponse[],
      hasMore: data.pages[data.pages.length - 1]?.has_more ?? false,
    }),
  })
}

// ─── Market Detail ───────────────────────────────────────────────────────────

export function useMarket(slug: string) {
  return useQuery({
    queryKey: ["market", slug] as const,
    queryFn: () => getMarket(slug).then((r) => r.data as MarketDetailResponse),
    enabled: !!slug,
  })
}

// ─── Market Activity ─────────────────────────────────────────────────────────

export function useMarketActivity(slug: string) {
  return useQuery({
    queryKey: ["market-activity", slug] as const,
    queryFn: () => getMarketActivity(slug).then((r) => r.data as MarketActivity),
    enabled: !!slug,
  })
}

// ─── Market Trades ──────────────────────────────────────────────────────────

export function useMarketTrades(slug: string) {
  return useInfiniteQuery({
    queryKey: ["market-trades", slug] as const,
    queryFn: ({ pageParam }) => getMarketTrades(slug, { page: pageParam, page_size: 50 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.data.trades.length === 50 ? lastPageParam + 1 : undefined,
    enabled: !!slug,
    select: (data) => ({
      trades: data.pages.flatMap((p) => p.data.trades) as Trade[],
      hasMore: data.pages[data.pages.length - 1]?.data.trades.length === 50,
    }),
  })
}

// ─── Global Trades ──────────────────────────────────────────────────────────

export function useGlobalTrades(params?: { market_slug?: string }) {
  return useInfiniteQuery({
    queryKey: ["global-trades", params?.market_slug] as const,
    queryFn: ({ pageParam }) => getGlobalTrades({ ...params, page: pageParam, page_size: 50 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.data.trades.length === 50 ? lastPageParam + 1 : undefined,
    select: (data) => ({
      trades: data.pages.flatMap((p) => p.data.trades) as Trade[],
      hasMore: data.pages[data.pages.length - 1]?.data.trades.length === 50,
    }),
  })
}

// ─── Comments ───────────────────────────────────────────────────────────────

export function useComments(slug: string) {
  return useQuery({
    queryKey: ["comments", slug] as const,
    queryFn: () => getMarketComments(slug).then((r) => r.data.comments as Comment[]),
    enabled: !!slug,
  })
}

export function usePostComment(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ content, parent_id }: { content: string; parent_id?: string }) =>
      postComment(slug, content, parent_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["comments", slug] }),
  })
}

export function useEditComment(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ commentId, content }: { commentId: string; content: string }) =>
      updateComment(slug, commentId, content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["comments", slug] }),
  })
}

export function useDeleteComment(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ commentId }: { commentId: string }) =>
      deleteComment(slug, commentId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["comments", slug] }),
  })
}

export function useFAQs(slug: string) {
  return useQuery({
    queryKey: ["faqs", slug] as const,
    queryFn: () => getMarketFAQs(slug).then((r) => r.data),
    enabled: !!slug,
  })
}

export function useRelatedMarkets(slug: string) {
  return useQuery({
    queryKey: ["related-markets", slug] as const,
    queryFn: () => getRelatedMarkets(slug).then((r) => r.data),
    enabled: !!slug,
  })
}

export function useResolveMarket() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ slug, winning_outcome_id }: { slug: string; winning_outcome_id: string }) =>
      resolveMarket(slug, winning_outcome_id),
    onSuccess: (_, { slug }) => {
      qc.invalidateQueries({ queryKey: ["market", slug] })
      qc.invalidateQueries({ queryKey: ["market-activity", slug] })
      qc.invalidateQueries({ queryKey: ["positions"] })
      qc.invalidateQueries({ queryKey: ["markets"] })
    },
  })
}

export function usePriceHistory(slug: string, interval = "5m") {
  return useQuery({
    queryKey: ["price-history", slug, interval] as const,
    queryFn: () => getPriceHistory(slug, { interval }).then((r) => r.data),
    enabled: !!slug,
    refetchInterval: 300_000,
  })
}

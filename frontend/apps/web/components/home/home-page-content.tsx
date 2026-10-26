"use client"

import Link from "next/link"
import { useCallback, Suspense, useMemo } from "react"
import dynamic from "next/dynamic"
import { useSearchParams } from "next/navigation"
import TrendingCarousel from "@/components/home/trending-carousel"
import { MarketList } from "@/components/markets/market-list"
import { useMarkets } from "@/hooks/api/use-markets"
import { useGlobalTrades } from "@/hooks/api/use-markets"
import { useLiveTradeFeed } from "@/hooks/use-live-trade-feed"
import { SkeletonTrendingCarousel, SkeletonTradeFeed } from "@/components/shared/skeletons"

const LazyTradeFeed = dynamic(
  () => import("@/components/trades/trade-feed").then((m) => ({ default: m.TradeFeed })),
  { ssr: false, loading: () => <SkeletonTradeFeed /> }
)

import type { MarketListResponse, TradesResponse } from "@/hooks/api/types/market"

/** Matches the /trades page so the two tapes behave identically. */
const HOME_FEED_MAX = 15

export default function HomePageContent({
  initialMarketsPage,
  initialClosingPage,
  initialTradesPage,
}: {
  initialMarketsPage?: MarketListResponse
  initialClosingPage?: MarketListResponse
  initialTradesPage?: TradesResponse
}) {
  const searchParams = useSearchParams()
  const tag = searchParams.get("tag") ?? "All"
  const query = searchParams.get("q") ?? ""

  const { data: marketsData, isLoading: marketsLoading, fetchNextPage: fetchMarketsNextPage, hasNextPage: marketsHasMore } = useMarkets({ q: query || undefined }, initialMarketsPage)
  const { data: closingSoonData, isLoading: closingSoonLoading, isError: closingSoonError } =
    useMarkets({ sort: "closing_soon" }, initialClosingPage)
  const { data: tradesData, refetch: refetchTrades } = useGlobalTrades(undefined, initialTradesPage)

  // The tape was rendered from a server snapshot and then never updated - the
  // one section of this page with no socket on it, sitting directly above a
  // "View all" link to a page that *is* live. Same merge logic as /trades, so
  // the two cannot drift.
  const { wsTrades } = useLiveTradeFeed(tradesData?.trades, refetchTrades, HOME_FEED_MAX)

  const recentTrades = useMemo(() => {
    // Deduped at the merge rather than on arrival: a frame that arrives while
    // the REST page is in flight is accepted, and the response then carries the
    // same trade. This is the only place both sources are visible together.
    const seen = new Set<string>()
    const out = []
    for (const t of [...wsTrades, ...(tradesData?.trades ?? [])]) {
      if (seen.has(t.id)) continue
      seen.add(t.id)
      out.push(t)
      if (out.length >= HOME_FEED_MAX) break
    }
    return out
  }, [wsTrades, tradesData?.trades])

  const handleLoadMore = useCallback(() => {
    fetchMarketsNextPage()
  }, [fetchMarketsNextPage])

  const trending = marketsData?.markets.slice(0, 8) ?? []
  const filteredMarkets = tag.toLowerCase() === "all"
    ? marketsData?.markets ?? []
    : (marketsData?.markets ?? []).filter((m) => m.category?.toLowerCase() === tag.toLowerCase())

  return (
    <div className="container mx-auto max-w-7xl px-4 py-6 space-y-10">
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Trending Markets</h2>
          <Link href="/markets" className="text-sm text-muted-foreground hover:text-foreground transition-colors">View all</Link>
        </div>
        {marketsLoading && trending.length === 0 ? (
          <SkeletonTrendingCarousel />
        ) : (
          <TrendingCarousel markets={trending} />
        )}
      </section>

      {/* Always mounted: conditional mounting would push every section
          below it down when data arrives (layout shift). */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Closing Soon</h2>
        </div>
        {/*
          `closingSoonLoading || !closingSoonData` left the skeleton on screen
          forever whenever the query *failed*: loading goes false but the data
          stays undefined, so the condition never became false. A 4xx or a
          network blip rendered as an endless shimmer with no way out. Skeleton
          only while actually loading; an error is reported, not hidden.
        */}
        {closingSoonLoading ? (
          <SkeletonTrendingCarousel />
        ) : closingSoonError ? (
          <p className="rounded-xl border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
            Couldn&apos;t load markets closing soon.
          </p>
        ) : (closingSoonData?.markets.length ?? 0) > 0 ? (
          <TrendingCarousel markets={closingSoonData!.markets.slice(0, 8)} />
        ) : (
          <p className="rounded-xl border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
            No markets closing soon
          </p>
        )}
      </section>

      <section>
        <div className="flex items-center justify-between mt-6 mb-4">
          <h2 className="text-lg font-semibold">Markets</h2>
          <Link href="/markets" className="text-sm text-muted-foreground hover:text-foreground transition-colors">View all</Link>
        </div>
        <MarketList
          markets={filteredMarkets}
          loading={marketsLoading}
          hasMore={marketsHasMore ?? false}
          onLoadMore={handleLoadMore}
        />
      </section>

      {tag.toLowerCase() === "all" && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Global Activity</h2>
            <Link href="/trades" className="text-sm text-muted-foreground hover:text-foreground transition-colors">View all</Link>
          </div>
          <Suspense fallback={<SkeletonTradeFeed />}>
            <LazyTradeFeed title="" trades={recentTrades} />
          </Suspense>
        </section>
      )}
    </div>
  )
}

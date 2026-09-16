"use client"

import Link from "next/link"
import { useCallback, Suspense } from "react"
import dynamic from "next/dynamic"
import { useSearchParams } from "next/navigation"
import TrendingCarousel from "@/components/home/trending-carousel"
import { MarketList } from "@/components/markets/market-list"
import { useMarkets } from "@/hooks/api/use-markets"
import { useGlobalTrades } from "@/hooks/api/use-markets"
import { SkeletonTrendingCarousel, SkeletonTradeFeed } from "@/components/shared/skeletons"

const LazyTradeFeed = dynamic(
  () => import("@/components/trades/trade-feed").then((m) => ({ default: m.TradeFeed })),
  { ssr: false, loading: () => <SkeletonTradeFeed /> }
)

import type { MarketListResponse, TradesResponse } from "@/hooks/api/types/market"

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
  const { data: closingSoonData, isLoading: closingSoonLoading } = useMarkets({ sort: "closing_soon" }, initialClosingPage)
  const { data: tradesData } = useGlobalTrades(undefined, initialTradesPage)

  const recentTrades = tradesData?.trades.slice(0, 15) ?? []

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
        {closingSoonLoading || !closingSoonData ? (
          <SkeletonTrendingCarousel />
        ) : closingSoonData.markets.length > 0 ? (
          <TrendingCarousel markets={closingSoonData.markets.slice(0, 8)} />
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

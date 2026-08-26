"use client"

import Link from "next/link"
import { useCallback, lazy, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import TrendingCarousel from "@/components/home/trending-carousel"
import { MarketList } from "@/components/markets/market-list"
import { useMarkets } from "@/hooks/api/use-markets"
import { useGlobalTrades } from "@/hooks/api/use-markets"
import { SkeletonTrendingCarousel, SkeletonTradeFeed } from "@/components/shared/skeletons"

const LazyTradeFeed = lazy(() =>
  import("@/components/trades/trade-feed").then((m) => ({ default: m.TradeFeed }))
)

export default function HomePageContent() {
  const searchParams = useSearchParams()
  const tag = searchParams.get("tag") ?? "All"
  const query = searchParams.get("q") ?? ""

  const { data: marketsData, isLoading: marketsLoading, fetchNextPage: fetchMarketsNextPage, hasNextPage: marketsHasMore } = useMarkets({ q: query || undefined })
  const { data: closingSoonData, isLoading: closingSoonLoading } = useMarkets({ sort: "closing_soon" })
  const { data: tradesData } = useGlobalTrades()

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

      {closingSoonData && closingSoonData.markets.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Closing Soon</h2>
          </div>
          {closingSoonLoading ? (
            <SkeletonTrendingCarousel />
          ) : (
            <TrendingCarousel markets={closingSoonData.markets.slice(0, 8)} />
          )}
        </section>
      )}

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
            <LazyTradeFeed title="" trades={tradesData?.trades.slice(0, 15) ?? []} />
          </Suspense>
        </section>
      )}
    </div>
  )
}

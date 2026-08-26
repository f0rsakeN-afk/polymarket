"use client"

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
        <div className="mt-6">
          <MarketList
            markets={filteredMarkets}
            loading={marketsLoading}
            hasMore={marketsHasMore ?? false}
            onLoadMore={handleLoadMore}
          />
        </div>
      </section>

      {tag.toLowerCase() === "all" && (
        <section className="lg:hidden">
          <Suspense fallback={<SkeletonTradeFeed />}>
            <LazyTradeFeed title="Global Activity" trades={tradesData?.trades.slice(0, 15) ?? []} />
          </Suspense>
        </section>
      )}
    </div>
  )
}

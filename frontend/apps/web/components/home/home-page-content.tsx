"use client"

import { useCallback, useEffect, useRef, useState, lazy, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import TrendingCarousel from "@/components/home/trending-carousel"
import CategoryTabs from "@/components/home/category-tabs"
import { MarketList } from "@/components/markets/market-list"
import { useMarkets, useMarketCategories } from "@/hooks/api/use-markets"
import { useGlobalTrades } from "@/hooks/api/use-markets"
import { SkeletonTrendingCarousel, SkeletonMarketGrid, SkeletonTradeFeed } from "@/components/shared/skeletons"
import { SearchIcon } from "lucide-react"

const LazyTradeFeed = lazy(() =>
  import("@/components/trades/trade-feed").then((m) => ({ default: m.TradeFeed }))
)

export default function HomePageContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const tag = searchParams.get("tag") ?? "All"
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { setQuery(search) }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [search])

  const { data: marketsData, isLoading: marketsLoading, fetchNextPage: fetchMarketsNextPage, hasNextPage: marketsHasMore } = useMarkets({ q: query || undefined })
  const { data: closingSoonData, isLoading: closingSoonLoading } = useMarkets({ sort: "closing_soon" })
  const { data: tradesData } = useGlobalTrades()

  const handleLoadMore = useCallback(() => {
    fetchMarketsNextPage()
  }, [fetchMarketsNextPage])

  const handleTagChange = useCallback((t: string) => {
    router.push(t === "All" ? "/" : `/?tag=${t.toLowerCase()}`)
  }, [router])

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
        <div className="relative mb-4">
          <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search markets..."
            className="w-full h-9 pl-9 pr-4 rounded-lg border border-border bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
        <CategoryTabs tag={tag} onTagChange={handleTagChange} />
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

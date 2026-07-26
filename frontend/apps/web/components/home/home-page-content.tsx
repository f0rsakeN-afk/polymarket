"use client"

import { useCallback } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import TrendingCarousel from "@/components/home/trending-carousel"
import CategoryTabs from "@/components/home/category-tabs"
import { MarketList } from "@/components/markets/market-list"
import { TradeFeed } from "@/components/trades/trade-feed"
import { useMarkets, useGlobalTrades } from "@/hooks/use-markets"
import { Spinner } from "@workspace/ui/components/spinner"

export default function HomePageContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const tag = searchParams.get("tag") ?? "All"

  const { data: marketsData, isLoading: marketsLoading, fetchNextPage: fetchMarketsNextPage, hasNextPage: marketsHasMore } = useMarkets()
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
          <div className="flex h-40 items-center justify-center">
            <Spinner className="size-5" />
          </div>
        ) : (
          <TrendingCarousel markets={trending} />
        )}
      </section>

      <section>
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
          <TradeFeed title="Global Activity" trades={tradesData?.trades.slice(0, 15) ?? []} />
        </section>
      )}
    </div>
  )
}

import { Suspense } from "react"
import CategoryTabsSection from "@/components/home/category-tabs-section"
import HomePageContent from "@/components/home/home-page-content"
import {
  SkeletonMarketGrid,
  SkeletonTradeFeed,
  SkeletonTrendingCarousel,
} from "@/components/shared/skeletons"
import { getGlobalTrades, listMarkets } from "@/lib/api/markets"
import type { MarketListResponse, TradesResponse } from "@/hooks/api/types/market"

export const dynamic = "force-dynamic"

// Same shell + section rhythm as HomePageContent so the boundary swaps
// skeletons for content without moving anything on screen.
function HomePageSkeleton() {
  return (
    <div className="container mx-auto max-w-7xl px-4 py-6 space-y-10" aria-hidden="true">
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="h-5 w-36 animate-pulse rounded-md bg-muted/60" />
        </div>
        <SkeletonTrendingCarousel />
      </section>
      <section>
        <div className="flex items-center justify-between mt-6 mb-4">
          <div className="h-5 w-24 animate-pulse rounded-md bg-muted/60" />
        </div>
        <SkeletonMarketGrid />
      </section>
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="h-5 w-32 animate-pulse rounded-md bg-muted/60" />
        </div>
        <SkeletonTradeFeed />
      </section>
    </div>
  )
}

type SearchParams = { tag?: string; q?: string }

/**
 * Server-rendered homepage shell. The three content queries run ON THE
 * SERVER in parallel (one fast backend hop, no client waterfall) and seed
 * React Query via initialData — first paint already contains real markets,
 * which is what LCP measures. If the backend is unreachable, seeds are
 * undefined and the client hooks fetch as before (graceful degradation).
 */
export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>
}) {
  const sp = await searchParams
  const q = sp?.q ?? ""

  const [marketsPage, closingPage, tradesPage] = await Promise.all([
    listMarkets({ q: q || undefined, page: 1, page_size: 20 }).catch(() => undefined),
    listMarkets({ sort: "closing_soon", page: 1, page_size: 8 }).catch(() => undefined),
    getGlobalTrades({ page: 1, page_size: 15 }).catch(() => undefined),
  ])

  return (
    <>
      <div className="sticky top-14 z-30 bg-background/80 backdrop-blur">
        <div className="container mx-auto max-w-7xl px-4 py-2">
          <Suspense fallback={<div className="h-9" />}>
            <CategoryTabsSection />
          </Suspense>
        </div>
      </div>
      <Suspense fallback={<HomePageSkeleton />}>
        <HomePageContent
          initialMarketsPage={marketsPage as MarketListResponse | undefined}
          initialClosingPage={closingPage as MarketListResponse | undefined}
          initialTradesPage={tradesPage as TradesResponse | undefined}
        />
      </Suspense>
    </>
  )
}

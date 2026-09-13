"use client"

import { lazy, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import CategoryTabs from "@/components/home/category-tabs"
import {
  SkeletonMarketGrid,
  SkeletonTradeFeed,
  SkeletonTrendingCarousel,
} from "@/components/shared/skeletons"

const HomePageContent = lazy(
  () => import("@/components/home/home-page-content")
)

export const dynamic = "force-dynamic"

// Same shell + section rhythm as HomePageContent so the lazy boundary
// swaps skeletons for content without moving anything on screen.
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

function CategoryTabsSection() {
  const searchParams = useSearchParams()
  const tag = searchParams.get("tag") ?? "All"
  return <CategoryTabs tag={tag} />
}

export default function HomePage() {
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
        <HomePageContent />
      </Suspense>
    </>
  )
}

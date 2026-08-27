"use client"

import { useEffect, useRef, memo, useCallback } from "react"
import { MarketCard } from "./market-card"
import { SkeletonMarketGrid } from "@/components/shared/skeletons"
import type { MarketResponse } from "@/hooks/api/types/market"

interface MarketListProps {
  markets: MarketResponse[]
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
}

const MarketList = memo(function MarketList({ markets, loading, hasMore, onLoadMore }: MarketListProps) {
  const sentinelRef = useRef<HTMLDivElement>(null)

  const handleIntersect = useCallback((entry: IntersectionObserverEntry) => {
    if (entry?.isIntersecting && hasMore && !loading) {
      onLoadMore()
    }
  }, [hasMore, loading, onLoadMore])

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return

    const observer = new IntersectionObserver(
      (entries) => {
        handleIntersect(entries[0])
      },
      { threshold: 0.1 }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [handleIntersect])

  if (loading && markets.length === 0) {
    return <SkeletonMarketGrid />
  }

  if (!loading && markets.length === 0) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        No markets found
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {markets.map((market) => (
          <MarketCard key={market.id} market={market} />
        ))}
      </div>
      <div ref={sentinelRef} className="flex justify-center py-4">
        {loading && <div className="flex items-center gap-1 text-muted-foreground"><div className="size-3 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" /> Loading...</div>}
        {!hasMore && markets.length > 0 && (
          <span className="text-xs text-muted-foreground">No more markets</span>
        )}
      </div>
    </div>
  )
})

export { MarketList }
export default MarketList

"use client"

import { useEffect, useRef, memo, useCallback } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { MarketCard } from "./market-card"
import { SkeletonMarketGrid } from "@/components/shared/skeletons"
import type { MarketResponse } from "@/hooks/api/types/market"

interface MarketListProps {
  markets: MarketResponse[]
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
}

const CARD_HEIGHT = 220
const CARD_GAP = 32
const COLS_LG = 3
const COLS_SM = 2

const MarketList = memo(function MarketList({ markets, loading, hasMore, onLoadMore }: MarketListProps) {
  const sentinelRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

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
        if (entries[0]) handleIntersect(entries[0])
      },
      { threshold: 0.1 }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [handleIntersect])

  const rowVirtualizer = useVirtualizer({
    count: Math.ceil(markets.length / COLS_LG),
    getScrollElement: () => containerRef.current,
    estimateSize: () => CARD_HEIGHT + CARD_GAP,
    overscan: 2,
  })

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
      <div
        ref={containerRef}
        className="overflow-auto pt-1 hide-scrollbar"
        style={{ maxHeight: "800px" }}
      >
        <div
          style={{
            height: `${rowVirtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const startIdx = virtualRow.index * COLS_LG
            const rowMarkets = markets.slice(startIdx, startIdx + COLS_LG)

            return (
              <div
                key={virtualRow.index}
                className="grid gap-4 absolute left-0 right-0 grid-cols-2 lg:grid-cols-3"
                style={{
                  top: `${virtualRow.start}px`,
                  height: `${virtualRow.size}px`,
                }}
              >
                {rowMarkets.map((market) => (
                  <MarketCard key={market.id} market={market} />
                ))}
              </div>
            )
          })}
        </div>
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

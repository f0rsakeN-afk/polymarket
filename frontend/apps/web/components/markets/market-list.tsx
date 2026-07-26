"use client"

import { useEffect, useRef, memo } from "react"
import { MarketCard } from "./market-card"
import { Spinner } from "@workspace/ui/components/spinner"
import type { MarketResponse } from "@/lib/types/api"

interface MarketListProps {
  markets: MarketResponse[]
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
}

function MarketList({ markets, loading, hasMore, onLoadMore }: MarketListProps) {
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0]
        if (entry?.isIntersecting && hasMore && !loading) {
          onLoadMore()
        }
      },
      { threshold: 0.1 }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, loading, onLoadMore])

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
        {loading && <Spinner className="size-5" />}
        {!hasMore && markets.length > 0 && (
          <span className="text-muted-foreground">No more markets</span>
        )}
      </div>
    </div>
  )
}

export { MarketList }
export default memo(MarketList)

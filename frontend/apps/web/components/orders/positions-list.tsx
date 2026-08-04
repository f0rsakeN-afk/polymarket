"use client"

import { useEffect, useRef, memo } from "react"
import { Spinner } from "@workspace/ui/components/spinner"
import type { Position } from "@/hooks/api/types/order"

function formatUSD(n: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Math.abs(n))
}

interface PositionsListProps {
  positions: Position[]
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
}

function PositionRow({ position }: { position: Position }) {
  const pnl = position.unrealized_pnl
  const isProfit = pnl >= 0

  return (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-0">
      <div className="min-w-0">
        <div className="truncate text-xs font-medium">{position.market_question}</div>
        <div className="mt-0.5 flex items-center gap-2 text-muted-foreground">
          <span
            className={`text-[10px] font-semibold uppercase ${
              position.outcome === "yes" ? "text-green-500" : "text-red-500"
            }`}
          >
            {position.outcome}
          </span>
          <span className="text-[10px]">
            {position.shares_held} shares @ ${position.average_price.toFixed(2)}
          </span>
        </div>
      </div>
      <div className="text-right shrink-0 ml-4">
        <span className={`text-xs font-bold ${isProfit ? "text-green-500" : "text-red-500"}`}>
          {isProfit ? "+" : "-"}{formatUSD(pnl)}
        </span>
      </div>
    </div>
  )
}

function PositionsList({ positions, loading, hasMore, onLoadMore }: PositionsListProps) {
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

  return (
    <div className="rounded-xl border border-border bg-card p-4 text-xs/relaxed">
      <h3 className="mb-3 text-sm font-medium">Positions</h3>
      {loading && positions.length === 0 ? (
        <div className="py-6 text-center text-muted-foreground">
          <Spinner className="size-5" />
        </div>
      ) : positions.length === 0 ? (
        <div className="py-6 text-center text-muted-foreground">No positions</div>
      ) : (
        <>
          <div>
            {positions.map((p) => (
              <PositionRow key={p.id} position={p} />
            ))}
          </div>
          <div ref={sentinelRef} className="flex justify-center py-3">
            {loading && <Spinner className="size-5" />}
          </div>
        </>
      )}
    </div>
  )
}

export { PositionsList }
export default memo(PositionsList)

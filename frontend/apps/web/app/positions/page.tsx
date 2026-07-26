"use client"

import { useState } from "react"
import { PositionsList } from "@/components/orders/positions-list"
import { usePositions } from "@/hooks/use-positions"
import { SkeletonPositionsList } from "@/components/shared/skeletons"
import { cn } from "@workspace/ui/lib/utils"

const FILTERS = ["All", "Winning", "Losing"] as const

export default function PositionsPage() {
  const { data, isLoading, fetchNextPage, hasNextPage } = usePositions()
  const [filter, setFilter] = useState<string>("All")

  const positions = (data?.positions ?? []).filter((p) => {
    if (filter === "Winning") return (p.unrealized_pnl ?? 0) > 0
    if (filter === "Losing") return (p.unrealized_pnl ?? 0) < 0
    return true
  })

  const totalUnrealizedPnl = positions.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0)
  const totalRealizedPnl = positions.reduce((s, p) => s + (p.realized_pnl ?? 0), 0)

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Positions</h1>
        <p className="mt-1 text-muted-foreground">Your active positions and P&amp;L</p>
      </div>

      {!isLoading && positions.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          {[
            { label: "Positions", value: positions.length, color: "" },
            { label: "Unrealized P&L", value: `$${totalUnrealizedPnl.toFixed(2)}`, color: totalUnrealizedPnl >= 0 ? "text-green-500" : "text-red-500" },
            { label: "Realized P&L", value: `$${totalRealizedPnl.toFixed(2)}`, color: totalRealizedPnl >= 0 ? "text-green-500" : "text-red-500" },
            { label: "Total P&L", value: `$${(totalUnrealizedPnl + totalRealizedPnl).toFixed(2)}`, color: (totalUnrealizedPnl + totalRealizedPnl) >= 0 ? "text-green-500" : "text-red-500" },
          ].map(({ label, value, color }) => (
            <div key={label} className="rounded-lg border border-border bg-card p-3 text-center">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</div>
              <div className={cn("text-sm font-semibold", color)}>{typeof value === "number" ? value : value}</div>
            </div>
          ))}
        </div>
      )}

      {!isLoading && positions.length > 0 && (
        <div className="flex items-center gap-1 mb-4 border-b border-border">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "px-3 py-1.5 text-xs font-medium border-b-2 -mb-px transition-colors",
                filter === f
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              {f}
            </button>
          ))}
        </div>
      )}

      {isLoading ? (
        <SkeletonPositionsList rows={5} />
      ) : (
        <PositionsList
          positions={positions}
          loading={false}
          hasMore={hasNextPage ?? false}
          onLoadMore={fetchNextPage}
        />
      )}
    </div>
  )
}

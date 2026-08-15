"use client"

import { memo, useCallback, useEffect, useRef } from "react"
import { cn } from "@workspace/ui/lib/utils"
import { Spinner } from "@workspace/ui/components/spinner"
import type { Trade } from "@/hooks/api/types/market"

function formatTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diff = (now.getTime() - d.getTime()) / 1000
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

const TradeRow = memo(function TradeRow({ trade }: { trade: Trade }) {
  const total = Number(trade.total ?? Number(trade.price) * Number(trade.amount))

  return (
    <div role="listitem" className="grid grid-cols-5 sm:grid-cols-7 gap-1.5 sm:gap-2 py-2.5 px-1 text-xs items-center border-b border-border/40 last:border-0">
      <span className="text-muted-foreground truncate font-medium">{trade.username}</span>
      <span
        className={cn(
          "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-center",
          trade.side === "buy"
            ? "bg-green-500/10 text-green-500"
            : "bg-red-500/10 text-red-500"
        )}
      >
        {trade.side}
      </span>
      <span className="capitalize font-medium truncate hidden sm:inline">{trade.outcome}</span>
      <span className="text-right font-medium tabular-nums">{Number(trade.amount).toFixed(0)}</span>
      <span className="text-right text-muted-foreground tabular-nums hidden sm:inline">${Number(trade.price).toFixed(3)}</span>
      <span className="text-right font-semibold tabular-nums">${total.toFixed(2)}</span>
      <span className="text-right text-muted-foreground hidden sm:inline">{formatTime(trade.executed_at)}</span>
    </div>
  )
})

interface TradeFeedProps {
  trades: Trade[]
  loading?: boolean
  hasMore?: boolean
  fetchNextPage?: () => void
  isFetchingNextPage?: boolean
  title?: string
}

function TradeFeed({ trades, loading, hasMore, fetchNextPage, isFetchingNextPage, title }: TradeFeedProps) {
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!hasMore || !fetchNextPage) return
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasMore && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { rootMargin: "200px" }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, fetchNextPage, isFetchingNextPage])

  if (loading && trades.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner className="size-5" />
      </div>
    )
  }

  if (trades.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">No trades yet</div>
    )
  }

  return (
    <section aria-label={title ?? "Trade feed"}>
      {title && <h3 className="mb-3 text-sm font-semibold text-foreground">{title}</h3>}
      <div role="row" className="grid grid-cols-5 sm:grid-cols-7 gap-1.5 sm:gap-2 px-1 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground border-b border-border">
        <span role="columnheader">Trader</span>
        <span role="columnheader" className="text-center">Side</span>
        <span role="columnheader" className="hidden sm:inline">Outcome</span>
        <span role="columnheader" className="text-right">Shares</span>
        <span role="columnheader" className="text-right hidden sm:inline">Price</span>
        <span role="columnheader" className="text-right">Total</span>
        <span role="columnheader" className="text-right hidden sm:inline">Time</span>
      </div>
      <div className="max-h-80 overflow-y-auto scrollbar-hide" role="list">
        {trades.map((trade) => (
          <TradeRow key={trade.id} trade={trade} />
        ))}
        {hasMore && (
          <div ref={sentinelRef} role="status" className="flex justify-center py-3">
            {isFetchingNextPage ? <Spinner className="size-4" /> : <span className="text-[10px] text-muted-foreground">Scroll for more</span>}
          </div>
        )}
      </div>
    </section>
  )
}

export { TradeFeed, TradeRow }

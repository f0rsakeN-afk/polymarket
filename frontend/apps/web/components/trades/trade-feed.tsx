"use client"

import { memo, useCallback, useEffect, useRef } from "react"
import { cn } from "@workspace/ui/lib/utils"
import { Spinner } from "@workspace/ui/components/spinner"
import type { Trade } from "@/lib/types/api"

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
  const total = trade.total ?? trade.price * trade.amount

  return (
    <div className="grid grid-cols-7 gap-2 py-2.5 px-1 text-xs items-center border-b border-border/40 last:border-0">
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
      <span className="capitalize font-medium truncate">{trade.outcome}</span>
      <span className="text-right font-medium tabular-nums">{trade.amount.toFixed(0)}</span>
      <span className="text-right text-muted-foreground tabular-nums">${trade.price.toFixed(3)}</span>
      <span className="text-right font-semibold tabular-nums">${total.toFixed(2)}</span>
      <span className="text-right text-muted-foreground">{formatTime(trade.executed_at)}</span>
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
    <div>
      {title && <h3 className="mb-3 text-sm font-semibold text-foreground">{title}</h3>}
      <div className="grid grid-cols-7 gap-2 px-1 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground border-b border-border">
        <span>Trader</span>
        <span className="text-center">Side</span>
        <span>Outcome</span>
        <span className="text-right">Shares</span>
        <span className="text-right">Price</span>
        <span className="text-right">Total</span>
        <span className="text-right">Time</span>
      </div>
      <div className="max-h-80 overflow-y-auto scrollbar-hide">
        {trades.map((trade) => (
          <TradeRow key={trade.id} trade={trade} />
        ))}
        {hasMore && (
          <div ref={sentinelRef} className="flex justify-center py-3">
            {isFetchingNextPage ? <Spinner className="size-4" /> : <span className="text-[10px] text-muted-foreground">Scroll for more</span>}
          </div>
        )}
      </div>
    </div>
  )
}

export { TradeFeed, TradeRow }

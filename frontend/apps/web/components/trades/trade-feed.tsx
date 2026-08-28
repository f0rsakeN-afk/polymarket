"use client"

import { memo, useRef } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { cn } from "@workspace/ui/lib/utils"
import { Spinner } from "@workspace/ui/components/spinner"
import { Card } from "@workspace/ui/components/card"
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

const COLUMNS = [
  { label: "Trader", width: "20%" },
  { label: "Side", width: "10%" },
  { label: "Outcome", width: "15%", hiddenSm: true },
  { label: "Shares", width: "10%", hiddenSm: true, align: "right" },
  { label: "Price", width: "10%", hiddenSm: true, align: "right" },
  { label: "Total", width: "15%", align: "right" },
  { label: "Time", width: "20%", hiddenSm: true, align: "right" },
]

const TradeRow = memo(function TradeRow({ trade }: { trade: Trade }) {
  const total = Number(trade.total ?? Number(trade.price) * Number(trade.amount))

  return (
    <div
      className="grid hover:bg-accent/30 transition-colors"
      style={{ gridTemplateColumns: COLUMNS.map((c) => c.width).join(" ") }}
    >
      <div className="px-3 py-2.5 text-muted-foreground truncate font-medium">{trade.username}</div>
      <div className="px-3 py-2.5">
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide inline-block",
            trade.side === "buy"
              ? "bg-green-500/10 text-green-500"
              : "bg-red-500/10 text-red-500"
          )}
        >
          {trade.side}
        </span>
      </div>
      <div className="px-3 py-2.5 capitalize font-medium hidden sm:block">{trade.outcome}</div>
      <div className="px-3 py-2.5 text-right font-medium tabular-nums hidden sm:block">{Number(trade.amount).toFixed(0)}</div>
      <div className="px-3 py-2.5 text-right text-muted-foreground tabular-nums hidden sm:block">${Number(trade.price).toFixed(3)}</div>
      <div className="px-3 py-2.5 text-right font-semibold tabular-nums">${total.toFixed(2)}</div>
      <div className="px-3 py-2.5 text-right text-muted-foreground hidden sm:block">{formatTime(trade.executed_at)}</div>
    </div>
  )
})

interface TradeFeedProps {
  trades: Trade[]
  loading?: boolean
  title?: string
  listRef?: React.RefObject<HTMLDivElement | null>
}

const TradeFeed = memo(function TradeFeed({ trades, loading, title, listRef }: TradeFeedProps) {
  const parentRef = useRef<HTMLDivElement>(null)

  const rowVirtualizer = useVirtualizer({
    count: trades.length,
    getScrollElement: () => listRef?.current ?? parentRef.current,
    estimateSize: () => 44,
    overscan: 5,
  })

  if (loading && trades.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner className="size-5" />
      </div>
    )
  }

  if (trades.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">
        No trades yet
      </div>
    )
  }

  return (
    <section aria-label={title ?? "Trade feed"}>
      {title && <h3 className="mb-3 text-sm font-semibold text-foreground">{title}</h3>}
      <Card className="overflow-hidden pt-0">
        <div ref={parentRef} className="overflow-auto hide-scrollbar" style={{ maxHeight: "500px", minHeight: "200px" }}>
          {/* Header */}
          <div
            className="sticky top-0 z-20 bg-muted grid border-b border-border text-[13px] font-medium text-muted-foreground"
            style={{ gridTemplateColumns: COLUMNS.map((c) => c.width).join(" ") }}
          >
            {COLUMNS.map((col) => (
              <div
                key={col.label}
                className={cn("px-3 py-2", col.align === "right" && "text-right", col.hiddenSm && "hidden sm:block")}
              >
                {col.label}
              </div>
            ))}
          </div>
          {/* Virtualized body */}
          <div
            ref={listRef}
            style={{
              height: `${rowVirtualizer.getTotalSize()}px`,
              width: "100%",
              position: "relative",
            }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const trade = trades[virtualRow.index]!
              return (
                <div
                  key={trade.id}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: `${virtualRow.size}px`,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  <TradeRow trade={trade} />
                </div>
              )
            })}
          </div>
        </div>
      </Card>
    </section>
  )
})

export { TradeFeed, TradeRow }

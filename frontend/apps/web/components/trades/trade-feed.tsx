"use client"

import { memo } from "react"
import { cn } from "@workspace/ui/lib/utils"
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
  return (
    <div className="flex items-center justify-between py-2.5 px-1">
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="text-[10px] text-muted-foreground truncate shrink-0">{trade.username}</span>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide shrink-0",
            trade.side === "buy"
              ? "bg-green-500/10 text-green-500"
              : "bg-red-500/10 text-red-500"
          )}
        >
          {trade.side}
        </span>
        <span className="text-xs capitalize font-medium shrink-0">{trade.outcome}</span>
      </div>
      <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0">
        <span className="font-medium">{trade.amount.toFixed(0)} @ <span className="text-foreground">${trade.price.toFixed(3)}</span></span>
        <span className="w-12 text-right">{formatTime(trade.timestamp)}</span>
      </div>
    </div>
  )
})

interface TradeFeedProps {
  trades: Trade[]
  loading?: boolean
  title?: string
}

function TradeFeed({ trades, loading, title }: TradeFeedProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      {title && (
        <h3 className="mb-3 text-sm font-semibold text-foreground">{title}</h3>
      )}
      {loading && trades.length === 0 ? (
        <div className="py-8 text-center text-xs text-muted-foreground">Loading trades...</div>
      ) : trades.length === 0 ? (
        <div className="py-8 text-center text-xs text-muted-foreground">No trades yet</div>
      ) : (
        <div className="divide-y divide-border overflow-y-auto max-h-72 scrollbar-hide">
          {trades.map((trade) => (
            <TradeRow key={trade.id} trade={trade} />
          ))}
        </div>
      )}
    </div>
  )
}

export { TradeFeed, TradeRow }

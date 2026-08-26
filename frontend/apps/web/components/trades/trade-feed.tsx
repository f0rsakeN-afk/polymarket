"use client"

import { memo, useRef } from "react"
import { cn } from "@workspace/ui/lib/utils"
import { Spinner } from "@workspace/ui/components/spinner"
import { Card } from "@workspace/ui/components/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
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
    <TableRow className="hover:bg-accent/30 transition-colors">
      <TableCell className="text-muted-foreground truncate font-medium">{trade.username}</TableCell>
      <TableCell>
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
      </TableCell>
      <TableCell className="capitalize font-medium hidden sm:table-cell">{trade.outcome}</TableCell>
      <TableCell className="text-right font-medium tabular-nums hidden sm:table-cell">{Number(trade.amount).toFixed(0)}</TableCell>
      <TableCell className="text-right text-muted-foreground tabular-nums hidden sm:table-cell">${Number(trade.price).toFixed(3)}</TableCell>
      <TableCell className="text-right font-semibold tabular-nums">${total.toFixed(2)}</TableCell>
      <TableCell className="text-right text-muted-foreground hidden sm:table-cell">{formatTime(trade.executed_at)}</TableCell>
    </TableRow>
  )
})

interface TradeFeedProps {
  trades: Trade[]
  loading?: boolean
  title?: string
  listRef?: React.RefObject<HTMLDivElement | null>
}

function TradeFeed({ trades, loading, title, listRef }: TradeFeedProps) {
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
        <div ref={listRef} className="overflow-auto" style={{ maxHeight: "500px", minHeight: "200px" }}>
          <Table noWrapper className="w-full" style={{ tableLayout: "fixed" }}>
            <colgroup>
              <col className="w-[20%]" />
              <col className="w-[10%]" />
              <col className="w-[15%]" />
              <col className="w-[10%]" />
              <col className="w-[10%]" />
              <col className="w-[15%]" />
              <col className="w-[20%]" />
            </colgroup>
            <TableHeader className="sticky top-0 z-20 bg-muted">
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-muted-foreground">Trader</TableHead>
                <TableHead className="text-muted-foreground">Side</TableHead>
                <TableHead className="text-muted-foreground hidden sm:table-cell">Outcome</TableHead>
                <TableHead className="text-muted-foreground text-right hidden sm:table-cell">Shares</TableHead>
                <TableHead className="text-muted-foreground text-right hidden sm:table-cell">Price</TableHead>
                <TableHead className="text-muted-foreground text-right">Total</TableHead>
                <TableHead className="text-muted-foreground text-right hidden sm:table-cell">Time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.map((trade) => (
                <TradeRow key={trade.id} trade={trade} />
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>
    </section>
  )
}

export { TradeFeed, TradeRow }

"use client"

import { memo, useRef } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { cn } from "@workspace/ui/lib/utils"
import { Spinner } from "@workspace/ui/components/spinner"
import { Card } from "@workspace/ui/components/card"
import type { Trade } from "@/hooks/api/types/market"

function formatTime(iso: string | null | undefined) {
  if (!iso) return "•"
  const d = new Date(iso)
  const now = new Date()
  const diff = (now.getTime() - d.getTime()) / 1000
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

type Column = {
  label: string;
  /** Fraction of the row. Must sum to 1 within its own set. */
  width: string;
  /** Hidden below `sm`. Only ever set on the desktop set. */
  hiddenSm?: boolean;
  align?: "right";
};

/**
 * Two separate column sets, not one set with responsive hiding.
 *
 * Hiding a cell with `display:none` removes it from the grid, so the surviving
 * percentage tracks keep their widths and only fill part of the row. The
 * previous single set summed to 100% across all seven columns, which left a
 * phone showing Trader(20%) + Side(10%) + Total(15%) = 45% of the row with the
 * remaining 55% blank, and "Total" stranded mid-row instead of flush right.
 *
 * Each set sums to 100% on its own, so the row is full-width at every size.
 */
const DESKTOP_COLUMNS: Column[] = [
  { label: "Trader", width: "20%" },
  { label: "Side", width: "10%" },
  { label: "Outcome", width: "15%" },
  { label: "Shares", width: "10%", align: "right" },
  { label: "Price", width: "10%", align: "right" },
  { label: "Total", width: "15%", align: "right" },
  { label: "Time", width: "20%", align: "right" },
];

/**
 * Phone: trader and side, then the notional. Price and shares are dropped
 * because `Total` is their product and is the number that matters here; outcome
 * moves into the second line below.
 */
const MOBILE_COLUMNS: Column[] = [
  { label: "Trader", width: "45%" },
  { label: "Side", width: "25%" },
  { label: "Total", width: "30%", align: "right" },
];

/**
 * Exported for tests: each column set must fill the row on its own.
 *
 * `display:none` drops a cell out of its grid, so the sibling percentage
 * tracks keep their widths and stop short of 100%. This is the invariant that
 * was violated on phones - the old single set summed to 100% across all seven
 * columns, leaving the row 55% empty below `sm`.
 */
function columnWidthSum(columns: Column[]): number {
  return columns.reduce((sum, c) => sum + Number.parseFloat(c.width), 0);
}

const SideBadge = memo(function SideBadge({ side }: { side: string }) {
  return (
    <span
      className={cn(
        "inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide",
        side === "buy" ? "bg-green-500/10 text-green-700" : "bg-red-500/10 text-red-700"
      )}
    >
      {side}
    </span>
  );
});

const TradeRow = memo(function TradeRow({ trade }: { trade: Trade }) {
  // Backend has no `total` field • notional is always price × shares.
  const total = Number(trade.price) * Number(trade.amount);

  return (
    // One row, one grid. Both column sets are rendered into the same track
    // count and swapped by breakpoint, so there is no second row to keep in
    // sync and the virtualizer's single height still holds.
    <div className="grid grid-cols-[45%_25%_30%] transition-colors hover:bg-accent/30 sm:grid-cols-[20%_10%_15%_10%_10%_15%_20%]">
      <div className="min-w-0 truncate px-3 py-2.5 font-medium text-muted-foreground">
        <div className="truncate">{trade.username}</div>
        {/* Outcome has no column of its own on a phone, so it moves under the
            name rather than being dropped - the trader still needs to know
            which outcome they took. */}
        <div className="truncate text-xs font-normal capitalize text-muted-foreground/70 sm:hidden">
          {trade.outcome}
        </div>
      </div>

      <div className="px-3 py-2.5">
        <SideBadge side={trade.side} />
      </div>

      <div className="hidden px-3 py-2.5 text-right font-medium tabular-nums sm:block">
        {Number(trade.amount).toFixed(0)}
      </div>

      <div className="hidden px-3 py-2.5 text-right tabular-nums text-muted-foreground sm:block">
        ${Number(trade.price).toFixed(3)}
      </div>

      <div className="px-3 py-2.5 text-right font-semibold tabular-nums">${total.toFixed(2)}</div>

      <div className="hidden px-3 py-2.5 text-right text-muted-foreground sm:block">
        {formatTime(trade.executed_at)}
      </div>
    </div>
  );
});

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
      <div role="status" className="flex h-40 items-center justify-center">
        <Spinner className="size-5" />
        <span className="sr-only">Loading…</span>
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
          {/*
            Header mirrors the row's breakpoint grid exactly. A `hidden` cell here
            still consumed its percentage track, so the header drifted out of
            alignment with the body it labels.
          */}
          <div className="sticky top-0 z-20 grid grid-cols-[45%_25%_30%] border-b border-border bg-muted text-[13px] font-medium text-muted-foreground sm:grid-cols-[20%_10%_15%_10%_10%_15%_20%]">
            <div className="px-3 py-2">Trader</div>
            <div className="px-3 py-2">Side</div>
            <div className="hidden px-3 py-2 text-right sm:block">Shares</div>
            <div className="hidden px-3 py-2 text-right sm:block">Price</div>
            <div className="px-3 py-2 text-right">Total</div>
            <div className="hidden px-3 py-2 text-right sm:block">Time</div>
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

export {
  TradeFeed,
  TradeRow,
  DESKTOP_COLUMNS,
  MOBILE_COLUMNS,
  columnWidthSum,
};

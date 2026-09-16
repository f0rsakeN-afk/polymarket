"use client"

import { memo, useCallback, useState } from "react"
import dynamic from "next/dynamic"
import Link from "next/link"
import { useMarketSocket } from "@/hooks/use-market-socket"
import type { LiveLinePoint } from "@workspace/ui/components/charts/live-line-chart"
import type { MarketResponse } from "@/hooks/api/types/market"

// visx/d3 chart code splits into its own chunk and never SSR-renders —
// the carousel ships without it and hydrates charts after first paint.
function ChartFallback() {
  return <div className="h-24 animate-pulse rounded-md bg-muted/60" aria-hidden="true" />
}

const LiveLineChart = dynamic(
  () => import("@workspace/ui/components/charts/live-line-chart").then((m) => ({ default: m.LiveLineChart })),
  { ssr: false, loading: ChartFallback }
)
const LiveLine = dynamic(
  () => import("@workspace/ui/components/charts/live-line").then((m) => ({ default: m.LiveLine })),
  { ssr: false }
)

interface TrendingCarouselItemProps {
  market: MarketResponse
}

function TrendingCarouselItem({ market }: TrendingCarouselItemProps) {
  const [priceHistory, setPriceHistory] = useState<LiveLinePoint[]>(() => {
    const now = Math.floor(Date.now() / 1000)
    const seed = Number(market.yes_price)
    return [
      { time: now - 60, value: seed },
      { time: now, value: seed },
    ]
  })

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; yes_price?: number }
    if (msg.type === "market:price_update" && msg.yes_price != null) {
      const now = Math.floor(Date.now() / 1000)
      setPriceHistory((prev) => {
        const next = [
          ...prev,
          { time: now, value: msg.yes_price ?? prev.at(-1)?.value ?? 0 },
        ]
        return next.slice(-60)
      })
    }
  }, [])

  const { status } = useMarketSocket({
    marketId: market.id,
    onMessage: handleWSMessage,
    enabled: !!market.id,
  })

  const prob = Math.round(Number(market.yes_price) * 100)

  return (
    <Link
      href={`/markets/${market.slug}`}
      role="listitem"
      aria-label={`${market.question} — YES ${prob}%, NO ${100 - prob}%`}
      className="flex w-[280px] shrink-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/30 hover:shadow-md"
    >
      {/* Header row */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-semibold tracking-widest text-muted-foreground uppercase">
          PredictX
        </span>
        {market.category && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {market.category}
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          <span
            className={
              status === "connected"
                ? "size-1.5 rounded-full bg-green-600 dark:bg-green-400"
                : status === "connecting"
                  ? "size-1.5 animate-pulse rounded-full bg-yellow-600 dark:bg-yellow-400"
                  : "size-1.5 rounded-full bg-muted-foreground/40"
            }
            role="status"
            aria-label={`WebSocket ${status}`}
          />
          <span className="text-[10px] font-medium text-muted-foreground">
            {status === "connected" ? "Live" : status === "connecting" ? "Sync" : "Off"}
          </span>
        </span>
      </div>

      {/* Question */}
      <h3 className="line-clamp-2 min-h-8 flex-1 text-sm leading-snug font-medium text-foreground">
        {market.question}
      </h3>

      {/* Mini chart */}
      <div className="h-24 overflow-hidden rounded-md" aria-hidden="true">
        <LiveLineChart
          data={priceHistory}
          value={priceHistory.at(-1)?.value ?? Number(market.yes_price)}
          window={300}
          numXTicks={3}
          height={96}
        >
          <LiveLine dataKey="value" stroke="var(--primary)" fill />
        </LiveLineChart>
      </div>

      {/* YES/NO prices + volume */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div>
            <div className="mb-0.5 text-[10px] tracking-wider text-muted-foreground uppercase">
              Yes
            </div>
            <div
              className="text-sm font-bold text-green-700 tabular-nums"
            >
              {prob}%
            </div>
          </div>
          <div>
            <div className="mb-0.5 text-[10px] tracking-wider text-muted-foreground uppercase">
              No
            </div>
            <div
              className="text-sm font-bold text-red-700 tabular-nums"
            >
              {100 - prob}%
            </div>
          </div>
        </div>
        <div className="text-right">
          <div className="mb-0.5 text-[10px] tracking-wider text-muted-foreground uppercase">
            Volume
          </div>
          <div className="text-xs font-medium text-foreground tabular-nums">
            $
            {Number(market.total_volume) >= 1_000_000
              ? `${(Number(market.total_volume) / 1_000_000).toFixed(1)}M`
              : Number(market.total_volume) >= 1_000
                ? `${(Number(market.total_volume) / 1_000).toFixed(1)}K`
                : `$${Number(market.total_volume).toFixed(0)}`}
          </div>
        </div>
      </div>
    </Link>
  )
}

export default memo(TrendingCarouselItem)

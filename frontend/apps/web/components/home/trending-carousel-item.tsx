"use client"

import { memo, useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useMarketSocket } from "@/hooks/use-market-socket"
import { LiveLineChart } from "@workspace/ui/components/charts/live-line-chart"
import { LiveLine } from "@workspace/ui/components/charts/live-line"
import type { LiveLinePoint } from "@workspace/ui/components/charts/live-line-chart"
import type { MarketResponse } from "@/hooks/api/types/market"
import { cn } from "@workspace/ui/lib/utils"

interface TrendingCarouselItemProps {
  market: MarketResponse
}

function TrendingCarouselItem({ market }: TrendingCarouselItemProps) {
  const [priceHistory, setPriceHistory] = useState<LiveLinePoint[]>([])

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; yes_price?: number }
    if (msg.type === "market:price_update" && msg.yes_price != null) {
      const now = Math.floor(Date.now() / 1000)
      setPriceHistory((prev) => {
        const next = [...prev, { time: now, value: msg.yes_price ?? prev.at(-1)?.value ?? 0 }]
        return next.slice(-60)
      })
    }
  }, [])

  const { status } = useMarketSocket({
    marketId: market.id,
    onMessage: handleWSMessage,
    enabled: !!market.id,
  })

  useEffect(() => {
    const now = Math.floor(Date.now() / 1000)
    const seed = Number(market.yes_price)
    setPriceHistory([
      { time: now - 300, value: seed * 0.97 },
      { time: now - 240, value: seed * 1.01 },
      { time: now - 180, value: seed * 0.99 },
      { time: now - 120, value: seed * 1.02 },
      { time: now - 60, value: seed * 0.98 },
      { time: now, value: seed },
    ])
  }, [market.yes_price])

  const prob = Math.round(Number(market.yes_price) * 100)
  const wsColor = status === "connected" ? "oklch(0.72 0.19 145)" : status === "connecting" ? "oklch(0.79 0.18 85)" : "oklch(0.7 0.0 0)"
  const yesColor = "oklch(0.63 0.15 145)"
  const noColor = "oklch(0.63 0.24 27)"

  return (
    <Link
      href={`/markets/${market.slug}`}
      role="listitem"
      aria-label={`${market.question} — YES ${prob}%, NO ${100 - prob}%`}
      className="flex-shrink-0 w-[280px] rounded-xl border border-border bg-card p-4 hover:border-primary/30 transition-colors flex flex-col gap-3"
    >
      {/* Header row */}
      <div className="flex items-center gap-2">
        <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-muted-foreground">POLYMARKET</span>
        {market.category && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[0.5rem] text-muted-foreground">
            {market.category}
          </span>
        )}
        <span
          className="ml-auto size-1.5 rounded-full shrink-0"
          style={{ backgroundColor: wsColor }}
          role="status"
          aria-label={`WebSocket ${status}`}
        />
      </div>

      {/* Question */}
      <h3 className="text-xs font-medium text-foreground leading-snug line-clamp-2 flex-1">
        {market.question}
      </h3>

      {/* Mini chart */}
      <div className="h-24 rounded-md overflow-hidden" aria-hidden="true">
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
            <div className="text-[0.5rem] uppercase tracking-wider text-muted-foreground mb-0.5">YES</div>
            <div className="text-sm font-bold tabular-nums" style={{ color: yesColor }}>{prob}%</div>
          </div>
          <div>
            <div className="text-[0.5rem] uppercase tracking-wider text-muted-foreground mb-0.5">NO</div>
            <div className="text-sm font-bold tabular-nums" style={{ color: noColor }}>{100 - prob}%</div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[0.5rem] uppercase tracking-wider text-muted-foreground mb-0.5">Volume</div>
          <div className="text-xs font-medium tabular-nums text-foreground">
            ${Number(market.total_volume) >= 1_000_000
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

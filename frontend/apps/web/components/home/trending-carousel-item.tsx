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
  const statusColor = status === "connected" ? "bg-green-500" : status === "connecting" ? "bg-yellow-500 animate-pulse" : "bg-muted"

  return (
    <Link
      href={`/markets/${market.slug}`}
      role="listitem"
      aria-label={`${market.question} — YES ${prob}%, NO ${100 - prob}%`}
      className="flex-shrink-0 w-[320px] rounded-xl border border-border bg-card p-4 hover:border-primary/30 transition-colors"
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[9px] font-bold tracking-widest text-muted-foreground">POLYMARKET</span>
        {market.category && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground">
            {market.category}
          </span>
        )}
        <span className={cn("ml-auto size-1.5 rounded-full shrink-0", statusColor)} role="status" aria-label={`WebSocket ${status}`} />
      </div>
      <h3 className="text-xs font-medium leading-snug line-clamp-2 mb-3">{market.question}</h3>
      <div className="h-28 mb-3 overflow-hidden rounded-md" aria-hidden="true">
        <LiveLineChart
          data={priceHistory}
          value={priceHistory.at(-1)?.value ?? Number(market.yes_price)}
          window={300}
          numXTicks={3}
          height={112}
        >
          <LiveLine dataKey="value" stroke="var(--chart-1)" fill />
        </LiveLineChart>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div>
            <div className="text-[9px] text-muted-foreground">YES</div>
            <div className="text-sm font-bold text-green-500">{prob}%</div>
          </div>
          <div>
            <div className="text-[9px] text-muted-foreground">NO</div>
            <div className="text-sm font-bold text-red-500">{100 - prob}%</div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[9px] text-muted-foreground">Volume</div>
          <div className="text-xs font-medium">${(Number(market.total_volume) / 1_000_000).toFixed(1)}M</div>
        </div>
      </div>
    </Link>
  )
}

export default memo(TrendingCarouselItem)

"use client"

import { memo, useCallback, useState } from "react"
import dynamic from "next/dynamic"
import Link from "next/link"
import { useMarketSocket } from "@/hooks/use-market-socket"
import type { LiveLinePoint } from "@workspace/ui/components/charts/live-line-chart"
import type { MarketResponse } from "@/hooks/api/types/market"

// visx/d3 chart code splits into its own chunk and never SSR-renders •
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

/**
 * Parse a REST `yes_price` into a usable number, or null when it is absent.
 *
 * `Number(null)` is 0 and `Number("")` is 0, so a plain `Number(...)` plus a
 * `Number.isFinite` guard accepts a missing price as a real 0. That made the
 * card render a confident "0%" - a real, wrong probability - for a market whose
 * price simply had not loaded. Anything non-numeric, null or undefined is null
 * so the caller can fall back to an even split.
 */
function parseYesPrice(raw: string | number | null | undefined): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const parsed = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function TrendingCarouselItem({ market }: TrendingCarouselItemProps) {
  // Live price, seeded from the REST payload and moved by every WS frame.
  //
  // The card used to re-read `market.yes_price` for everything it displayed,
  // so the sparkline tracked live while the "62%" beside it stayed frozen at
  // whatever the list fetch returned - the chart and the number disagreeing on
  // screen. One source of truth for both.
  const [livePrice, setLivePrice] = useState<number | null>(() =>
    parseYesPrice(market.yes_price)
  )

  const [priceHistory, setPriceHistory] = useState<LiveLinePoint[]>(() => {
    const parsed = parseYesPrice(market.yes_price)
    // No usable price seeds no points rather than a 0: a zero seed flowed into
    // the y-domain and drew the sparkline flat on the floor.
    if (parsed === null) return []
    const now = Math.floor(Date.now() / 1000)
    return [
      { time: now - 60, value: parsed },
      { time: now, value: parsed },
    ]
  })

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; yes_price?: number }
    if (msg.type !== "market:price_update" || !Number.isFinite(msg.yes_price)) return

    const price = msg.yes_price as number
    setLivePrice(price)

    setPriceHistory((prev) => {
      // `msg.yes_price ?? 0` would append a hard 0 for a malformed frame - the
      // exact "graph dives to zero" failure fixed on the market page.
      if (!Number.isFinite(msg.yes_price)) return prev
      const now = Math.floor(Date.now() / 1000)
      const seed: LiveLinePoint[] =
        prev.length === 0
          ? [
              { time: now - 60, value: price },
              { time: now, value: price },
            ]
          : prev
      return [...seed, { time: now, value: price }].slice(-60)
    })
  }, [])

  const { status } = useMarketSocket({
    marketId: market.id,
    onMessage: handleWSMessage,
    enabled: !!market.id,
  })

  // Falls back to the REST price if no frame has arrived, then to an even
  // split.
  //
  // The `?? 0.5` is load-bearing: `yes_price` is typed string, and a null or
  // empty value reaches here. `Number(null)` is 0, not NaN, so a plain
  // `Number(...)` guard passed and the card rendered a confident "0%" for a
  // market whose price was simply absent - worse than showing nothing. The
  // fallback is read first so both null and a non-numeric string land on 0.5.
  const shownPrice = livePrice ?? parseYesPrice(market.yes_price) ?? 0.5
  const prob = Math.round(Math.min(Math.max(shownPrice, 0), 1) * 100)

  return (
    <Link
      href={`/markets/${market.slug}`}
      role="listitem"
      aria-label={`${market.question} • YES ${prob}%, NO ${100 - prob}%`}
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

      {/* Mini chart. aria-hidden because the percentage beside it is the accessible
          value; a sparkline with no axis or labels is noise to announce. */}
      <div className="h-24 overflow-hidden rounded-md" aria-hidden="true">
        <LiveLineChart
          data={priceHistory}
          // Driven by the same live value as the percentage, so the badge on the
          // chart tip and the number in the footer cannot disagree.
          value={shownPrice}
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

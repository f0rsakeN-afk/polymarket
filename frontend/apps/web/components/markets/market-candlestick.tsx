"use client"

import dynamic from "next/dynamic"
import { cn } from "@workspace/ui/lib/utils"

import type { OHLCPoint } from "@/lib/utils/ohlc"
import { formatCents } from "@/lib/utils/ohlc"

/**
 * Candlestick view of a market's price history.
 *
 * The chart primitives live in the shared UI package and are loaded on demand:
 * the visx/d3 code is heavy and the market detail page paints its text and
 * order book first, so the chart is not worth blocking first paint for.
 */
const CandlestickChart = dynamic(
  () =>
    import("@workspace/ui/components/charts/candlestick-chart").then((m) => ({
      default: m.CandlestickChart,
    })),
  { ssr: false, loading: ChartFallback }
)

const Candlestick = dynamic(
  () => import("@workspace/ui/components/charts/candlestick").then((m) => ({ default: m.Candlestick })),
  { ssr: false }
)

const XAxis = dynamic(
  () => import("@workspace/ui/components/charts/x-axis").then((m) => ({ default: m.XAxis })),
  { ssr: false }
)

const YAxis = dynamic(
  () => import("@workspace/ui/components/charts/y-axis").then((m) => ({ default: m.YAxis })),
  { ssr: false }
)

const Grid = dynamic(
  () => import("@workspace/ui/components/charts/grid").then((m) => ({ default: m.Grid })),
  { ssr: false }
)

const ChartTooltip = dynamic(
  () =>
    import("@workspace/ui/components/charts/tooltip/chart-tooltip").then((m) => ({
      default: m.ChartTooltip,
    })),
  { ssr: false }
)

function ChartFallback() {
  return <div className="h-[200px] animate-pulse rounded-md bg-muted/60" aria-hidden="true" />
}

/** Green for a rising period, red for a falling one, grey for one that did not move. */
const UP = "#16a34a"
const DOWN = "#dc2626"
const FLAT = "#78716c"

export interface MarketCandlestickProps {
  data: OHLCPoint[]
  className?: string
  height?: number
  /**
   * How wide each candle is, in seconds.
   *
   * Used to label the time axis. A chart of one-minute candles needs to say
   * "14:32" on its axis, and a chart of one-day candles needs "Sep 22" — and
   * the default label is always the date, so on a minute chart every tick
   * would read the same thing and the axis would carry no information at all.
   */
  intervalSeconds?: number
}

/** The time axis label, suited to how wide the candles are. */
function axisTimeFormat(intervalSeconds: number): (date: Date) => string {
  const fmt = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
  const dayFmt = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  })

  // At a day or more, the clock time is noise and the date is the point.
  if (intervalSeconds >= 86400) return (date) => dayFmt.format(date)
  // At an hour or more, the date matters more than the minute.
  if (intervalSeconds >= 3600) {
    return (date) => `${dayFmt.format(date)} ${fmt.format(date)}`
  }
  return (date) => fmt.format(date)
}

export function MarketCandlestick({
  data,
  className,
  height = 200,
  intervalSeconds = 300,
}: MarketCandlestickProps) {
  if (data.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-xs text-muted-foreground">
        No price history yet
      </div>
    )
  }

  // The shared chart types its x-axis as a Date, so the unix seconds the API
  // hands back are converted once here rather than at every call site.
  const ohlc = data.map((d) => ({
    date: new Date(d.time * 1000),
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
  }))

  const tickFormat = axisTimeFormat(intervalSeconds)

  return (
    <CandlestickChart
      data={ohlc}
      className={cn("w-full", className)}
      style={{ height }}
      margin={{ top: 16, right: 44, bottom: 28, left: 44 }}
    >
      <Grid horizontal numTicksRows={4} />
      <Candlestick />
      <XAxis numTicks={5} tickFormat={tickFormat} />
      {/* Prices are probabilities, so the axis reads in cents like every other
          price on the page — 0.65 is "65¢", not "0.65". */}
      <YAxis numTicks={5} formatValue={formatCents} />
      <ChartTooltip
        showDots={false}
        /**
         * The crosshair takes the candle's own colour, so the line across the
         * chart says which way the period moved without the reader having to
         * look at the body to find out.
         */
        indicatorColor={(point) => {
          const open = Number(point.open)
          const close = Number(point.close)
          if (!Number.isFinite(open) || !Number.isFinite(close)) return UP
          // A period that did not move is neither a rise nor a fall, and the
          // crosshair says so — the same way the candle's body does.
          if (close === open) return FLAT
          return close > open ? UP : DOWN
        }}
        /**
         * The four prices, and what they say together.
         *
         * A candle without a tooltip is a shape: the reader can see that
         * something moved but not what it was or how far. Open, high, low and
         * close, plus the change across the period, is the whole reading of a
         * candle — and the change is computed here rather than left to the
         * reader, because "did this go up or down" is the first question a
         * candle chart is asked and the answer should not require arithmetic.
         */
        content={({ point }) => {
          const open = Number(point.open)
          const high = Number(point.high)
          const low = Number(point.low)
          const close = Number(point.close)
          if (![open, high, low, close].every(Number.isFinite)) return null

          const flat = close === open
          const up = close > open
          const color = flat ? FLAT : up ? UP : DOWN
          const change = close - open
          const changePct = open > 0 ? (change / open) * 100 : 0

          return (
            <div className="rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-md">
              <div className="mb-1.5 font-medium text-popover-foreground">
                {new Date(point.date as Date).toLocaleString("en-US", {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </div>
              <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 tabular-nums">
                <dt className="text-muted-foreground">Open</dt>
                <dd className="text-right">{formatCents(open)}</dd>
                <dt className="text-muted-foreground">High</dt>
                <dd className="text-right">{formatCents(high)}</dd>
                <dt className="text-muted-foreground">Low</dt>
                <dd className="text-right">{formatCents(low)}</dd>
                <dt className="text-muted-foreground">Close</dt>
                <dd className="text-right">{formatCents(close)}</dd>
                <dt className="text-muted-foreground">Change</dt>
                <dd className="text-right font-semibold" style={{ color }}>
                  {change >= 0 ? "+" : ""}
                  {(change * 100).toFixed(1)}¢ ({changePct >= 0 ? "+" : ""}
                  {changePct.toFixed(1)}%)
                </dd>
              </dl>
            </div>
          )
        }}
      />
    </CandlestickChart>
  )
}

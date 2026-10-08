"use client"

import { memo, useCallback, useMemo, useState } from "react"
import dynamic from "next/dynamic"
import Link from "next/link"
import { useMarketSocket } from "@/hooks/use-market-socket"
import { usePriceHistory } from "@/hooks/api/use-markets"
import { priceHistoryToPoints, buildLivePricePoint } from "@/lib/live-price"
import type { LiveLinePoint } from "@workspace/ui/components/charts/live-line-chart"
import { plottedOutcomeColors } from "@/lib/outcome-colors"
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
  // Real history, same source the market page charts. Without it the sparkline
  // seeded two identical points and waited for a WebSocket frame, so any market
  // that had not traded recently drew a dead straight line - which reads as a
  // broken chart rather than an unchanged price.
  const { data: historyData } = usePriceHistory(market.slug)

  const historyPoints = useMemo(
    // priceHistoryToPoints always sets `value`, so it satisfies LiveLinePoint;
    // the cast keeps the chart's required field from being re-derived here.
    () => priceHistoryToPoints(historyData as never) as LiveLinePoint[],
    [historyData]
  )

  // Live price, seeded from the REST payload and moved by every WS frame.
  //
  // The card used to re-read `market.yes_price` for everything it displayed,
  // so the sparkline tracked live while the "62%" beside it stayed frozen at
  // whatever the list fetch returned - the chart and the number disagreeing on
  // screen. One source of truth for both.
  const [livePrice, setLivePrice] = useState<number | null>(() =>
    parseYesPrice(market.yes_price)
  )

  // History is the base; live frames are appended by the WS handler. Seeded from
  // history rather than the current price so a market with real trading has a
  // curve immediately, and from the current price only when there is none.
  const [livePoints, setLivePoints] = useState<LiveLinePoint[]>([])

  // Anchor clock, captured once like the market page's seedTime. Date.now() in
  // the body of a useMemo is an impure render-time call: it shifts on every
  // re-render, so the seeded points moved each time anything else changed.
  const [seedTime] = useState(() => Math.floor(Date.now() / 1000))

  const priceHistory = useMemo(() => {
    // Real history wins. Without it the seed is two identical points, which
    // draws a dead straight line and reads as a broken chart rather than an
    // unchanged price.
    if (historyPoints.length > 0) {
      return [...historyPoints, ...livePoints].slice(-120)
    }

    const seed = parseYesPrice(market.yes_price)
    if (seed === null) return livePoints
    // Seed first, then live: the seed points are older, and the chart's tip is
    // the LAST point. Appending the seed last made the tip show the stale seed
    // instead of the newest price.
    return [
      { time: seedTime - 60, value: seed },
      { time: seedTime, value: seed },
      ...livePoints,
    ].slice(-120)
  }, [historyPoints, livePoints, market.yes_price, seedTime])

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; yes_price?: number; outcome_prices?: Record<string, number> }
    if (msg.type !== "market:price_update") return

    /*
     * buildLivePricePoint, not a hand-rolled `{time, value}`.
     *
     * A bare point carries only the primary `value`, so on a multi-outcome
     * market every per-outcome line lost its key at the live tip and - now that
     * getY renders a missing key as a gap rather than a fake 0 - the coloured
     * lines would break at the right edge. The server sends `outcome_prices` for
     * 3+ outcome markets, and this maps them onto their outcome names.
     */
    const point = buildLivePricePoint(msg, Math.floor(Date.now() / 1000))
    if (!point) return

    if (Number.isFinite(msg.yes_price)) setLivePrice(msg.yes_price as number)
    // buildLivePricePoint always sets `value`; the cast mirrors the history one.
    setLivePoints((prev) => [...prev, point as unknown as LiveLinePoint].slice(-60))
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

  /*
   * Named-outcome support, which is not the same thing as "more than two".
   *
   * The list endpoint's `outcomes` is nullable and carries no price, so the
   * per-outcome prices come from the same price-history payload the chart uses.
   * `yes_price`/`no_price` describe the binary pool; on a named market they are
   * not any of the outcomes, so they must not be displayed as if they were.
   */
  // `outcomes` is a fresh array when the list payload carries none (`market.outcomes`
  // is nullable), which would make every downstream memo recompute each render.
  const outcomes = useMemo(() => market.outcomes ?? [], [market.outcomes])

  /*
   * Binary means "the outcomes are the YES/NO pair" - not "there are two of
   * them". Counting outcomes gets a 2-way named market wrong: a Trump-vs-Biden
   * market has two outcomes, but rendering it as "Yes 55% / No 45%" labels them
   * with sides that do not exist, and it is not the binary book the AMM prices.
   *
   * Same rule as the market page (`isBinary` there = an outcome named "yes" and
   * one named "no"), so a card and its detail page always agree.
   *
   * Edge case: with NO outcome names there is nothing to judge by, so fall back
   * to the binary split - yes_price/no_price are then the only prices we have,
   * and an empty outcome list would render a card with no prices at all.
   */
  const isBinaryMarket = useMemo(() => {
    if (outcomes.length === 0) return true
    const names = outcomes.map((outcome) => outcome.name.toLowerCase())
    return names.includes("yes") && names.includes("no")
  }, [outcomes])

  const isMultiOutcome = !isBinaryMarket

  const displayOutcomes = useMemo(() => {
    if (!isMultiOutcome) return []

    // Seed from the price the API put on each outcome, so the card shows real
    // numbers on first paint. Reading only from price history meant a market
    // whose history had not been snapshotted yet rendered a column of "—" -
    // the API knows every outcome's price, so there is no reason to wait.
    const latest = new Map<string, number>()
    for (const outcome of outcomes) {
      const seeded = Number(outcome.price)
      if (Number.isFinite(seeded)) latest.set(outcome.name, seeded)
    }

    // History then overrides, newest last: it is the live source once it
    // exists. (History is ordered ascending, so the last entry carrying a
    // price for an outcome is its current one.)
    for (const point of historyPoints) {
      for (const outcome of outcomes) {
        const price = Number(point[outcome.name])
        if (Number.isFinite(price)) latest.set(outcome.name, price)
      }
    }

    return outcomes.map((outcome) => {
      const price = latest.get(outcome.name)
      return {
        name: outcome.name,
        // null rather than 0 for an outcome nothing can price: a fabricated
        // zero is a real, wrong probability.
        pct:
          price === undefined
            ? null
            : Math.round(Math.min(Math.max(price, 0), 1) * 100),
      }
    })
  }, [historyPoints, isMultiOutcome, outcomes])

  return (
    <Link
      href={`/markets/${market.slug}`}
      role="listitem"
      aria-label={
        isMultiOutcome
          ? `${market.question} • ${displayOutcomes
              .filter((o) => o.pct !== null)
              .map((o) => `${o.name} ${o.pct}%`)
              .join(", ")}`
          : `${market.question} • YES ${prob}%, NO ${100 - prob}%`
      }
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
          {/*
            One line per outcome on a multi-outcome market, each in its own
            colour - same shape as the market page. A single line cannot
            represent three mutually exclusive prices, and tracing only the first
            outcome hides the others entirely.

            Binary markets keep a single `value` line: that key is the YES
            price and the NO line is already implied by its complement.
          */}
          {isMultiOutcome ? (
            /* Same palette and same cap as the market page, so an outcome keeps
             * one colour across the card and the chart it links to. The old
             * local CHART_COLORS duplicated the market page's list, and drew up
             * to five lines from five lightnesses of one green. */
            plottedOutcomeColors(outcomes.map((o) => o.name)).map(
              ({ name, color }, i) => (
                <LiveLine
                  key={name}
                  dataKey={name}
                  stroke={color}
                  fill={i === 0}
                />
              )
            )
          ) : (
            <LiveLine dataKey="value" stroke="var(--primary)" fill />
          )}
        </LiveLineChart>
      </div>

      {/*
        Outcome prices + volume.

        Binary markets show the familiar YES/NO split. With 3+ outcomes there is
        no NO: "Yes 40% / No 60%" on a three-way market is simply wrong, so the
        outcomes are listed by name instead.
      */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-4">
          {isMultiOutcome ? (
            <div className="min-w-0 space-y-0.5">
              {displayOutcomes.slice(0, 3).map((outcome) => (
                <div key={outcome.name} className="flex items-baseline gap-1.5">
                  <span className="max-w-[6rem] truncate text-[10px] tracking-wider text-muted-foreground uppercase">
                    {outcome.name}
                  </span>
                  <span className="text-xs font-bold tabular-nums text-foreground">
                    {/* "—" not 0% for an outcome the book cannot price. */}
                    {outcome.pct === null ? "—" : `${outcome.pct}%`}
                  </span>
                </div>
              ))}
              {displayOutcomes.length > 3 && (
                <div className="text-[10px] text-muted-foreground">
                  +{displayOutcomes.length - 3} more
                </div>
              )}
            </div>
          ) : (
            <>
              <div>
                <div className="mb-0.5 text-[10px] tracking-wider text-muted-foreground uppercase">
                  Yes
                </div>
                <div className="text-sm font-bold text-green-700 tabular-nums">
                  {prob}%
                </div>
              </div>
              <div>
                <div className="mb-0.5 text-[10px] tracking-wider text-muted-foreground uppercase">
                  No
                </div>
                <div className="text-sm font-bold text-red-700 tabular-nums">
                  {100 - prob}%
                </div>
              </div>
            </>
          )}
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

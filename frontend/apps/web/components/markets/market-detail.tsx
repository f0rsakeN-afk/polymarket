"use client"

import { memo, useCallback, useMemo, useState } from "react"
import dynamic from "next/dynamic"
import { useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@workspace/ui/components/tabs"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@workspace/ui/components/select"
import { Button } from "@workspace/ui/components/button"
import { useMarket, useMarketActivity, useFAQs, useRelatedMarkets, usePriceHistory, useResolveMarket, useOrderBook } from "@/hooks/api/use-markets"
import { useSimpleMarketTrades } from "@/hooks/api/use-trades"
import { useCurrentUser } from "@/hooks/use-auth"
import { useMarketSocket } from "@/hooks/use-market-socket"
import { claimWinnings } from "@/lib/api/markets"
import { TradeFeed } from "@/components/trades/trade-feed"
import { TradeForm } from "./trade-form"
import { OrderBook } from "./order-book"
import { queryKeys } from "@/lib/api/queryKeys"
import type { OrderBook as OrderBookData } from "@/lib/api/markets"
import { CommentList, CommentForm } from "./comment-list"
import { LiveTradeTicker } from "./live-trade-ticker"
import { SkeletonMarketDetail } from "@/components/shared/skeletons"
import type { LiveLinePoint } from "@workspace/ui/components/charts/live-line-chart"
import type { PlaceOrderInput } from "@/lib/schemas/trading"
import type { Trade } from "@/hooks/api/types/market"
import { cn } from "@workspace/ui/lib/utils"
import {
  buildLivePricePoint,
  buildOutcomePrices,
  patchMarketPrices,
  type MarketPriceCache,
} from "@/lib/live-price"
import { apiErrorMessage } from "@/lib/api/client"
import { outcomeColor, plottedOutcomeColors } from "@/lib/outcome-colors"

// visx/d3 chart code splits into its own chunk and never SSR-renders •
// the detail page paints text/orderbook first, charts hydrate after.
function ChartFallback() {
  return <div className="h-[220px] animate-pulse rounded-md bg-muted/60" aria-hidden="true" />
}

const LiveLineChart = dynamic(
  () => import("@workspace/ui/components/charts/live-line-chart").then((m) => ({ default: m.LiveLineChart })),
  { ssr: false, loading: ChartFallback }
)
const LiveXAxis = dynamic(
  () => import("@workspace/ui/components/charts/live-x-axis").then((m) => ({ default: m.LiveXAxis })),
  { ssr: false }
)
const LiveYAxis = dynamic(
  () => import("@workspace/ui/components/charts/live-y-axis").then((m) => ({ default: m.LiveYAxis })),
  { ssr: false }
)
const LiveLine = dynamic(
  () => import("@workspace/ui/components/charts/live-line").then((m) => ({ default: m.LiveLine })),
  { ssr: false }
)
// Below-fold dialogs hydrate on demand instead of riding first paint.
const AlertDialog = dynamic(
  () => import("@/components/alerts/alert-dialog").then((m) => ({ default: m.AlertDialog })),
  { ssr: false }
)
const AddLiquidityForm = dynamic(
  () => import("@/components/liquidity/add-liquidity-form").then((m) => ({ default: m.AddLiquidityForm })),
  { ssr: false }
)

interface MarketDetailProps {
  slug: string
  onTrade?: (order: PlaceOrderInput) => Promise<void>
}

function MarketDetail({ slug, onTrade }: MarketDetailProps) {
  const queryClient = useQueryClient()
  const { data: market, isLoading: marketLoading } = useMarket(slug)
  const { data: activity } = useMarketActivity(slug)
  const { data: tradesData, isLoading: tradesLoading } = useSimpleMarketTrades(slug, { page_size: 200 })
  const { data: faqs } = useFAQs(slug)
  const { data: relatedMarkets } = useRelatedMarkets(slug)
  const { data: priceHistoryData } = usePriceHistory(slug)

  // useOrderBook already uses queryKeys.orderBook(slug) = ["orderbook", slug]
  // which is the same key the WS 'orderbook:update' message writes to • no extra fetch on WS events
  const { data: orderbookData } = useOrderBook(slug)
  // Derive first outcome's bids/asks for the header display (same select as before)
  const headerOutcome = useMemo(() => {
    if (!orderbookData?.data?.outcomes) return null
    return Object.values(orderbookData.data.outcomes)[0] ?? null
  }, [orderbookData])

  /**
   * Per-outcome price, from the API's `outcomes[].price` when present.
   *
   * buildOutcomePrices holds the ordering and the reasoning: the API price is
   * authoritative and the orderbook midpoint is only a fallback, because a
   * resting book is often empty on a thin market and must not blank out a price
   * the backend already knows. Deriving the price purely from the orderbook was
   * the original defect - with no orders resting, every outcome fell back to
   * the same even split, which is why the page showed "Yes 75 / No 25" for an
   * eight-way market.
   */
  const outcomePrices = useMemo(
    () =>
      buildOutcomePrices(
        market?.outcomes,
        orderbookData?.data?.outcomes as never
      ),
    [orderbookData, market?.outcomes]
  )

  /** Orderbook keys are lower-cased outcome names; fall back to an even split. */
  const priceFor = useCallback(
    (outcomeName: string, fallback: number) => outcomePrices[outcomeName.toLowerCase()] ?? fallback,
    [outcomePrices]
  )

  // outcomePrices is already keyed by lower-cased outcome name (the orderbook's
  // own key shape), which is exactly what trade-form selects by, so it passes
  // straight through.
  // WS-only points • chart renders history + seeds + these, capped at 200
  const [wsPoints, setWsPoints] = useState<LiveLinePoint[]>([])
  const [realtimeTrades, setRealtimeTrades] = useState<Trade[]>([])

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; yes_price?: number; no_price?: number; outcome_prices?: Record<string, number>; winning_outcome_name?: string; outcome?: string; side?: string; price?: number; amount?: number; username?: string }
    if (msg.type === "trade:new" && msg.outcome && msg.side && msg.price && msg.amount && msg.username) {
      setRealtimeTrades((prev) => {
        const next = [{ id: `ws-${Date.now()}`, market_id: "", market_slug: slug, market_question: "", outcome: msg.outcome!, side: msg.side! as "buy" | "sell", price: String(msg.price!), amount: String(msg.amount!), executed_at: new Date().toISOString(), username: msg.username! }, ...prev]
        return next.slice(0, 200)
      })
      return
    }
    if (msg.type === "market:price_update") {
      const now = Math.floor(Date.now() / 1000)

      // Build the point OUTSIDE the state updater. React may invoke an updater
      // more than once (StrictMode double-invokes), so side effects inside it
      // are not safe. Both helpers are pure and unit-tested in lib/live-price.
      const point = buildLivePricePoint(msg, now)

      // A partial frame yields null and is dropped: a point with no `value`
      // renders as 0 and drags the live tip to the floor.
      if (point) {
        setWsPoints((prev) => [...prev, point as LiveLinePoint].slice(-200))
      }

      // Push the new price into the cached market.
      //
      // Without this the chart moved but `market.yes_price` did not, so the big
      // YES/NO numbers and - worse - `currentYesPrice`/`currentNoPrice`, which
      // price the order form, kept quoting the last HTTP fetch. `useMarket` has
      // staleTime but NO refetchInterval and nothing else invalidates it, so the
      // form could sit on a stale price indefinitely while the chart disagreed.
      //
      // setQueryData (not invalidateQueries) keeps it instantaneous, with no
      // network round-trip.
      queryClient.setQueryData(
        queryKeys.market(slug),
        (prev) =>
          patchMarketPrices(
            prev as MarketPriceCache | undefined,
            msg
          ) as typeof prev
      )
    }
    if (msg.type === "market:resolved") {
      sileo.info({
        title: "Market Resolved!",
        description: `Winning outcome: ${msg.winning_outcome_name ?? "Unknown"}`,
      })
      queryClient.invalidateQueries({ queryKey: queryKeys.market(slug) })
      queryClient.invalidateQueries({ queryKey: queryKeys.markets() })
      queryClient.invalidateQueries({ queryKey: queryKeys.positions() })
    }
    // publish_notification wraps with type:"notification", so check that first then inspect inner fields
    if (msg.type === "notification" && (msg as { alert_id?: string }).alert_id) {
      const n = msg as { outcome?: string; condition?: string; trigger_price?: number }
      sileo.success({
        title: "Price Alert!",
        description: `${n.outcome?.toUpperCase()} ${n.condition} $${n.trigger_price?.toFixed(2)}`,
      })
    }
    if (msg.type === "orderbook:update" && (msg as { outcomes?: unknown }).outcomes) {
      // WS publishes the raw `build_orderbook` dict { outcome: { bids, asks } };
      // the HTTP response wraps it as { success, data }. Cache the wrapped shape
      // so this write and `getOrderBook` produce the identical value.
      const outcomes = (msg as { outcomes: OrderBookData }).outcomes
      queryClient.setQueryData(queryKeys.orderBook(slug), { success: true, data: { outcomes } })
    }
    if (msg.type === "comment:new" || msg.type === "comment:updated") {
      queryClient.invalidateQueries({ queryKey: ["comments", slug] })
    }
    if (msg.type === "comment:deleted") {
      queryClient.invalidateQueries({ queryKey: ["comments", slug] })
    }
  }, [slug, queryClient])

  const { status: wsStatus } = useMarketSocket({
    marketId: market?.id ?? "",
    onMessage: handleWSMessage,
    enabled: !!market?.id,
  })

  const { yesOutcome, noOutcome, outcomeList } = useMemo(() => {
    const outcomes = market?.outcomes ?? []
    return {
      // Matched by name, never by position. The previous
      // `yes ?? outcomes[0]` / `no ?? outcomes[1]` fallbacks made this pair
      // non-null for EVERY market with two or more outcomes, so `isBinary`
      // below was always true - and an eight-way market like
      // "euro-2024-winner" rendered as "Yes 75 / No 25" taken from the binary
      // pool's yes_price/no_price, which for a market with no Yes or No outcome
      // are meaningless seed values, not anybody's price.
      yesOutcome: outcomes.find((o) => o.name.toLowerCase() === "yes"),
      noOutcome: outcomes.find((o) => o.name.toLowerCase() === "no"),
      outcomeList: outcomes,
    }
  }, [market])

  // Binary only when the outcomes really are the YES/NO pair.
  const isBinary = !!(yesOutcome && noOutcome)

  const outcomeNames = useMemo(() => outcomeList.map((o) => o.name), [outcomeList])

  // Stable seed clock • captured once per market so re-renders don't shift the chart
  const [seedTime] = useState(() => Math.floor(Date.now() / 1000))

  // Two seed points from current market prices so the chart renders immediately
  const seedPoints = useMemo(() => {
    if (!market) return [] as LiveLinePoint[]

    const now = seedTime
    const seedPoint: Record<string, number | string> = { time: now - 60 }
    const seedPoint2: Record<string, number | string> = { time: now }

    if (isBinary) {
      const yesPrice = Number(market.yes_price ?? 0.5)
      const noPrice = Number(market.no_price ?? 0.5)
      seedPoint["value"] = yesPrice
      seedPoint["Yes"] = yesPrice
      seedPoint["No"] = noPrice
      seedPoint2["value"] = yesPrice
      seedPoint2["Yes"] = yesPrice
      seedPoint2["No"] = noPrice
    } else {
      const uniform = outcomeList.length > 0 ? 1 / outcomeList.length : 0.5
      const firstPrice = priceFor(outcomeList[0]?.name ?? "", uniform)
      seedPoint["value"] = isNaN(firstPrice) ? uniform : firstPrice
      seedPoint2["value"] = seedPoint["value"]
      for (const o of outcomeList) {
        const p = priceFor(o.name, uniform)
        seedPoint[o.name] = isNaN(p) ? uniform : p
        seedPoint2[o.name] = isNaN(p) ? uniform : p
      }
    }
    return [seedPoint, seedPoint2] as LiveLinePoint[]
  }, [market, outcomeList, isBinary, seedTime, priceFor])

  // Historical points from fetched price history • shown behind seeds/live data
  const historicalPoints = useMemo(() => {
    if (!priceHistoryData || priceHistoryData.length === 0) return [] as LiveLinePoint[]

    // Skip samples with no usable price. Defaulting to 0 here (as `?? 0` did)
    // put real market history on the floor, which is exactly the "chart dives
    // to zero" symptom; a missing price is missing, not zero.
    const points: LiveLinePoint[] = []
    for (const p of priceHistoryData) {
      const outcomes = p.outcomes ?? []
      const value = Number(outcomes[0]?.price)
      if (!Number.isFinite(value)) continue

      const point: Record<string, number | string> = {
        time: new Date(p.timestamp).getTime() / 1000,
        // value drives the first LiveLine (YES for binary)
        value,
      }
      for (const o of outcomes) {
        const price = Number((o as unknown as { price?: string }).price)
        if (Number.isFinite(price)) point[o.name] = price
      }
      points.push(point as LiveLinePoint)
    }
    return points
  }, [priceHistoryData])

  const priceHistory = useMemo(
    () => [...historicalPoints, ...seedPoints, ...wsPoints].slice(-200),
    [historicalPoints, seedPoints, wsPoints]
  )

  const { data: currentUser } = useCurrentUser()
  const { mutateAsync: resolveMarket, isPending: isResolving } = useResolveMarket()
  const [selectedOutcomeId, setSelectedOutcomeId] = useState<string>("")

  const handleResolve = useCallback(async () => {
    if (!selectedOutcomeId) return
    try {
      const res = await resolveMarket({ slug, winning_outcome_id: selectedOutcomeId })
      sileo.success({ title: res.message ?? "Market resolved!" })
    } catch (e) {
      sileo.error({ title: "Resolve failed", description: apiErrorMessage(e, "Unknown error") })
    }
  }, [slug, selectedOutcomeId, resolveMarket])

  const handleTrade = useCallback(
    async (order: PlaceOrderInput) => { await onTrade?.(order) },
    [onTrade]
  )

  const handleOutcomeSelect = useCallback(
    (val: string | null) => setSelectedOutcomeId(val ?? ""),
    []
  )

  const outcomes = useMemo(
    () => market?.outcomes ?? [],
    [market]
  )

  const stats = useMemo(() => activity ? [
    { label: "Volume", value: `$${(Number(activity.market_stats.total_volume) / 1e6).toFixed(1)}M` },
    { label: "Liquidity", value: `$${(Number(activity.market_stats.total_liquidity) / 1e6).toFixed(1)}M` },
    { label: "Spread", value: `${(Number(activity.market_stats.spread) * 100).toFixed(1)}%` },
    { label: "Trades", value: activity.market_stats.num_trades.toLocaleString() },
  ] : null, [activity])

  const relatedSlice = useMemo(
    () => relatedMarkets?.slice(0, 5) ?? [],
    [relatedMarkets]
  )

  const combinedTrades = useMemo(
    () => [...realtimeTrades, ...(tradesData?.trades ?? [])].slice(0, 200) as Trade[],
    [realtimeTrades, tradesData?.trades]
  )

  const holderOutcomes = useMemo(
    () => activity ? Object.entries(activity.top_holders_by_outcome) : [],
    [activity]
  )

  if (marketLoading && !market) {
    return <SkeletonMarketDetail />
  }

  if (!market) {
    return <div className="py-12 text-center text-muted-foreground">Market not found</div>
  }

  return (
    <div className="grid gap-4 sm:gap-6 lg:grid-cols-4">
      {/* Main content */}
      <div className="min-w-0 space-y-4 sm:space-y-6 lg:col-span-3">
        {/* Resolution banner */}
        {market.status === "resolved" && (
          <div role="status" className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 p-4">
            <div className="text-sm font-semibold text-yellow-700">Resolved</div>
            <div className="text-xs text-muted-foreground mt-1">
              Winning outcome: <span className="font-medium text-foreground">{market.winning_outcome_name ?? "Unknown"}</span>
            </div>
            <ClaimWinnings slug={slug} />
          </div>
        )}

        {/* Admin resolve UI */}
        {market.status !== "resolved" && currentUser?.is_admin && (
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-4">
            <div className="text-xs font-semibold text-blue-700 mb-3 uppercase tracking-wider">Admin: Resolve Market</div>
            <div className="flex items-center gap-2">
              <label htmlFor="resolve-outcome" className="sr-only">Select winning outcome</label>
              <Select value={selectedOutcomeId} onValueChange={handleOutcomeSelect}>
                <SelectTrigger id="resolve-outcome" aria-label="Select winning outcome" className="flex-1 h-9">
                  <SelectValue placeholder="Select winning outcome..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                  {market.outcomes.map((o) => (
                    <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>
                  ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Button
                onClick={handleResolve}
                disabled={!selectedOutcomeId || isResolving}
                variant="default"
                size="sm"
              >
                {isResolving ? "Resolving..." : "Resolve"}
              </Button>
            </div>
          </div>
        )}

        {/* Market header */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            {market.category && (
              <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-wider text-primary">
                {market.category}
              </span>
            )}
            <span className="text-xs font-semibold tracking-widest text-muted-foreground">PREDICTX</span>
          </div>
          {/*
            Fluid type rather than one fixed size. A prediction-market question
            can be a short "Will X?" or two full sentences, and on a 360px phone
            a 24px heading for the latter overflows into two very short ragged
            lines. Scales with the viewport and stops before it dominates.
          */}
          <h1 className="text-lg font-bold leading-tight tracking-tight sm:text-xl lg:text-2xl">
            {market.question}
          </h1>
          {market.description && (
            <p className="text-sm leading-relaxed text-muted-foreground">{market.description}</p>
          )}
        </div>

        {/* Price chart */}
        <div className="relative min-w-0 overflow-hidden rounded-xl border border-border bg-card p-4 sm:p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              {isBinary
                ? (
                  <>
                    <div className="flex items-center gap-2">
                      <div className="text-xs uppercase tracking-wider text-muted-foreground">Yes</div>
                      <div className="text-lg font-bold text-green-700 tabular-nums">{Math.round(Number(market.yes_price ?? 0.5) * 100)}¢</div>
                      <div className="text-xs text-muted-foreground">
                        {headerOutcome?.bids?.[0] ? `${Number(headerOutcome.bids[0].size).toFixed(0)} shares` : ""}
                      </div>
                    </div>
                    <div className="h-6 w-px bg-border" />
                    <div className="flex items-center gap-2">
                      <div className="text-xs uppercase tracking-wider text-muted-foreground">No</div>
                      <div className="text-lg font-bold text-red-700 tabular-nums">{Math.round(Number(market.no_price ?? 0.5) * 100)}¢</div>
                      <div className="text-xs text-muted-foreground">
                        {headerOutcome?.asks?.[0] ? `${Number(headerOutcome.asks[0].size).toFixed(0)} shares` : ""}
                      </div>
                    </div>
                  </>
                )
                : outcomeList.slice(0, 4).map((outcome, i) => (
                    <div key={outcome.id} className="flex items-center gap-2">
                      <div className="text-xs uppercase tracking-wider text-muted-foreground">{outcome.name}</div>
                      <div className="text-lg font-bold tabular-nums" style={{ color: outcomeColor(i) }}>
                        {Math.round(priceFor(outcome.name, 0) * 100)}¢
                      </div>
                    </div>
                  ))
              }
            </div>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5">
                <span
                  role="status"
                  aria-label={`WebSocket ${wsStatus}`}
                  className={cn(
                    "size-2 rounded-full",
                    wsStatus === "connected" ? "bg-green-600 dark:bg-green-400" : wsStatus === "connecting" ? "bg-yellow-600 animate-pulse dark:bg-yellow-400" : "bg-muted-foreground/40"
                  )}
                />
                <span className="text-xs font-medium text-muted-foreground">
                  {wsStatus === "connected" ? "Live" : wsStatus === "connecting" ? "Syncing" : "Offline"}
                </span>
              </span>
              <span className="text-xs text-muted-foreground tabular-nums">Vol ${market.total_volume.toLocaleString()}</span>
            </div>
          </div>
          {/* Chart height scales a little: 220px was generous on a phone and cramped on
            a desktop. The right margin holds the Y-axis labels, which are
            widened at sm so they don't clip. */}
          <div className="h-[200px] sm:h-[240px]">
            {priceHistory.length === 0 ? (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Loading chart...</div>
            ) : (
            <LiveLineChart
              data={priceHistory}
              // value = first outcome's latest price (drives smooth interpolation).
              // Fall back to the market price, not 0: a 0 here hands the chart a
              // real zero and the line dives to the floor on the first frame.
              value={(priceHistory.at(-1)?.["value"] as number | undefined) ?? Number(market.yes_price ?? 0.5)}
              // valueNo = second outcome's latest price (drives secondary line for binary)
              valueNo={
                isBinary
                  ? ((priceHistory.at(-1)?.["No"] as number | undefined) ?? Number(market.no_price ?? 0.5))
                  : undefined
              }
              window={60}
              numXTicks={5}
              // Matches the container's h-[200px] sm:h-[240px]; a mismatch here
              // silently overrides the CSS height because ParentSize drives the
              // SVG from this prop.
              height={200}
              margin={{ top: 16, right: 40, bottom: 32, left: 40 }}
              multiOutcome={!isBinary}
            >
              <LiveXAxis />
              <LiveYAxis />
              {isBinary ? (
                // Binary: YES = green primary line, NO = red secondary line
                <>
                  <LiveLine key="Yes" dataKey="Yes" stroke="var(--chart-1)" fill />
                  <LiveLine key="No" dataKey="No" stroke="var(--destructive)" fill />
                </>
              ) : (
                // Multi-outcome: one line per outcome, capped for legibility.
                // plottedOutcomeColors pairs each name with its own colour so the
                // two cannot drift apart.
                plottedOutcomeColors(outcomeNames).map(({ name, color }) => (
                  <LiveLine key={name} dataKey={name} stroke={color} fill />
                ))
              )}
            </LiveLineChart>
            )}
          </div>
          {/* Live Trade Ticker • below chart so it never covers axes */}
          <div className="mt-3">
            <LiveTradeTicker marketId={market.id} />
          </div>
        </div>

        {/* Stats. Two-up on phones rather than one-per-row: four stacked cards
            pushed the chart and tabs a full screen down. Values get
            break-words because a formatted volume can be long. */}
        {stats && (
          <section
            aria-label="Market statistics"
            className="grid grid-cols-2 gap-2 sm:gap-3 sm:grid-cols-4"
            role="list"
          >
            {stats.map(({ label, value }) => (
              <div
                key={label}
                role="listitem"
                className="rounded-xl border border-border bg-card p-2.5 text-center sm:p-3"
              >
                <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                  {label}
                </div>
                <div className="break-words text-sm font-semibold tabular-nums">{value}</div>
              </div>
            ))}
          </section>
        )}

        {/* Tabs: Orderbook / Trades / Positions / Discussion / FAQs */}
        <Tabs defaultValue="orderbook" className="overflow-hidden rounded-xl border border-border bg-card">
          <TabsList role="tablist" aria-label="Market details" className="h-auto w-full justify-start gap-1 overflow-x-auto rounded-none bg-muted/50 p-1 nice-scroll">
            <TabsTrigger value="orderbook" role="tab" className="rounded-md px-4 py-2.5 text-xs font-semibold data-active:bg-primary/10 data-active:text-foreground">Orderbook</TabsTrigger>
            <TabsTrigger value="trades" role="tab" className="rounded-md px-4 py-2.5 text-xs font-semibold data-active:bg-primary/10 data-active:text-foreground">Trades</TabsTrigger>
            <TabsTrigger value="positions" role="tab" className="rounded-md px-4 py-2.5 text-xs font-semibold data-active:bg-primary/10 data-active:text-foreground">Positions</TabsTrigger>
            <TabsTrigger value="discussion" role="tab" className="rounded-md px-4 py-2.5 text-xs font-semibold data-active:bg-primary/10 data-active:text-foreground">Discussion</TabsTrigger>
            {faqs && faqs.length > 0 && (
              <TabsTrigger value="faqs" role="tab" className="rounded-md px-4 py-2.5 text-xs font-semibold data-active:bg-primary/10 data-active:text-foreground">FAQs</TabsTrigger>
            )}
          </TabsList>

          <div className="space-y-3 p-3 sm:p-4">
            {/*
              Panels scroll internally, but the height is viewport-relative on
              small screens: a fixed 400px inside a phone's shorter viewport
              left the page itself scrolling and the sticky header fighting it.
            */}
            <TabsContent value="orderbook" role="tabpanel" className="nice-scroll max-h-[60vh] overflow-y-auto lg:max-h-[400px]">
              <OrderBook slug={slug} />
            </TabsContent>
            <TabsContent value="trades" role="tabpanel" className="nice-scroll max-h-[60vh] overflow-y-auto lg:max-h-[400px]">
              <TradeFeed
                trades={combinedTrades}
                loading={tradesLoading}
              />
            </TabsContent>

            <TabsContent value="positions" role="tabpanel" className="nice-scroll max-h-[60vh] overflow-y-auto lg:max-h-[400px]">
              {holderOutcomes.length > 0 ? (
                <div className={holderOutcomes.length > 1 ? "grid gap-6 sm:grid-cols-2" : ""}>
                  {holderOutcomes.map(([outcomeName, holders]) => (
                    <div key={outcomeName}>
                      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        {outcomeName}
                      </h4>
                      <ul className="space-y-1.5">
                        {holders.slice(0, 10).map((holder, i) => (
                          <li key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-border/50 last:border-0">
                            <span className="text-muted-foreground font-medium">{holder.username}</span>
                            <span className="font-semibold">{Number(holder.shares_held).toFixed(0)} <span className="text-muted-foreground text-[10px]">shares</span></span>
                          </li>
                        ))}
                        {holders.length === 0 && (
                          <li className="text-xs text-muted-foreground py-2">No positions yet</li>
                        )}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-8 text-center text-xs text-muted-foreground">No positions yet</div>
              )}
            </TabsContent>

            <TabsContent value="discussion" role="tabpanel" className="nice-scroll max-h-[60vh] overflow-y-auto lg:max-h-[400px]">
              <CommentForm slug={slug} />
              <CommentList slug={slug} />
            </TabsContent>

            <TabsContent value="faqs" role="tabpanel" className="nice-scroll max-h-[60vh] overflow-y-auto lg:max-h-[400px]">
              {faqs && faqs.length > 0 ? (
                <div className="space-y-3">
                  {faqs.map((faq, i) => (
                    <article key={faq.id} className={i > 0 ? "pt-3 border-t border-border" : ""}>
                      <h4 className="text-xs font-semibold text-foreground mb-1">{faq.question}</h4>
                      <p className="text-xs text-muted-foreground leading-relaxed">{faq.answer}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="py-8 text-center text-xs text-muted-foreground">No FAQs for this market</div>
              )}
            </TabsContent>
          </div>
        </Tabs>
      </div>

      {/*
          Right sidebar. Stacks below the main column until `lg`. `min-w-0`
          matters: grid items default to min-width:auto, so without it the
          order book's fixed-width rows force this column wider than its track
          and push a horizontal scrollbar onto the page.
        */}
      <aside aria-label="Trading panel" className="min-w-0 space-y-4">
        {/* Trade card */}
        <section
          aria-labelledby="trade-heading"
          className="rounded-xl border border-border bg-card p-4 sm:p-5"
        >
          <h2 id="trade-heading" className="mb-4 text-sm font-semibold text-foreground">Place Trade</h2>
          <TradeForm
            marketId={market.id}
            currentYesPrice={Number(market.yes_price)}
            currentNoPrice={Number(market.no_price)}
            // Live book-derived price per outcome. Multi-outcome markets have no
            // AMM price at all, so without this the form quoted 0 for the third
            // and later outcomes.
            outcomePrices={outcomePrices}
            outcomes={outcomes}
            marketStatus={market.status}
            onSubmit={handleTrade}
          />
          <AlertDialog
            marketId={market.id}
            currentYesPrice={Number(market.yes_price)}
            currentNoPrice={Number(market.no_price)}
          />
        </section>

        {/* Liquidity */}
        <section aria-labelledby="liquidity-heading" className="rounded-xl border border-border bg-card p-5">
          <h2 id="liquidity-heading" className="mb-3 text-sm font-semibold text-foreground">Liquidity</h2>
          <AddLiquidityForm marketId={market.id} marketStatus={market.status} />
        </section>

        {/* Market Info */}
        <section aria-labelledby="info-heading" className="rounded-xl border border-border bg-card p-5">
          <h2 id="info-heading" className="mb-3 text-sm font-semibold text-foreground">Market Info</h2>
          <dl className="space-y-2.5">
            <div className="flex items-center justify-between text-xs">
              <dt className="text-muted-foreground">Status</dt>
              {market.status === "resolved" ? (
                <dd className="font-semibold px-1.5 py-0.5 rounded text-[10px] bg-yellow-500/10 text-yellow-700">
                  RESOLVED
                </dd>
              ) : (
                <dd className={cn(
                  "font-semibold capitalize px-1.5 py-0.5 rounded text-[10px]",
                  market.status === "active" ? "bg-green-500/10 text-green-700" : "bg-muted text-muted-foreground"
                )}>{market.status}</dd>
              )}
            </div>
            {market.status === "resolved" && market.winning_outcome_name ? (
              <div className="flex items-center justify-between text-xs">
                <dt className="text-muted-foreground">Winner</dt>
                <dd className="font-medium text-green-700">{market.winning_outcome_name}</dd>
              </div>
            ) : (
              <div className="flex items-center justify-between text-xs">
                <dt className="text-muted-foreground">Closes</dt>
                <dd className="font-medium">{new Date(market.closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</dd>
              </div>
            )}
            <div className="flex items-center justify-between text-xs">
              <dt className="text-muted-foreground">Liquidity</dt>
              <dd className="font-medium">${market.total_liquidity.toLocaleString()}</dd>
            </div>
            {market.status !== "resolved" && (
              <div className="flex items-center justify-between text-xs">
                <dt className="text-muted-foreground">Spread</dt>
                <dd className="font-medium">{((Number(market.spread)) * 100).toFixed(1)}%</dd>
              </div>
            )}
            {!isBinary && (
              <div className="flex items-center justify-between text-xs">
                <dt className="text-muted-foreground">Type</dt>
                <dd className="font-medium">Multi-outcome</dd>
              </div>
            )}
          </dl>
        </section>

        {/* Related Markets */}
        {relatedSlice.length > 0 && (
          <section aria-labelledby="related-heading" className="rounded-xl border border-border bg-card p-5">
            <h2 id="related-heading" className="mb-3 text-sm font-semibold text-foreground">Related</h2>
            <div className="space-y-2">
              {relatedSlice.map((m) => (
                <a
                  key={m.slug}
                  href={`/markets/${m.slug}`}
                  className="block rounded-lg border border-border p-3 hover:bg-muted/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="text-xs font-medium leading-snug line-clamp-2 mb-1.5">{m.question}</div>
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span className="text-green-700 font-semibold">${Number(m.yes_price).toFixed(2)}</span>
                    <span aria-hidden="true">·</span>
                    <span>${(Number(m.total_volume) / 1000).toFixed(0)}K vol</span>
                  </div>
                </a>
              ))}
            </div>
          </section>
        )}
      </aside>
    </div>
  )
}

const ClaimWinnings = memo(function ClaimWinnings({ slug }: { slug: string }) {
  const { data: currentUser } = useCurrentUser()
  const qc = useQueryClient()
  const [claiming, setClaiming] = useState(false)
  const [claimed, setClaimed] = useState(false)

  const handleClaim = useCallback(async () => {
    setClaiming(true)
    try {
      const res = await claimWinnings(slug)
      setClaimed(true)
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.transactions() })
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
      sileo.success({ title: res.message ?? "Winnings claimed!" })
    } catch (e) {
      sileo.error({ title: "Claim failed", description: apiErrorMessage(e, "Unknown error") })
    } finally {
      setClaiming(false)
    }
  }, [slug, qc])

  if (!currentUser) return null

  return (
    <div className="mt-3 pt-3 border-t border-yellow-500/20">
      <button
        onClick={handleClaim}
        disabled={claiming || claimed}
        aria-label={claimed ? "Winnings already claimed" : claiming ? "Claiming winnings" : "Claim your winnings"}
        className="w-full rounded-md bg-yellow-500 px-3 py-2 text-xs font-semibold text-yellow-950 hover:bg-yellow-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {claimed ? "Claimed!" : claiming ? "Claiming..." : "Claim Winnings"}
      </button>
    </div>
  )
})

export { MarketDetail }

"use client"

import { memo, useCallback, useEffect, useMemo, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { LiveLineChart } from "@workspace/ui/components/charts/live-line-chart"
import { LiveXAxis } from "@workspace/ui/components/charts/live-x-axis"
import { LiveYAxis } from "@workspace/ui/components/charts/live-y-axis"
import { LiveLine } from "@workspace/ui/components/charts/live-line"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@workspace/ui/components/tabs"
import { useMarket, useMarketActivity, useMarketTrades, useFAQs, useRelatedMarkets, usePriceHistory, useResolveMarket } from "@/hooks/api/use-markets"
import { useCurrentUser } from "@/hooks/use-auth"
import { useMarketSocket } from "@/hooks/use-market-socket"
import { api } from "@/lib/api/client"
import { TradeFeed } from "@/components/trades/trade-feed"
import { TradeForm } from "./trade-form"
import { AlertDialog } from "@/components/alerts/alert-dialog"
import { OrderBook } from "./order-book"
import { CommentList, CommentForm } from "./comment-list"
import { AddLiquidityForm } from "@/components/liquidity/add-liquidity-form"
import { LiveTradeTicker } from "./live-trade-ticker"
import { SkeletonMarketDetail } from "@/components/shared/skeletons"
import type { LiveLinePoint } from "@workspace/ui/components/charts/live-line-chart"
import type { PlaceOrderInput } from "@/lib/schemas/trading"
import type { MarketDetailResponse, PriceHistoryPoint, Trade } from "@/hooks/api/types/market"
import { cn } from "@workspace/ui/lib/utils"

interface MarketDetailProps {
  slug: string
  onTrade?: (order: PlaceOrderInput) => Promise<void>
}

function MarketDetail({ slug, onTrade }: MarketDetailProps) {
  const queryClient = useQueryClient()
  const { data: market, isLoading: marketLoading } = useMarket(slug)
  const { data: activity, isLoading: activityLoading } = useMarketActivity(slug)
  const { data: tradesData, isLoading: tradesLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useMarketTrades(slug)
  const { data: faqs } = useFAQs(slug)
  const { data: relatedMarkets } = useRelatedMarkets(slug)
  const { data: priceHistoryData } = usePriceHistory(slug)

  const { data: orderbookData } = useQuery({
    queryKey: ["orderbook-header", slug] as const,
    queryFn: () => api.get<{ success: boolean; data: { bids: { price: number; depth: number }[]; asks: { price: number; depth: number }[] } }>(`/api/v1/markets/${slug}/orderbook`),
    enabled: !!slug,
    refetchInterval: 5000,
    select: (res) => res.data,
  })

  const [priceHistory, setPriceHistory] = useState<LiveLinePoint[]>([])
  const [outcomeNames, setOutcomeNames] = useState<string[]>([])
  const [realtimeTrades, setRealtimeTrades] = useState<Trade[]>([])

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; yes_price?: number; no_price?: number; outcome_prices?: Record<string, number>; winning_outcome_name?: string; outcome?: string; side?: string; price?: number; amount?: number; username?: string }
    if (msg.type === "trade:new" && msg.outcome && msg.side && msg.price && msg.amount && msg.username) {
      setRealtimeTrades((prev) => {
        const next = [{ id: `ws-${Date.now()}`, market_slug: slug, market_question: "", outcome: msg.outcome!, side: msg.side! as "buy" | "sell", price: msg.price!, amount: msg.amount!, executed_at: new Date().toISOString(), username: msg.username! }, ...prev]
        return next.slice(0, 200)
      })
      return
    }
    if (msg.type === "market:price_update") {
      const now = Math.floor(Date.now() / 1000)
      setPriceHistory((prev) => {
        const point: Record<string, number | string> = { time: now }
        if (msg.outcome_prices) {
          for (const [name, price] of Object.entries(msg.outcome_prices)) {
            point[name] = price
          }
        } else if (msg.yes_price != null && msg.no_price != null) {
          point["Yes"] = msg.yes_price
          point["No"] = msg.no_price
        }
        const next = [...prev, point as LiveLinePoint]
        return next.slice(-200)
      })
    }
    if (msg.type === "market:resolved") {
      sileo.info({
        title: "Market Resolved!",
        description: `Winning outcome: ${msg.winning_outcome_name ?? "Unknown"}`,
      })
      queryClient.invalidateQueries({ queryKey: ["market", slug] })
      queryClient.invalidateQueries({ queryKey: ["markets"] })
      queryClient.invalidateQueries({ queryKey: ["positions"] })
    }
    if (msg.type === "alert:triggered") {
      sileo.success({
        title: "Price Alert!",
        description: `${(msg as { outcome?: string }).outcome?.toUpperCase()} ${(msg as { condition?: string }).condition} $${(msg as { trigger_price?: number }).trigger_price?.toFixed(2)}`,
      })
    }
    if (msg.type === "orderbook:update") {
      queryClient.invalidateQueries({ queryKey: ["orderbook-header", slug] })
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

  useEffect(() => {
    if (priceHistoryData && priceHistoryData.length > 0) {
      const first = priceHistoryData[0]!
      const names = first.outcomes.map((o) => o.name)
      setOutcomeNames(names)
      setPriceHistory(
        priceHistoryData.map((p: PriceHistoryPoint) => {
          const point: Record<string, number | string> = { time: new Date(p.timestamp).getTime() / 1000, value: 0 }
          for (const o of p.outcomes) {
            point[o.name] = o.price
          }
          return point as LiveLinePoint
        })
      )
      return
    }
    if (!market) return
    const names = isMultiOutcome
      ? (market as MarketDetailResponse).outcomes.map((o) => o.name)
      : ["Yes", "No"]
    setOutcomeNames(names)
    const now = Math.floor(Date.now() / 1000)
    const seedPoint: Record<string, number | string> = { time: now - 60 }
    const seedPoint2: Record<string, number | string> = { time: now }
    if (isMultiOutcome) {
      const outcomes = (market as MarketDetailResponse).outcomes
      const uniform = 1 / outcomes.length
      for (const o of outcomes) {
        seedPoint[o.name] = uniform
        seedPoint2[o.name] = uniform
      }
    } else {
      seedPoint["Yes"] = market.yes_price
      seedPoint["No"] = market.no_price
      seedPoint2["Yes"] = market.yes_price
      seedPoint2["No"] = market.no_price
    }
    setPriceHistory([seedPoint, seedPoint2] as LiveLinePoint[])
  }, [market, priceHistoryData])

  const { data: currentUser } = useCurrentUser()
  const { mutateAsync: resolveMarket, isPending: isResolving } = useResolveMarket()
  const [selectedOutcomeId, setSelectedOutcomeId] = useState<string>("")

  const handleResolve = useCallback(async () => {
    if (!selectedOutcomeId) return
    try {
      await resolveMarket({ slug, winning_outcome_id: selectedOutcomeId })
      sileo.success({ title: "Market resolved!" })
    } catch (e) {
      sileo.error({ title: "Resolve failed", description: e instanceof Error ? e.message : "Unknown error" })
    }
  }, [slug, selectedOutcomeId, resolveMarket])

  const handleTrade = useCallback(
    async (order: PlaceOrderInput) => { await onTrade?.(order) },
    [onTrade]
  )

  const isMultiOutcome = useMemo(
    () => (market as MarketDetailResponse)?.outcomes?.length > 2,
    [market]
  )

  const outcomes = useMemo(
    () => (market as MarketDetailResponse)?.outcomes ?? [],
    [market]
  )

  const chartColors = useMemo(
    () => ["var(--chart-1)", "var(--chart-5)", "var(--chart-3)", "var(--chart-4)", "var(--chart-2)", "var(--chart-6)", "var(--chart-7)", "var(--chart-8)"],
    []
  )

  const stats = useMemo(() => activity ? [
    { label: "Volume", value: `$${(activity.market_stats.total_volume / 1e6).toFixed(1)}M` },
    { label: "Liquidity", value: `$${(activity.market_stats.total_liquidity / 1e6).toFixed(1)}M` },
    { label: "Spread", value: `${(activity.market_stats.spread * 100).toFixed(1)}%` },
    { label: "Trades", value: activity.market_stats.num_trades.toLocaleString() },
  ] : null, [activity])

  const relatedSlice = useMemo(
    () => relatedMarkets?.slice(0, 5) ?? [],
    [relatedMarkets]
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
    <div className="grid gap-6 lg:grid-cols-4">

      {/* Main content */}
      <div className="space-y-6 lg:col-span-3">
        {/* Resolution banner */}
        {market.status === "resolved" && (
          <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 p-4">
            <div className="text-sm font-semibold text-yellow-600">RESOLVED</div>
            <div className="text-xs text-muted-foreground mt-1">
              Winning outcome: <span className="font-medium text-foreground">{market.winning_outcome_name ?? "Unknown"}</span>
            </div>
            <ClaimWinnings slug={slug} />
          </div>
        )}

        {/* Admin resolve UI */}
        {market.status !== "resolved" && currentUser?.is_admin && (
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-4">
            <div className="text-xs font-semibold text-blue-500 mb-3 uppercase tracking-wider">Admin: Resolve Market</div>
            <div className="flex items-center gap-2">
              <select
                value={selectedOutcomeId}
                onChange={(e) => setSelectedOutcomeId(e.target.value)}
                className="flex-1 h-9 rounded-md border border-border bg-background px-3 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">Select winning outcome...</option>
                {(market as MarketDetailResponse).outcomes.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
              <button
                onClick={handleResolve}
                disabled={!selectedOutcomeId || isResolving}
                className="h-9 rounded-md bg-blue-500 px-4 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isResolving ? "Resolving..." : "Resolve"}
              </button>
            </div>
          </div>
        )}

        {/* Market header */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            {market.category && (
              <span className="rounded-full bg-primary/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-primary">
                {market.category}
              </span>
            )}
            <span className="text-[10px] font-bold tracking-widest text-muted-foreground">POLYMARKET</span>
          </div>
          <h1 className="text-2xl font-semibold leading-tight">{market.question}</h1>
          {market.description && (
            <p className="text-sm text-muted-foreground leading-relaxed">{market.description}</p>
          )}
        </div>

        {/* Price chart */}
        <div className="relative rounded-xl border border-border bg-card p-5 overflow-hidden">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex flex-wrap items-center gap-3">
              {isMultiOutcome
                ? (market as MarketDetailResponse).outcomes.map((outcome, i) => (
                    <div key={outcome.id} className="flex items-center gap-2">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">{outcome.name}</div>
                      {i < (market as MarketDetailResponse).outcomes.length - 1 && <div className="h-6 w-px bg-border" />}
                    </div>
                  ))
                : (
                  <>
                    <div className="flex items-center gap-2">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">YES</div>
                      <div className="text-lg font-bold text-green-500">${market.yes_price.toFixed(2)}</div>
                      <div className="text-xs text-muted-foreground">
                        {orderbookData?.bids?.[0] ? `${orderbookData.bids[0].depth.toFixed(0)} shares` : ""}
                      </div>
                    </div>
                    <div className="h-6 w-px bg-border" />
                    <div className="flex items-center gap-2">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">NO</div>
                      <div className="text-lg font-bold text-red-500">${market.no_price.toFixed(2)}</div>
                      <div className="text-xs text-muted-foreground">
                        {orderbookData?.asks?.[0] ? `${orderbookData.asks[0].depth.toFixed(0)} shares` : ""}
                      </div>
                    </div>
                  </>
                )
              }
            </div>
            <div className="flex items-center gap-2">
              <span
                role="status"
                aria-label={`WebSocket ${wsStatus}`}
                className={cn(
                  "size-2 rounded-full",
                  wsStatus === "connected" ? "bg-green-500" : wsStatus === "connecting" ? "bg-yellow-500 animate-pulse" : "bg-muted"
                )}
              />
              <span className="text-xs text-muted-foreground">Vol ${market.total_volume.toLocaleString()}</span>
            </div>
          </div>
          <div className="h-[220px]">
            <LiveLineChart
              data={priceHistory}
              value={priceHistory.at(-1)?.[outcomeNames[0] ?? "Yes"] as number ?? market.yes_price}
              valueNo={outcomeNames.length > 1 ? priceHistory.at(-1)?.[outcomeNames[1]!] as number ?? market.no_price : undefined}
              window={60}
              numXTicks={5}
              height={220}
              margin={{ top: 16, right: 36, bottom: 40, left: 48 }}
              multiOutcome={outcomeNames.length > 2}
            >
              <LiveXAxis />
              <LiveYAxis />
              {outcomeNames.map((name, i) => (
                <LiveLine key={name} dataKey={name} stroke={chartColors[i % chartColors.length]} fill />
              ))}
            </LiveLineChart>
          </div>
          {/* Live Trade Ticker - floats over the chart */}
          <div className="absolute bottom-3 left-3 right-3 z-10 pointer-events-none">
            <LiveTradeTicker marketId={market.id} />
          </div>
        </div>

        {/* Stats */}
        {stats && (
          <section aria-label="Market statistics" className="grid grid-cols-4 gap-3">
            {stats.map(({ label, value }) => (
              <div key={label} className="rounded-lg border border-border bg-card p-3 text-center">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</div>
                <div className="font-semibold text-sm">{value}</div>
              </div>
            ))}
          </section>
        )}

        {/* Tabs: Orderbook / Trades / Positions / Discussion / FAQs */}
        <Tabs defaultValue="orderbook" className="rounded-xl border border-border bg-card overflow-hidden">
          <TabsList role="tablist" aria-label="Market details" className="w-full justify-start rounded-none border-b border-border bg-muted/50 p-0 h-auto">
            <TabsTrigger value="orderbook" role="tab" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">Orderbook</TabsTrigger>
            <TabsTrigger value="trades" role="tab" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">Trades</TabsTrigger>
            <TabsTrigger value="positions" role="tab" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">Positions</TabsTrigger>
            <TabsTrigger value="discussion" role="tab" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">Discussion</TabsTrigger>
            {faqs && faqs.length > 0 && (
              <TabsTrigger value="faqs" role="tab" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">FAQs</TabsTrigger>
            )}
          </TabsList>

          <div className="p-4">
            <TabsContent value="orderbook" role="tabpanel" className="min-h-[200px]">
              <OrderBook slug={slug} />
            </TabsContent>
            <TabsContent value="trades" role="tabpanel" className="min-h-[200px]">
              <TradeFeed
                trades={[...realtimeTrades, ...(tradesData?.trades ?? [])].slice(0, 200)}
                loading={tradesLoading}
                hasMore={hasNextPage}
                fetchNextPage={fetchNextPage}
                isFetchingNextPage={isFetchingNextPage}
              />
            </TabsContent>

            <TabsContent value="positions" role="tabpanel" className="min-h-[200px]">
              {holderOutcomes.length > 0 ? (
                <div className="max-h-64 overflow-y-auto scrollbar-hide">
                  <div className={holderOutcomes.length > 1 ? "grid grid-cols-2 gap-6" : ""}>
                    {holderOutcomes.map(([outcomeName, holders]) => (
                      <div key={outcomeName}>
                        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          {outcomeName}
                        </h4>
                        <ul className="space-y-1.5">
                          {holders.slice(0, 10).map((holder, i) => (
                            <li key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-border/50 last:border-0">
                              <span className="text-muted-foreground font-medium">{holder.username}</span>
                              <span className="font-semibold">{holder.shares_held.toFixed(0)} <span className="text-muted-foreground text-[10px]">shares</span></span>
                            </li>
                          ))}
                          {holders.length === 0 && (
                            <li className="text-xs text-muted-foreground py-2">No positions yet</li>
                          )}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="py-8 text-center text-xs text-muted-foreground">No positions yet</div>
              )}
            </TabsContent>

            <TabsContent value="discussion" role="tabpanel" className="min-h-[200px]">
              <div className="mb-4">
                <CommentForm slug={slug} />
              </div>
              <CommentList slug={slug} />
            </TabsContent>

            <TabsContent value="faqs" role="tabpanel" className="min-h-[200px]">
              {faqs && faqs.length > 0 ? (
                <div className="max-h-64 overflow-y-auto scrollbar-hide space-y-3">
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

      {/* Right sidebar */}
      <aside className="space-y-4">
        {/* Trade card */}
        <section aria-labelledby="trade-heading" className="rounded-xl border border-border bg-card p-5">
          <h2 id="trade-heading" className="mb-4 text-sm font-semibold text-foreground">Place Trade</h2>
          <TradeForm
            marketId={market.id}
            currentYesPrice={market.yes_price}
            currentNoPrice={market.no_price}
            outcomes={outcomes}
            onSubmit={handleTrade}
          />
          <AlertDialog
            marketId={market.id}
            currentYesPrice={market.yes_price}
            currentNoPrice={market.no_price}
          />
        </section>

        {/* Liquidity */}
        <section aria-labelledby="liquidity-heading" className="rounded-xl border border-border bg-card p-5">
          <h2 id="liquidity-heading" className="mb-3 text-sm font-semibold text-foreground">Liquidity</h2>
          <AddLiquidityForm marketId={market.id} />
        </section>

        {/* Market Info */}
        <section aria-labelledby="info-heading" className="rounded-xl border border-border bg-card p-5">
          <h2 id="info-heading" className="mb-3 text-sm font-semibold text-foreground">Market Info</h2>
          <dl className="space-y-2.5">
            <div className="flex items-center justify-between text-xs">
              <dt className="text-muted-foreground">Status</dt>
              {market.status === "resolved" ? (
                <dd className="font-semibold px-1.5 py-0.5 rounded text-[10px] bg-yellow-500/10 text-yellow-600">
                  RESOLVED
                </dd>
              ) : (
                <dd className={cn(
                  "font-semibold capitalize px-1.5 py-0.5 rounded text-[10px]",
                  market.status === "active" ? "bg-green-500/10 text-green-500" : "bg-muted text-muted-foreground"
                )}>{market.status}</dd>
              )}
            </div>
            {market.status === "resolved" && market.winning_outcome_name ? (
              <div className="flex items-center justify-between text-xs">
                <dt className="text-muted-foreground">Winner</dt>
                <dd className="font-medium text-green-500">{market.winning_outcome_name}</dd>
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
                <dd className="font-medium">{((market as MarketDetailResponse).spread * 100).toFixed(1)}%</dd>
              </div>
            )}
            {isMultiOutcome && (
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
                    <span className="text-green-500 font-semibold">${m.yes_price.toFixed(2)}</span>
                    <span aria-hidden="true">·</span>
                    <span>${(m.total_volume / 1000).toFixed(0)}K vol</span>
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
      await api.post(`/api/v1/markets/${slug}/claim`)
      setClaimed(true)
      qc.invalidateQueries({ queryKey: ["wallet"] })
      qc.invalidateQueries({ queryKey: ["transactions"] })
      sileo.success({ title: "Winnings claimed!" })
    } catch (e) {
      sileo.error({ title: "Claim failed", description: e instanceof Error ? e.message : "Unknown error" })
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

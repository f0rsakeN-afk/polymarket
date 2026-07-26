"use client"

import { useCallback, useEffect, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { sileo } from "sileo"
import { LiveLineChart } from "@workspace/ui/components/charts/live-line-chart"
import { LiveXAxis } from "@workspace/ui/components/charts/live-x-axis"
import { LiveYAxis } from "@workspace/ui/components/charts/live-y-axis"
import { LiveLine } from "@workspace/ui/components/charts/live-line"
import { Spinner } from "@workspace/ui/components/spinner"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@workspace/ui/components/tabs"
import { useMarket, useMarketActivity, useMarketTrades, useFAQs, useRelatedMarkets } from "@/hooks/use-markets"
import { useMarketSocket } from "@/hooks/use-market-socket"
import { api } from "@/lib/api/client"
import { TradeFeed } from "@/components/trades/trade-feed"
import { TradeForm } from "./trade-form"
import { AlertDialog } from "@/components/alerts/alert-dialog"
import { OrderBook } from "./order-book"
import { CommentList, CommentForm } from "./comment-list"
import { LiveTradeTicker } from "./live-trade-ticker"
import type { LiveLinePoint } from "@workspace/ui/components/charts/live-line-chart"
import type { PlaceOrderInput } from "@/lib/schemas/trading"
import type { MarketDetailResponse } from "@/lib/types/api"
import { cn } from "@workspace/ui/lib/utils"

interface MarketDetailProps {
  slug: string
  onTrade?: (order: PlaceOrderInput) => Promise<void>
}

function MarketDetail({ slug, onTrade }: MarketDetailProps) {
  const queryClient = useQueryClient()
  const { data: market, isLoading: marketLoading } = useMarket(slug)
  const { data: activity, isLoading: activityLoading } = useMarketActivity(slug)
  const { data: tradesData, isLoading: tradesLoading } = useMarketTrades(slug)
  const { data: faqs } = useFAQs(slug)
  const { data: relatedMarkets } = useRelatedMarkets(slug)

  const { data: orderbookData } = useQuery({
    queryKey: ["orderbook-header", slug] as const,
    queryFn: () => api.get<{ success: boolean; data: { bids: { price: number; depth: number }[]; asks: { price: number; depth: number }[] } }>(`/api/v1/markets/${slug}/orderbook`),
    enabled: !!slug,
    refetchInterval: 5000,
    select: (res) => res.data,
  })

  const [priceHistory, setPriceHistory] = useState<LiveLinePoint[]>([])

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; yes_price?: number; no_price?: number; winning_outcome_name?: string }
    if (msg.type === "market:price_update" && msg.yes_price != null && msg.no_price != null) {
      const now = Math.floor(Date.now() / 1000)
      setPriceHistory((prev) => {
        const next = [
          ...prev,
          {
            time: now,
            value: msg.yes_price ?? 0,
            yes_price: msg.yes_price,
            no_price: msg.no_price,
          },
        ]
        return next.slice(-200)
      })
    }
    if (msg.type === "market:resolved") {
      sileo.info({
        title: "Market Resolved!",
        description: `Winning outcome: ${msg.winning_outcome_name ?? "Unknown"}`,
      })
      queryClient.invalidateQueries({ queryKey: ["market", slug] })
    }
    if (msg.type === "alert:triggered") {
      sileo.success({
        title: "Price Alert!",
        description: `${(msg as { outcome?: string }).outcome?.toUpperCase()} ${(msg as { condition?: string }).condition} $${(msg as { trigger_price?: number }).trigger_price?.toFixed(2)}`,
      })
    }
  }, [slug, queryClient])

  const { status: wsStatus } = useMarketSocket({
    marketId: market?.id ?? "",
    onMessage: handleWSMessage,
    enabled: !!market?.id,
  })

  useEffect(() => {
    if (!market) return
    const now = Math.floor(Date.now() / 1000)
    setPriceHistory([
      { time: now - 60, value: market.yes_price, yes_price: market.yes_price, no_price: market.no_price },
      { time: now, value: market.yes_price, yes_price: market.yes_price, no_price: market.no_price },
    ])
  }, [market])

  const handleTrade = useCallback(
    async (order: PlaceOrderInput) => { await onTrade?.(order) },
    [onTrade]
  )

  if (marketLoading && !market) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner className="size-5" />
      </div>
    )
  }

  if (!market) {
    return <div className="py-12 text-center text-muted-foreground">Market not found</div>
  }

  const isMultiOutcome = (market as MarketDetailResponse).outcomes?.length > 2

  return (
    <div className="grid gap-6 lg:grid-cols-4">
      {/* Left sidebar - Order Book */}
      <div className="space-y-4">
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="mb-3 text-sm font-semibold text-foreground">Order Book</h3>
          <OrderBook slug={slug} />
        </div>
      </div>

      {/* Main content */}
      <div className="space-y-6 lg:col-span-2">
        {/* Resolution banner */}
        {market.status === "resolved" && market.winning_outcome_name && (
          <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 p-4">
            <div className="text-sm font-semibold text-yellow-600">RESOLVED</div>
            <div className="text-xs text-muted-foreground mt-1">
              Winning outcome: <span className="font-medium text-foreground">{market.winning_outcome_name}</span>
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
                className={cn(
                  "size-2 rounded-full",
                  wsStatus === "connected" ? "bg-green-500" : wsStatus === "connecting" ? "bg-yellow-500 animate-pulse" : "bg-muted"
                )}
                title={`WebSocket: ${wsStatus}`}
              />
              <span className="text-xs text-muted-foreground">Vol ${market.total_volume.toLocaleString()}</span>
            </div>
          </div>
          <div className="h-[220px]">
            <LiveLineChart
              data={priceHistory}
              value={priceHistory.at(-1)?.yes_price ?? market.yes_price}
              valueNo={priceHistory.at(-1)?.no_price ?? market.no_price}
              window={60}
              numXTicks={5}
              height={220}
              margin={{ top: 16, right: 36, bottom: 40, left: 48 }}
            >
              <LiveXAxis />
              <LiveYAxis />
              <LiveLine dataKey="yes_price" stroke="var(--chart-1)" fill />
              <LiveLine dataKey="no_price" stroke="var(--chart-5)" fill />
            </LiveLineChart>
          </div>
          {/* Live Trade Ticker - floats over the chart */}
          <div className="absolute bottom-3 left-3 right-3 z-10 pointer-events-none">
            <LiveTradeTicker marketId={market.id} />
          </div>
        </div>

        {/* Stats */}
        {activity && (
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: "Volume", value: `$${(activity.market_stats.total_volume / 1e6).toFixed(1)}M` },
              { label: "Liquidity", value: `$${(activity.market_stats.total_liquidity / 1e6).toFixed(1)}M` },
              { label: "Spread", value: `${(activity.market_stats.spread * 100).toFixed(1)}%` },
              { label: "Trades", value: activity.market_stats.num_trades.toLocaleString() },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-lg border border-border bg-card p-3 text-center">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</div>
                <div className="font-semibold text-sm">{value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Tabs: Trades / Positions / Discussion / FAQs */}
        <Tabs defaultValue="trades" className="rounded-xl border border-border bg-card overflow-hidden">
          <TabsList className="w-full justify-start rounded-none border-b border-border bg-muted/50 p-0 h-auto">
            <TabsTrigger value="trades" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">Trades</TabsTrigger>
            <TabsTrigger value="positions" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">Positions</TabsTrigger>
            <TabsTrigger value="discussion" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">Discussion</TabsTrigger>
            {faqs && faqs.length > 0 && (
              <TabsTrigger value="faqs" className="rounded-none border-b-2 border-transparent data-active:border-primary data-active:bg-card px-4 py-2.5 text-xs font-semibold">FAQs</TabsTrigger>
            )}
          </TabsList>

          <div className="p-4">
            <TabsContent value="trades" className="min-h-[200px]">
              <TradeFeed
                trades={(tradesData?.trades ?? []).slice(0, 20)}
                loading={tradesLoading}
              />
            </TabsContent>

            <TabsContent value="positions" className="min-h-[200px]">
              {activity && Object.keys(activity.top_holders_by_outcome).length > 0 ? (
                <div className="max-h-64 overflow-y-auto scrollbar-hide">
                  <div className={Object.keys(activity.top_holders_by_outcome).length > 1 ? "grid grid-cols-2 gap-6" : ""}>
                    {Object.entries(activity.top_holders_by_outcome).map(([outcomeName, holders]) => (
                      <div key={outcomeName}>
                        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          {outcomeName}
                        </div>
                        <div className="space-y-1.5">
                          {holders.slice(0, 10).map((holder, i) => (
                            <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-border/50 last:border-0">
                              <span className="text-muted-foreground font-medium">{holder.username}</span>
                              <span className="font-semibold">{holder.shares_held.toFixed(0)} <span className="text-muted-foreground text-[10px]">shares</span></span>
                            </div>
                          ))}
                          {holders.length === 0 && (
                            <div className="text-xs text-muted-foreground py-2">No positions yet</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="py-8 text-center text-xs text-muted-foreground">No positions yet</div>
              )}
            </TabsContent>

            <TabsContent value="discussion" className="min-h-[200px]">
              <div className="mb-4">
                <CommentForm slug={slug} />
              </div>
              <CommentList slug={slug} />
            </TabsContent>

            <TabsContent value="faqs" className="min-h-[200px]">
              {faqs && faqs.length > 0 ? (
                <div className="max-h-64 overflow-y-auto scrollbar-hide space-y-3">
                  {faqs.map((faq, i) => (
                    <div key={faq.id} className={i > 0 ? "pt-3 border-t border-border" : ""}>
                      <div className="text-xs font-semibold text-foreground mb-1">{faq.question}</div>
                      <div className="text-xs text-muted-foreground leading-relaxed">{faq.answer}</div>
                    </div>
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
      <div className="space-y-4">
        {/* Trade card */}
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="mb-4 text-sm font-semibold text-foreground">Place Trade</h3>
          <TradeForm
            marketId={market.id}
            currentYesPrice={market.yes_price}
            currentNoPrice={market.no_price}
            outcomes={(market as MarketDetailResponse).outcomes}
            onSubmit={handleTrade}
          />
          <AlertDialog
            marketId={market.id}
            currentYesPrice={market.yes_price}
            currentNoPrice={market.no_price}
          />
        </div>

        {/* Market Info */}
        <div className="rounded-xl border border-border bg-card p-5">
          <h3 className="mb-3 text-sm font-semibold text-foreground">Market Info</h3>
          <div className="space-y-2.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Status</span>
              {market.status === "resolved" ? (
                <span className="font-semibold px-1.5 py-0.5 rounded text-[10px] bg-yellow-500/10 text-yellow-600">
                  RESOLVED
                </span>
              ) : (
                <span className={cn(
                  "font-semibold capitalize px-1.5 py-0.5 rounded text-[10px]",
                  market.status === "active" ? "bg-green-500/10 text-green-500" : "bg-muted text-muted-foreground"
                )}>{market.status}</span>
              )}
            </div>
            {market.status === "resolved" && market.winning_outcome_name ? (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Winner</span>
                <span className="font-medium text-green-500">{market.winning_outcome_name}</span>
              </div>
            ) : (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Closes</span>
                <span className="font-medium">{new Date(market.closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>
              </div>
            )}
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Liquidity</span>
              <span className="font-medium">${market.total_liquidity.toLocaleString()}</span>
            </div>
            {market.status !== "resolved" && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Spread</span>
                <span className="font-medium">{((market as MarketDetailResponse).spread * 100).toFixed(1)}%</span>
              </div>
            )}
            {isMultiOutcome && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Type</span>
                <span className="font-medium">Multi-outcome</span>
              </div>
            )}
          </div>
        </div>

        {/* Related Markets */}
        {relatedMarkets && relatedMarkets.length > 0 && (
          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="mb-3 text-sm font-semibold text-foreground">Related</h3>
            <div className="space-y-2">
              {relatedMarkets.slice(0, 5).map((m) => (
                <a
                  key={m.slug}
                  href={`/markets/${m.slug}`}
                  className="block rounded-lg border border-border p-3 hover:bg-muted/50 transition-colors"
                >
                  <div className="text-xs font-medium leading-snug line-clamp-2 mb-1.5">{m.question}</div>
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span className="text-green-500 font-semibold">${m.yes_price.toFixed(2)}</span>
                    <span>·</span>
                    <span>${(m.total_volume / 1000).toFixed(0)}K vol</span>
                  </div>
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export { MarketDetail }

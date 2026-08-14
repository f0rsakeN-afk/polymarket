"use client"

import { useQuery } from "@tanstack/react-query"
import { getOrderBook } from "@/lib/api/markets"
import type { OrderBookEntry } from "@/lib/api/markets"

function n(v: string | number | null | undefined, fallback = 0): number {
  if (v == null) return fallback
  const parsed = Number(v)
  return isNaN(parsed) ? fallback : parsed
}

function OrderBook({ slug }: { slug: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["orderbook", slug] as const,
    queryFn: () => getOrderBook(slug),
    enabled: !!slug,
    refetchInterval: 5000,
  })

  const bids: OrderBookEntry[] = data?.bids ?? []
  const asks: OrderBookEntry[] = data?.asks ?? []

  const maxDepth = Math.max(
    ...bids.map((b) => n(b.size)),
    ...asks.map((a) => n(a.size)),
    1
  )

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  if (bids.length === 0 && asks.length === 0) {
    return (
      <div className="py-10 text-center text-xs text-muted-foreground">
        No orders yet
      </div>
    )
  }

  const bestBid = n(bids[0]?.price)
  const bestAsk = n(asks[asks.length - 1]?.price)
  const spread =
    bids.length > 0 && asks.length > 0
      ? ((bestAsk - bestBid) * 100).toFixed(2)
      : null

  return (
    <section aria-label="Order book" className="space-y-2">
      {/* Column headers */}
      <div className="flex items-center justify-between px-1 mb-1">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Price
        </span>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Size
        </span>
      </div>

      {/* Asks (sells) — reversed so lowest ask is at bottom */}
      <div role="list" aria-label="Sell orders">
        {[...asks]
          .reverse()
          .map((ask, i) => (
            <div
              key={`ask-${i}`}
              role="listitem"
              className="relative h-6 overflow-hidden rounded-sm"
              aria-label={`Sell at $${n(ask.price).toFixed(3)}, size ${n(
                ask.size
              ).toFixed(0)}`}
            >
              <div
                className="absolute inset-y-0 right-0 bg-red-500/20"
                style={{ width: `${(n(ask.size) / maxDepth) * 100}%` }}
                aria-hidden="true"
              />
              <div className="absolute inset-y-0 flex items-center justify-between px-2 text-xs">
                <span className="text-red-400 font-medium">
                  ${n(ask.price).toFixed(3)}
                </span>
                <span className="font-semibold text-red-400">
                  {n(ask.size).toFixed(0)}
                </span>
              </div>
            </div>
          ))}
      </div>

      {/* Spread indicator */}
      <div
        className="flex items-center justify-center py-1"
        role="status"
        aria-label={spread ? `Spread ${spread}%` : "No spread"}
      >
        <span className="rounded-full bg-muted px-2.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
          {spread
            ? `Spread: ${spread}%`
            : bids.length > 0
              ? "Bid side"
              : "Ask side"}
        </span>
      </div>

      {/* Bids (buys) */}
      <div role="list" aria-label="Buy orders">
        {bids.map((bid, i) => (
          <div
            key={`bid-${i}`}
            role="listitem"
            className="relative h-6 overflow-hidden rounded-sm"
            aria-label={`Buy at $${n(bid.price).toFixed(3)}, size ${n(
              bid.size
            ).toFixed(0)}`}
          >
            <div
              className="absolute inset-y-0 right-0 bg-green-500/20"
              style={{ width: `${(n(bid.size) / maxDepth) * 100}%` }}
              aria-hidden="true"
            />
            <div className="absolute inset-y-0 flex items-center justify-between px-2 text-xs">
              <span className="text-green-400 font-medium">
                ${n(bid.price).toFixed(3)}
              </span>
              <span className="font-semibold text-green-400">
                {n(bid.size).toFixed(0)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export { OrderBook }

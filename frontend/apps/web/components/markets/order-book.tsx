"use client"

import { memo, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { getOrderBook } from "@/lib/api/markets"
import type { OrderBookEntry } from "@/lib/api/markets"

function n(v: string | number | null | undefined, fallback = 0): number {
  if (v == null) return fallback
  const parsed = Number(v)
  return isNaN(parsed) ? fallback : parsed
}

const OutcomeOrderbook = memo(function OutcomeOrderbook({
  name,
  bids,
  asks,
}: {
  name: string
  bids: OrderBookEntry[]
  asks: OrderBookEntry[]
}) {
  const maxDepth = useMemo(() => Math.max(
    ...bids.map((b) => n(b.size)),
    ...asks.map((a) => n(a.size)),
    1
  ), [bids, asks])

  const bestBid = bids[0] ? n(bids[0].price) : null
  const bestAsk = asks.length > 0 ? n(asks[asks.length - 1]!.price) : null
  const spread =
    bestBid !== null && bestAsk !== null
      ? ((bestAsk - bestBid) * 100).toFixed(2)
      : null

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between px-1 mb-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-foreground">{name}</span>
        {spread !== null && (
          <span className="text-[10px] text-muted-foreground">Spread {spread}%</span>
        )}
      </div>

      {/* Column headers */}
      <div className="flex items-center justify-between px-1 mb-1 text-[9px] uppercase tracking-wider text-muted-foreground">
        <span>Bid</span>
        <span>Price</span>
        <span>Ask</span>
      </div>

      {/* Combined asks + bids rows */}
      <div className="flex flex-col gap-0.5">
        {/* Asks (sell orders) — lowest ask at bottom, shown right side */}
        {[...asks].reverse().map((ask, i) => (
          <div key={`ask-${i}`} className="relative h-5 overflow-hidden rounded-[3px]">
            <div
              className="absolute inset-y-0 right-0 bg-red-500/25"
              style={{ width: `${(n(ask.size) / maxDepth) * 100}%` }}
              aria-hidden="true"
            />
            <div className="absolute inset-y-0 flex items-center justify-between px-1.5 text-[10px]">
              <span className="w-12 text-right text-red-400/60 font-medium">
                {n(ask.size) > 0 ? n(ask.size).toFixed(0) : ""}
              </span>
              <span className="w-12 text-center font-semibold text-red-400">
                ${n(ask.price).toFixed(3)}
              </span>
              <span className="w-12" />
            </div>
          </div>
        ))}

        {/* Spread divider */}
        <div className="flex items-center justify-center py-0.5 my-0.5 rounded bg-muted/50">
          <span className="text-[9px] font-semibold text-muted-foreground">
            {spread !== null ? `${spread}% spread` : bestBid !== null ? "Bid side only" : "Ask side only"}
          </span>
        </div>

        {/* Bids (buy orders) — highest bid at top */}
        {bids.map((bid, i) => (
          <div key={`bid-${i}`} className="relative h-5 overflow-hidden rounded-[3px]">
            <div
              className="absolute inset-y-0 right-0 bg-green-500/25"
              style={{ width: `${(n(bid.size) / maxDepth) * 100}%` }}
              aria-hidden="true"
            />
            <div className="absolute inset-y-0 flex items-center justify-between px-1.5 text-[10px]">
              <span className="w-12 text-right text-green-400/60 font-medium">
                {n(bid.size) > 0 ? n(bid.size).toFixed(0) : ""}
              </span>
              <span className="w-12 text-center font-semibold text-green-400">
                ${n(bid.price).toFixed(3)}
              </span>
              <span className="w-12" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
})

function OrderBook({ slug }: { slug: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["orderbook", slug] as const,
    queryFn: () => getOrderBook(slug),
    enabled: !!slug,
    // No refetchInterval — WS 'orderbook:update' message drives cache invalidation.
    // Each WS message triggers one fresh fetch, which is the correct push model.
    // If backend sends full orderbook in the WS message, this can be replaced
    // with cache.setQueryData for zero-latency update (no extra round-trip).
  })

  const outcomes = data?.data?.outcomes ?? {}

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  const outcomeNames = Object.keys(outcomes)
  if (outcomeNames.length === 0) {
    return (
      <div className="py-10 text-center text-xs text-muted-foreground">
        No orders yet
      </div>
    )
  }

  // Two-column grid for binary markets, single column for multi-outcome
  const isBinary = outcomeNames.length === 2

  return (
    <section aria-label="Order book" className="space-y-4">
      {isBinary ? (
        // Binary: YES and NO side by side
        <div className="grid grid-cols-2 gap-6">
          {outcomeNames.map((name) => (
            <OutcomeOrderbook
              key={name}
              name={name}
              bids={outcomes[name]?.bids ?? []}
              asks={outcomes[name]?.asks ?? []}
            />
          ))}
        </div>
      ) : (
        // Multi-outcome: stacked
        <div className="grid grid-cols-2 gap-x-8 gap-y-6 sm:grid-cols-3 lg:grid-cols-4">
          {outcomeNames.map((name) => (
            <OutcomeOrderbook
              key={name}
              name={name}
              bids={outcomes[name]?.bids ?? []}
              asks={outcomes[name]?.asks ?? []}
            />
          ))}
        </div>
      )}
    </section>
  )
}

export { OrderBook }

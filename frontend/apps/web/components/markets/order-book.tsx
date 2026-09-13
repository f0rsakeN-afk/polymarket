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
        <span className="text-xs font-semibold uppercase tracking-wider text-foreground">{name}</span>
        {spread !== null && (
          <span className="text-xs text-muted-foreground tabular-nums">Spread {spread}%</span>
        )}
      </div>

      {/* Column headers */}
      <div className="flex items-center justify-between px-1 mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
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
            <div className="absolute inset-y-0 flex w-full items-center justify-between px-1.5 text-xs">
              <span className="w-12 text-right font-medium text-red-700/70 tabular-nums dark:text-red-400/70">
                {n(ask.size) > 0 ? n(ask.size).toFixed(0) : ""}
              </span>
              <span className="w-12 text-center font-semibold text-red-700 tabular-nums dark:text-red-400">
                ${n(ask.price).toFixed(3)}
              </span>
              <span className="w-12" />
            </div>
          </div>
        ))}

        {/* Spread divider */}
        <div className="my-0.5 flex items-center justify-center rounded bg-muted/50 py-0.5">
          <span className="text-[10px] font-semibold text-muted-foreground">
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
            <div className="absolute inset-y-0 flex w-full items-center justify-between px-1.5 text-xs">
              <span className="w-12 text-right font-medium text-green-700/70 tabular-nums dark:text-green-400/70">
                {n(bid.size) > 0 ? n(bid.size).toFixed(0) : ""}
              </span>
              <span className="w-12 text-center font-semibold text-green-700 tabular-nums dark:text-green-400">
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

const OrderBook = memo(function OrderBook({ slug }: { slug: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["orderbook", slug] as const,
    queryFn: () => getOrderBook(slug),
    enabled: !!slug,
  })

  const outcomes = useMemo(() => data?.data?.outcomes ?? {}, [data])

  const outcomeNames = useMemo(() => Object.keys(outcomes), [outcomes])

  const outcomeEntries = useMemo(
    () => outcomeNames.map((name) => ({
      name,
      bids: outcomes[name]?.bids ?? [],
      asks: outcomes[name]?.asks ?? [],
    })),
    [outcomeNames, outcomes]
  )

  if (isLoading) {
    return (
      <div role="status" className="flex h-48 items-center justify-center">
        <div aria-hidden="true" className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="sr-only">Loading…</span>
      </div>
    )
  }

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
        // Binary: YES and NO side by side (stack on mobile)
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 sm:gap-6">
          {outcomeEntries.map(({ name, bids, asks }) => (
            <OutcomeOrderbook
              key={name}
              name={name}
              bids={bids}
              asks={asks}
            />
          ))}
        </div>
      ) : (
        // Multi-outcome: stacked
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 sm:gap-x-6 sm:gap-y-6 lg:grid-cols-3 xl:grid-cols-4">
          {outcomeEntries.map(({ name, bids, asks }) => (
            <OutcomeOrderbook
              key={name}
              name={name}
              bids={bids}
              asks={asks}
            />
          ))}
        </div>
      )}
    </section>
  )
})

export { OrderBook }

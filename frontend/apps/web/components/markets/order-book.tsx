"use client"

import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api/client"

interface OrderBookLevel {
  price: number
  depth: number
  outcome: string
}

async function fetchOrderBook(slug: string) {
  return api.get<{ success: boolean; data: { bids: OrderBookLevel[]; asks: OrderBookLevel[] } }>(
    `/api/v1/markets/${slug}/orderbook`
  )
}

function OrderBook({ slug }: { slug: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["orderbook", slug] as const,
    queryFn: () => fetchOrderBook(slug),
    enabled: !!slug,
    refetchInterval: 5000,
  })

  const bids = data?.data?.bids ?? []
  const asks = data?.data?.asks ?? []

  const maxDepth = Math.max(
    ...bids.map((b) => b.depth),
    ...asks.map((a) => a.depth),
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

  return (
    <div className="space-y-2">
      {/* Column headers */}
      <div className="flex items-center justify-between px-1 mb-1">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Price</span>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Size</span>
      </div>

      {/* Asks (sells) — reversed so lowest ask is at bottom */}
      <div className="space-y-1">
        {[...asks].reverse().map((ask, i) => (
          <div key={`ask-${i}`} className="relative h-6 overflow-hidden rounded-sm">
            <div
              className="absolute inset-y-0 right-0 bg-red-500/20"
              style={{ width: `${(ask.depth / maxDepth) * 100}%` }}
            />
            <div className="absolute inset-y-0 flex items-center justify-between px-2 text-xs">
              <span className="text-muted-foreground font-medium">${ask.price.toFixed(3)}</span>
              <span className="font-semibold text-red-400">{ask.depth.toFixed(0)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Spread indicator */}
      <div className="flex items-center justify-center py-1">
        <span className="rounded-full bg-muted px-2.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
          {bids.length > 0 && asks.length > 0
            ? `Spread: ${((asks[asks.length - 1]!.price - bids[0]!.price) * 100).toFixed(2)}%`
            : bids.length > 0 ? "Bid side" : "Ask side"}
        </span>
      </div>

      {/* Bids (buys) */}
      <div className="space-y-1">
        {bids.map((bid, i) => (
          <div key={`bid-${i}`} className="relative h-6 overflow-hidden rounded-sm">
            <div
              className="absolute inset-y-0 right-0 bg-green-500/20"
              style={{ width: `${(bid.depth / maxDepth) * 100}%` }}
            />
            <div className="absolute inset-y-0 flex items-center justify-between px-2 text-xs">
              <span className="text-muted-foreground font-medium">${bid.price.toFixed(3)}</span>
              <span className="font-semibold text-green-400">{bid.depth.toFixed(0)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export { OrderBook }

"use client"

import { useCallback } from "react"
import { useParams } from "next/navigation"
import { sileo } from "sileo"
import { MarketDetail } from "@/components/markets/market-detail"
import { usePlaceOrder } from "@/hooks/api/use-orders"
import type { PlaceOrderInput } from "@/lib/schemas/trading"

export function MarketDetailClient() {
  const params = useParams<{ slug: string }>()
  const slug = params.slug
  const { mutateAsync: placeOrder } = usePlaceOrder()

  const handleTrade = useCallback(async (order: PlaceOrderInput) => {
    try {
      const result = await placeOrder(order)
      const { data } = result
      const shares = parseFloat(data.shares || "0").toFixed(2)
      const price = parseFloat(data.price || "0").toFixed(4)
      const detail = `${shares} shares at $${price}`
      if (data.status === "duplicate" || data.duplicate) {
        sileo.info({
          title: result.message ?? "Order already placed",
          description: `View in orders (${detail})`,
        })
      } else {
        sileo.success({
          title: result.message ?? `Order placed: ${order.side.toUpperCase()} ${order.outcome.toUpperCase()}`,
          description: detail,
        })
      }
    } catch {
      // Error toast • including the backend's message • is emitted by
      // usePlaceOrder, so re-throwing here would only duplicate it.
    }
  }, [placeOrder])

  if (!slug) return null

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <MarketDetail key={slug} slug={slug} onTrade={handleTrade} />
    </div>
  )
}

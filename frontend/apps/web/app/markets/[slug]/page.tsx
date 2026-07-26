"use client"

import { useCallback } from "react"
import { useParams } from "next/navigation"
import { sileo } from "sileo"
import { MarketDetail } from "@/components/markets/market-detail"
import { usePlaceOrder } from "@/hooks/use-orders"
import type { PlaceOrderInput } from "@/lib/schemas/trading"

export default function MarketPage() {
  const params = useParams<{ slug: string }>()
  const slug = params.slug
  const { mutateAsync: placeOrder } = usePlaceOrder()

  const handleTrade = useCallback(async (order: PlaceOrderInput) => {
    try {
      await placeOrder(order)
      sileo.success({ title: `Order placed: ${order.side.toUpperCase()} ${order.outcome.toUpperCase()}` })
    } catch (e) {
      sileo.error({ title: "Trade failed", description: e instanceof Error ? e.message : "Unknown error" })
    }
  }, [placeOrder])

  if (!slug) return null

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <MarketDetail slug={slug} onTrade={handleTrade} />
    </div>
  )
}

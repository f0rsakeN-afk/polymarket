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
      const result = await placeOrder(order) as { success?: boolean; data?: { status?: string; shares?: number; price?: number; duplicate?: boolean } }
      const status = result?.data?.status
      if (status === "duplicate" || result?.data?.duplicate) {
        sileo.info({ title: "Order already placed", description: `View in orders (${result?.data?.shares?.toFixed(2) ?? 0} shares at $${result?.data?.price?.toFixed(4) ?? 0})` })
      } else {
        sileo.success({ title: `Order placed: ${order.side.toUpperCase()} ${order.outcome.toUpperCase()}`, description: `${result?.data?.shares?.toFixed(2) ?? 0} shares at $${result?.data?.price?.toFixed(4) ?? 0}` })
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Unknown error"
      if (msg.includes("slippage")) {
        sileo.error({ title: "Price moved", description: "The price changed more than expected. Please review and try again." })
      } else if (msg.includes("duplicate") || msg.includes("already placed")) {
        sileo.info({ title: "Order already placed" })
      } else {
        sileo.error({ title: "Trade failed", description: msg })
      }
    }
  }, [placeOrder])

  if (!slug) return null

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <MarketDetail slug={slug} onTrade={handleTrade} />
    </div>
  )
}

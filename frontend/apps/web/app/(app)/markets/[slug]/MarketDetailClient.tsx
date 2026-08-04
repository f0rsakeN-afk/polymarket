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
      const err = e as { message: string; error_code?: string }
      const msg = err.message
      const code = err.error_code
      if (code === "VALIDATION_ERROR") {
        sileo.error({ title: "Invalid order", description: msg })
      } else if (msg.includes("slippage") || code === "SLIPPAGE_EXCEEDED") {
        sileo.error({ title: "Price moved", description: "The price changed more than expected. Please review and try again." })
      } else if (msg.includes("duplicate") || msg.includes("already placed") || code === "DUPLICATE_ORDER") {
        sileo.info({ title: "Order already placed" })
      } else if (code === "INSUFFICIENT_BALANCE") {
        sileo.error({ title: "Insufficient balance", description: "You don't have enough funds for this order." })
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

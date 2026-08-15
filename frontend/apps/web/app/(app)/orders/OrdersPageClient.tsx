"use client"

import { useCallback } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Card } from "@workspace/ui/components/card"
import { useOrders } from "@/hooks/api/use-orders"
import { useUserSocket } from "@/hooks/use-user-socket"
import { useCurrentUser } from "@/hooks/use-auth"
import { OrdersList } from "@/components/orders/orders-list"

export function OrdersPageClient() {
  const { data: user } = useCurrentUser()
  const qc = useQueryClient()

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useOrders()
  const orders = data?.orders ?? []
  const hasMore = data?.hasMore ?? false

  const handleWsMessage = useCallback((payload: unknown) => {
    const msg = payload as { type?: string; notification?: { type?: string } }
    if (msg?.type === "position:update" || msg?.notification?.type === "order_filled") {
      qc.invalidateQueries({ queryKey: ["orders"] })
      qc.invalidateQueries({ queryKey: ["positions"] })
    }
  }, [qc])

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: Boolean(user?.id),
  })

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-4">
      <h1 className="text-2xl font-semibold">Orders</h1>
      <Card className="p-4">
        <OrdersList
          orders={orders}
          loading={isLoading || isFetchingNextPage}
          hasMore={hasMore}
          onLoadMore={fetchNextPage}
        />
      </Card>
    </div>
  )
}

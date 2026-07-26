"use client"

import { OrdersList } from "@/components/orders/orders-list"
import { useOrders } from "@/hooks/use-orders"

export default function OrdersPage() {
  const { data, isLoading, fetchNextPage, hasNextPage } = useOrders()

  return (
    <div className="container mx-auto max-w-4xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Orders</h1>
        <p className="mt-1 text-muted-foreground">Your trading orders</p>
      </div>
      <OrdersList
        orders={data?.orders ?? []}
        loading={isLoading}
        hasMore={hasNextPage ?? false}
        onLoadMore={fetchNextPage}
      />
    </div>
  )
}

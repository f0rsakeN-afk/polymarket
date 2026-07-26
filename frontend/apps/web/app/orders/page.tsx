"use client"

import { useState } from "react"
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from "@workspace/ui/components/select"
import { OrdersList } from "@/components/orders/orders-list"
import { useOrders } from "@/hooks/use-orders"

export default function OrdersPage() {
  const [status, setStatus] = useState("")
  const [side, setSide] = useState("")
  const [orderType, setOrderType] = useState("")

  const filters = {
    ...(status && { status }),
    ...(side && { side }),
    ...(orderType && { order_type: orderType }),
  }

  const { data, isLoading, fetchNextPage, hasNextPage } = useOrders(filters)

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Orders</h1>
        <p className="mt-1 text-muted-foreground">Your trading orders</p>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <div className="w-32">
          <Select value={status} onValueChange={(v) => setStatus(v ?? "")}>
            <SelectTrigger><SelectValue placeholder="All status" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="">All status</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="partial">Partial</SelectItem>
              <SelectItem value="filled">Filled</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
              <SelectItem value="expired">Expired</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-28">
          <Select value={side} onValueChange={(v) => setSide(v ?? "")}>
            <SelectTrigger><SelectValue placeholder="Both sides" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="">Both sides</SelectItem>
              <SelectItem value="buy">Buy</SelectItem>
              <SelectItem value="sell">Sell</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-32">
          <Select value={orderType} onValueChange={(v) => setOrderType(v ?? "")}>
            <SelectTrigger><SelectValue placeholder="All types" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="">All types</SelectItem>
              <SelectItem value="market">Market</SelectItem>
              <SelectItem value="limit">Limit</SelectItem>
              <SelectItem value="fill_or_kill">FOK</SelectItem>
            </SelectContent>
          </Select>
        </div>
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

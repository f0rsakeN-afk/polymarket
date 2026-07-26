"use client"

import { useCallback, useEffect, useRef, useState, memo } from "react"
import { Spinner } from "@workspace/ui/components/spinner"
import { Button } from "@workspace/ui/components/button"
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@workspace/ui/components/alert-dialog"
import { useCancelOrder } from "@/hooks/use-orders"
import { sileo } from "sileo"
import type { Order } from "@/lib/types/api"

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

interface OrderRowProps {
  order: Order
}

function OrderRow({ order }: OrderRowProps) {
  const { mutateAsync: cancelOrder, isPending } = useCancelOrder()
  const [open, setOpen] = useState(false)

  const handleCancelConfirm = useCallback(async () => {
    try {
      await cancelOrder(order.id)
      sileo.success({ title: "Order cancelled" })
      setOpen(false)
    } catch (e) {
      sileo.error({ title: "Cancel failed", description: e instanceof Error ? e.message : "Unknown error" })
    }
  }, [cancelOrder, order.id])

  const handleDialogOpenChange = useCallback((next: boolean) => {
    setOpen(next)
  }, [])

  return (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-0">
      <div className="min-w-0">
        <div className="truncate text-xs font-medium">{order.market_question}</div>
        <div className="mt-0.5 flex items-center gap-2 text-muted-foreground">
          <span
            className={`text-[10px] font-semibold uppercase ${
              order.outcome === "yes" ? "text-green-500" : "text-red-500"
            }`}
          >
            {order.outcome}
          </span>
          <span className="text-[10px]">{order.side}</span>
          <span className="text-[10px]">{order.amount} @ ${order.price.toFixed(2)}</span>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-4">
        <span
          className={`text-[10px] font-semibold uppercase ${
            order.status === "filled"
              ? "text-green-500"
              : order.status === "cancelled"
              ? "text-muted-foreground"
              : "text-yellow-500"
          }`}
        >
          {order.status}
        </span>
        {order.status === "pending" && (
          <AlertDialog open={open} onOpenChange={handleDialogOpenChange}>
            <AlertDialogTrigger render={<Button variant="ghost" size="sm" className="h-5 text-[10px] text-red-500 hover:text-red-400">Cancel</Button>} />
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Cancel Order</AlertDialogTitle>
                <AlertDialogDescription>
                  Are you sure you want to cancel this order for {order.amount} @ ${order.price.toFixed(2)}?
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep Order</AlertDialogCancel>
                <AlertDialogAction onClick={handleCancelConfirm}>
                  {isPending ? "Cancelling..." : "Cancel Order"}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
    </div>
  )
}

interface OrdersListProps {
  orders: Order[]
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
}

function OrdersList({ orders, loading, hasMore, onLoadMore }: OrdersListProps) {
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0]
        if (entry?.isIntersecting && hasMore && !loading) {
          onLoadMore()
        }
      },
      { threshold: 0.1 }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, loading, onLoadMore])

  return (
    <div className="rounded-xl border border-border bg-card p-4 text-xs/relaxed">
      <h3 className="mb-3 text-sm font-medium">Orders</h3>
      {loading && orders.length === 0 ? (
        <div className="py-6 text-center text-muted-foreground">
          <Spinner className="size-5" />
        </div>
      ) : orders.length === 0 ? (
        <div className="py-6 text-center text-muted-foreground">No orders yet</div>
      ) : (
        <>
          <div>
            {orders.map((order) => (
              <OrderRow key={order.id} order={order} />
            ))}
          </div>
          <div ref={sentinelRef} className="flex justify-center py-3">
            {loading && <Spinner className="size-5" />}
          </div>
        </>
      )}
    </div>
  )
}

export { OrdersList }
export default memo(OrdersList)

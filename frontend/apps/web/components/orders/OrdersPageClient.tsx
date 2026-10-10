"use client"

import { useCallback, useRef, useEffect, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@workspace/ui/components/alert-dialog"
import { Spinner } from "@workspace/ui/components/spinner"
import { DataTable, Column } from "@/components/shared/data-table"
import { useOrders } from "@/hooks/api/use-orders"
import { useUserSocket } from "@/hooks/use-user-socket"
import { applyPrivateFeedResync } from "@/lib/ws-resync"
import { useCurrentUser } from "@/hooks/use-auth"
import { useCancelOrder } from "@/hooks/api/use-orders"
import { queryKeys } from "@/lib/api/queryKeys"
import { cn } from "@workspace/ui/lib/utils"
import type { Order } from "@/hooks/api/types/order"

type StatusFilter = "all" | "pending" | "filled" | "cancelled" | "partial"

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "filled", label: "Filled" },
  { value: "partial", label: "Partial" },
  { value: "cancelled", label: "Cancelled" },
]

function n(v: string | number | null | undefined, fallback = 0): number {
  if (v == null) return fallback
  const x = Number(v)
  return isNaN(x) ? fallback : x
}

function formatTime(iso: string | null | undefined) {
  if (!iso) return "•"
  const d = new Date(iso)
  const now = new Date()
  const diff = (now.getTime() - d.getTime()) / 1000
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function SideBadge({ side }: { side: string }) {
  if (side === "buy") {
    return (
      <Badge className="bg-emerald-600 text-xs text-white capitalize hover:bg-emerald-700">
        buy
      </Badge>
    )
  }
  return (
    <Badge variant="destructive" className="text-xs capitalize">
      sell
    </Badge>
  )
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  if (outcome === "yes") {
    return (
      <Badge className="bg-emerald-600 text-xs text-white capitalize hover:bg-emerald-700">
        yes
      </Badge>
    )
  }
  if (outcome === "no") {
    return (
      <Badge variant="destructive" className="text-xs capitalize">
        no
      </Badge>
    )
  }
  return (
    <Badge
      variant="secondary"
      className="max-w-[80px] truncate text-xs capitalize"
      title={outcome}
    >
      {outcome}
    </Badge>
  )
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, string> = {
    filled:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
    cancelled: "bg-muted text-muted-foreground",
    pending:
      "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
    partial: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
    expired: "bg-muted text-muted-foreground",
  }
  const cls = variants[status] ?? "bg-muted text-muted-foreground"
  return <Badge className={cn("text-xs capitalize", cls)}>{status}</Badge>
}

// ── Cancel Dialog ─────────────────────────────────────────────────────────────

function CancelButton({ order }: { order: Order }) {
  const { mutateAsync: cancelOrder, isPending } = useCancelOrder()
  const [open, setOpen] = useState(false)

  const handleConfirm = useCallback(async () => {
    try {
      await cancelOrder(order.id)
      setOpen(false)
    } catch {
      // Toast (with the backend's message) is emitted by useCancelOrder.
    }
  }, [cancelOrder, order.id])

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger className="inline-flex h-6 items-center justify-center rounded-md px-2 py-1 text-xs text-destructive transition-colors hover:bg-destructive/10">
        Cancel
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Cancel Order</AlertDialogTitle>
          <AlertDialogDescription>
            Are you sure you want to cancel this order for{" "}
            {Number(order.amount).toFixed(2)} shares @ $
            {Number(order.price).toFixed(2)}?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep Order</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            className="bg-destructive hover:bg-destructive/90"
          >
            {isPending ? "Cancelling..." : "Cancel Order"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function OrdersPageClient() {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const { data, fetchNextPage, isFetchingNextPage, isLoading, error, refetch } =
    useOrders(statusFilter === "all" ? {} : { status: statusFilter })
  const orders = data?.orders ?? []
  const hasMore = data?.hasMore ?? false
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasMore && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { threshold: 0.1 }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [hasMore, isFetchingNextPage, fetchNextPage])

  const handleWsMessage = useCallback(
    (payload: unknown) => {
      // The socket reconnected; fills may have been missed while it was down.
      if (applyPrivateFeedResync(qc, payload)) return
      const msg = payload as { type?: string; notification?: { type?: string } }
      if (
        msg?.type === "position:update" ||
        msg?.notification?.type === "order_filled"
      ) {
        qc.invalidateQueries({ queryKey: queryKeys.orders() })
        qc.invalidateQueries({ queryKey: ["positions"] })
      }
    },
    [qc]
  )

  const handleFilterClick = useCallback((filter: StatusFilter) => {
    setStatusFilter(filter)
  }, [])

  const makeFilterHandler = useCallback(
    (f: StatusFilter) => () => handleFilterClick(f),
    [handleFilterClick]
  )

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: Boolean(user?.id),
  })

  const columns: Column<Order>[] = [
    {
      key: "market_question",
      header: "Market",
      sortable: true,
      className: "w-[38%] font-medium max-w-xs truncate",
      render: (row) => (
        <span className="block truncate">{row.market_question ?? "•"}</span>
      ),
    },
    {
      key: "side",
      header: "Side",
      className: "w-[10%]",
      render: (row) => <SideBadge side={row.side} />,
    },
    {
      key: "outcome",
      header: "Outcome",
      className: "w-[10%]",
      render: (row) => <OutcomeBadge outcome={row.outcome} />,
    },
    {
      key: "order_type",
      header: "Type",
      sortable: true,
      className: "w-[10%] capitalize text-muted-foreground text-sm",
      render: (row) => row.order_type.replace("_", " "),
    },
    {
      key: "price",
      header: "Price",
      sortable: true,
      className: "w-[10%] text-right tabular-nums text-sm",
      render: (row) => `$${n(row.price).toFixed(3)}`,
    },
    {
      key: "amount",
      header: "Amount",
      sortable: true,
      className: "w-[10%] text-right tabular-nums text-sm",
      render: (row) => n(row.amount).toFixed(0),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      className: "w-[10%]",
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "created_at",
      header: "Time",
      sortable: true,
      className: "w-[8%] text-muted-foreground text-xs",
      render: (row) => formatTime(row.created_at),
    },
    {
      key: "cancel",
      header: "",
      className: "w-[4%]",
      render: (row) =>
        row.status === "pending" || row.status === "partial" ? (
          <CancelButton order={row} />
        ) : null,
    },
  ]

  return (
    <div className="container mx-auto max-w-7xl space-y-6 px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Orders</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {orders.length} orders
          </p>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1">
        {STATUS_FILTERS.map((f) => (
          <Button
            key={f.value}
            variant={statusFilter === f.value ? "default" : "ghost"}
            size="sm"
            onClick={makeFilterHandler(f.value)}
            className="text-xs"
          >
            {f.label}
          </Button>
        ))}
      </div>

      {/* Table */}
      <DataTable
        data={orders}
        columns={columns}
        loading={isLoading}
        error={error}
        onRetry={refetch}
        rowKey={(row) => row.id}
        emptyMessage="No orders found"
        skeletonRows={8}
      />

      {/* Load more sentinel */}
      <div ref={sentinelRef} className="flex justify-center py-2">
        {isFetchingNextPage && <Spinner className="size-5" />}
      </div>
    </div>
  )
}

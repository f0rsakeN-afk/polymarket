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
import { useCurrentUser } from "@/hooks/use-auth"
import { sileo } from "sileo"
import { useCancelOrder } from "@/hooks/api/use-orders"
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

function formatTime(iso: string) {
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
    return <Badge className="bg-emerald-600 hover:bg-emerald-700 text-white capitalize text-xs">buy</Badge>
  }
  return <Badge variant="destructive" className="capitalize text-xs">sell</Badge>
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  if (outcome === "yes") {
    return <Badge className="bg-emerald-600 hover:bg-emerald-700 text-white capitalize text-xs">yes</Badge>
  }
  if (outcome === "no") {
    return <Badge variant="destructive" className="capitalize text-xs">no</Badge>
  }
  return <Badge variant="secondary" className="capitalize text-xs truncate max-w-[80px]" title={outcome}>{outcome}</Badge>
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, string> = {
    filled: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
    cancelled: "bg-muted text-muted-foreground",
    pending: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
    partial: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
    expired: "bg-muted text-muted-foreground",
  }
  const cls = variants[status] ?? "bg-muted text-muted-foreground"
  return <Badge className={cn("capitalize text-xs", cls)}>{status}</Badge>
}

// ── Cancel Dialog ─────────────────────────────────────────────────────────────

function CancelButton({ order }: { order: Order }) {
  const { mutateAsync: cancelOrder, isPending } = useCancelOrder()
  const [open, setOpen] = useState(false)

  const handleConfirm = useCallback(async () => {
    try {
      await cancelOrder(order.id)
      sileo.success({ title: "Order cancelled" })
      setOpen(false)
    } catch (e) {
      sileo.error({ title: "Cancel failed", description: e instanceof Error ? e.message : "Unknown error" })
    }
  }, [cancelOrder, order.id])

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger className="inline-flex items-center justify-center rounded-md text-xs px-2 py-1 h-6 text-destructive hover:bg-destructive/10 transition-colors">
        Cancel
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Cancel Order</AlertDialogTitle>
          <AlertDialogDescription>
            Are you sure you want to cancel this order for {Number(order.amount).toFixed(2)} shares @ ${Number(order.price).toFixed(2)}?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep Order</AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirm} className="bg-destructive hover:bg-destructive/90">
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
  const { data, fetchNextPage, isFetchingNextPage, isLoading, error, refetch } = useOrders(
    statusFilter === "all" ? {} : { status: statusFilter }
  )
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

  const handleWsMessage = useCallback((payload: unknown) => {
    const msg = payload as { type?: string; notification?: { type?: string } }
    if (msg?.type === "position:update" || msg?.notification?.type === "order_filled") {
      qc.invalidateQueries({ queryKey: ["orders"] })
      qc.invalidateQueries({ queryKey: ["positions"] })
    }
  }, [qc])

  const handleFilterClick = useCallback((filter: StatusFilter) => {
    setStatusFilter(filter)
  }, [])

  const makeFilterHandler = useCallback((f: StatusFilter) => () => handleFilterClick(f), [handleFilterClick])

  useUserSocket({ userId: user?.id ?? "", onMessage: handleWsMessage, enabled: Boolean(user?.id) })

  const columns: Column<Order>[] = [
    {
      key: "market_question",
      header: "Market",
      sortable: true,
      className: "w-[38%] font-medium max-w-xs truncate",
      render: (row) => <span className="truncate block">{row.market_question ?? "—"}</span>,
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
        (row.status === "pending" || row.status === "partial") ? (
          <CancelButton order={row} />
        ) : null,
    },
  ]

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Orders</h1>
          <p className="text-sm text-muted-foreground mt-0.5">{orders.length} orders</p>
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

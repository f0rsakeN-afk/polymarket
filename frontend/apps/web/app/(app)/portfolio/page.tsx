"use client"

import { useCallback } from "react"
import { sileo } from "sileo"
import { useQueryClient } from "@tanstack/react-query"
import { usePositions } from "@/hooks/api/use-positions"
import { useOrders } from "@/hooks/api/use-orders"
import { useWallet } from "@/hooks/api/use-wallet"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import { SplitMergeForm } from "@/components/liquidity/split-merge-form"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@workspace/ui/components/table"
import { Spinner } from "@workspace/ui/components/spinner"
import { Lock, ArrowUpRight, ChevronDown } from "lucide-react"
import { cn } from "@workspace/ui/lib/utils"
import type { Position, Order } from "@/hooks/api/types/order"

function n(v: string | number | null | undefined, fallback = 0): number {
  if (v == null) return fallback
  const x = Number(v)
  return isNaN(x) ? fallback : x
}

function formatPnL(v: number) {
  const sign = v >= 0 ? "+" : ""
  return `${sign}$${v.toFixed(2)}`
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

function Greeting() {
  const h = new Date().getHours()
  if (h < 12) return "Good morning"
  if (h < 17) return "Good afternoon"
  return "Good evening"
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  if (outcome === "yes") {
    return <Badge className="bg-emerald-600 hover:bg-emerald-700 text-white capitalize shrink-0">yes</Badge>
  }
  if (outcome === "no") {
    return <Badge variant="destructive" className="capitalize shrink-0">no</Badge>
  }
  // multi-outcome markets — show as secondary badge
  return <Badge variant="secondary" className="capitalize shrink-0 truncate max-w-[80px]" title={outcome}>{outcome}</Badge>
}

function SideBadge({ side }: { side: string }) {
  if (side === "buy") {
    return <Badge className="bg-emerald-600 hover:bg-emerald-700 text-white capitalize">buy</Badge>
  }
  return <Badge variant="destructive" className="capitalize">sell</Badge>
}

// ── Wallet Hero ────────────────────────────────────────────────────────────────

function WalletHero({ wallet, username, positions }: {
  wallet: NonNullable<ReturnType<typeof useWallet>["data"]>
  username: string
  positions: Position[]
}) {
  const balance = n(wallet.balance)
  const available = Math.max(0, n(wallet.available_balance))
  const locked = n(wallet.locked_balance)
  const totalUnrealized = positions.reduce((s, p) => s + n(p.unrealized_pnl), 0)
  const totalRealized = positions.reduce((s, p) => s + n(p.realized_pnl), 0)
  const totalPnL = totalUnrealized + totalRealized

  return (
    <Card>
      <CardContent className="p-6">
        <p className="text-sm text-muted-foreground">
          <Greeting />, <span className="font-medium text-foreground">{username}</span>
        </p>

        <p className="text-5xl font-bold tabular-nums tracking-tight mt-3">${balance.toFixed(2)}</p>
        <p className="text-xs text-muted-foreground mt-1">Total portfolio value</p>

        <div className="flex gap-3 mt-5">
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-accent border border-border">
            <ArrowUpRight className="size-3.5 text-emerald-600 dark:text-emerald-400" />
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">Available</p>
              <p className="text-sm font-semibold tabular-nums text-foreground">${available.toFixed(2)}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-accent border border-border">
            <Lock className="size-3.5 text-amber-600 dark:text-amber-400" />
            <div>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">Locked</p>
              <p className="text-sm font-semibold tabular-nums text-foreground">${locked.toFixed(2)}</p>
            </div>
          </div>
        </div>

        <div className="border-t border-border my-5" />

        <div className="grid grid-cols-3 gap-3">
          <div>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium mb-1">Unrealized</p>
            <p className={cn("text-lg font-bold tabular-nums tracking-tight", totalUnrealized >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive")}>
              {formatPnL(totalUnrealized)}
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">{positions.length} positions</p>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium mb-1">Realized</p>
            <p className={cn("text-lg font-bold tabular-nums tracking-tight", totalRealized >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive")}>
              {formatPnL(totalRealized)}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium mb-1">Total P&L</p>
            <p className={cn("text-lg font-bold tabular-nums tracking-tight", totalPnL >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive")}>
              {formatPnL(totalPnL)}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Positions ─────────────────────────────────────────────────────────────────

function PositionsSection({ positions, isLoading, hasMore, fetchNextPage }: {
  positions: Position[]
  isLoading: boolean
  hasMore?: boolean
  fetchNextPage?: () => void
}) {
  if (isLoading && positions.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Open Positions</CardTitle></CardHeader>
        <CardContent className="flex h-48 items-center justify-center"><Spinner className="size-5" /></CardContent>
      </Card>
    )
  }

  if (positions.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Open Positions</CardTitle></CardHeader>
        <CardContent className="flex h-24 items-center justify-center text-sm text-muted-foreground">No open positions</CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader><CardTitle className="text-base">Open Positions</CardTitle></CardHeader>
        <div className="divide-y overflow-auto" style={{ maxHeight: "400px", minHeight: "200px" }}>
            {positions.map((pos) => {
              const unrealized = n(pos.unrealized_pnl)
              const isUp = unrealized >= 0
              return (
                <div key={pos.id} className="flex items-center gap-4 px-6 py-4 hover:bg-accent/40 transition-colors">
                  <div className="shrink-0">
                    <OutcomeBadge outcome={pos.outcome} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{pos.market_question}</p>
                    <p className="text-xs text-muted-foreground">
                      {Number(pos.shares_held).toFixed(0)} shares @ ${n(pos.average_price).toFixed(3)}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className={cn("text-sm font-semibold tabular-nums", isUp ? "text-emerald-600 dark:text-emerald-400" : "text-destructive")}>
                      {formatPnL(unrealized)}
                    </p>
                    <p className="text-xs text-muted-foreground">unrealized</p>
                  </div>
                </div>
              )
            })}
          </div>
      </Card>
      {hasMore && (
        <div className="flex justify-center">
          <Button variant="outline" size="sm" onClick={() => fetchNextPage?.()} disabled={isLoading} className="gap-2">
            {isLoading ? <Spinner className="size-3" /> : <ChevronDown className="size-3" />}
            Load more
          </Button>
        </div>
      )}
    </div>
  )
}

// ── Orders ────────────────────────────────────────────────────────────────────

function OrdersSection({ orders, isLoading, hasMore, fetchNextPage }: {
  orders: Order[]
  isLoading: boolean
  hasMore?: boolean
  fetchNextPage?: () => void
}) {
  if (isLoading && orders.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Recent Orders</CardTitle></CardHeader>
        <CardContent className="flex h-48 items-center justify-center"><Spinner className="size-5" /></CardContent>
      </Card>
    )
  }

  if (orders.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Recent Orders</CardTitle></CardHeader>
        <CardContent className="flex h-24 items-center justify-center text-sm text-muted-foreground">No orders yet</CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader><CardTitle className="text-base">Recent Orders</CardTitle></CardHeader>
        <div className="overflow-auto" style={{ maxHeight: "400px", minHeight: "200px" }}>
          <Table noWrapper className="w-full">
            <TableHeader className="sticky top-0 z-20 bg-muted">
              <TableRow className="hover:bg-transparent">
                <TableHead>Market</TableHead>
                <TableHead>Side</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.map((order) => (
                <TableRow key={order.id} className="hover:bg-accent/30 transition-colors">
                  <TableCell className="font-medium max-w-xs truncate">{order.market_question}</TableCell>
                  <TableCell><SideBadge side={order.side} /></TableCell>
                  <TableCell className="capitalize text-muted-foreground text-sm">
                    {order.order_type.replace("_", " ")}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-sm">${n(order.price).toFixed(3)}</TableCell>
                  <TableCell className="text-right tabular-nums text-sm">{n(order.amount).toFixed(0)}</TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="capitalize text-xs">{order.status}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">{formatTime(order.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>
      {hasMore && (
        <div className="flex justify-center">
          <Button variant="outline" size="sm" onClick={() => fetchNextPage?.()} disabled={isLoading} className="gap-2">
            {isLoading ? <Spinner className="size-3" /> : <ChevronDown className="size-3" />}
            Load more
          </Button>
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  const {
    data: positionsData,
    isLoading: positionsLoading,
    hasNextPage: positionsHasMore,
    fetchNextPage: fetchPositionsNextPage,
  } = usePositions()
  const {
    data: ordersData,
    isLoading: ordersLoading,
    hasNextPage: ordersHasMore,
    fetchNextPage: fetchOrdersNextPage,
  } = useOrders()
  const { data: wallet, isLoading: walletLoading } = useWallet()

  const handleWsMessage = useCallback(
    (msg: unknown) => {
      const message = msg as { type?: string; title?: string; body?: string; outcome?: string; condition?: string; trigger_price?: number }
      if (message.type === "notification") {
        sileo.info({ title: message.title ?? "Notification", description: message.body ?? "" })
        qc.invalidateQueries({ queryKey: ["notifications"] })
        return
      }
      if (message.type === "alert:triggered") {
        sileo.success({
          title: "Price Alert!",
          description: `${(message.outcome ?? "price").toUpperCase()} ${message.condition} $${message.trigger_price?.toFixed(2)}`,
        })
        return
      }
      if (message.type === "order:fill" || message.type === "position:update") {
        qc.invalidateQueries({ queryKey: ["positions"] })
        qc.invalidateQueries({ queryKey: ["orders"] })
      }
    },
    [qc]
  )

  useUserSocket({ userId: user?.id ?? "", onMessage: handleWsMessage, enabled: !!user?.id })

  const positions = positionsData?.positions ?? []
  const orders = ordersData?.orders ?? []

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      {/* Top: Wallet (3/4) + Liquidity (1/4) */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-3">
          {walletLoading ? (
            <Card><CardContent className="flex h-56 items-center justify-center"><Spinner className="size-5" /></CardContent></Card>
          ) : wallet ? (
            <WalletHero wallet={wallet} username={user?.username ?? "Trader"} positions={positions} />
          ) : null}
        </div>
        <div className="lg:col-span-1">
          <Card>
            <CardHeader className="pb-0">
              <CardTitle className="text-sm">Provide Liquidity</CardTitle>
            </CardHeader>
            <CardContent className="p-4">
              <SplitMergeForm />
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Below: full-width stacked */}
      <PositionsSection
        positions={positions}
        isLoading={positionsLoading}
        hasMore={positionsHasMore}
        fetchNextPage={fetchPositionsNextPage}
      />

      <OrdersSection
        orders={orders}
        isLoading={ordersLoading}
        hasMore={ordersHasMore}
        fetchNextPage={fetchOrdersNextPage}
      />
    </div>
  )
}

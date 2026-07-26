"use client"

import { useMemo } from "react"
import { Spinner } from "@workspace/ui/components/spinner"
import { PositionsList } from "@/components/orders/positions-list"
import { OrdersList } from "@/components/orders/orders-list"
import { LPDashboard } from "@/components/liquidity/lp-dashboard"
import { usePositions } from "@/hooks/use-positions"
import { useOrders } from "@/hooks/use-orders"
import { useWallet } from "@/hooks/use-wallet"
import Link from "next/link"
import { Button } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"
import type { Position } from "@/lib/types/api"

function formatUSD(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

function PnLBadge({ value }: { value: number }) {
  const isPositive = value >= 0
  return (
    <span className={cn("text-sm font-semibold", isPositive ? "text-green-500" : "text-red-500")}>
      {isPositive ? "+" : ""}{formatUSD(value)}
    </span>
  )
}

function PortfolioSummary({
  wallet,
  positions,
}: {
  wallet: { balance: number; locked: number; available: number }
  positions: Position[]
}) {
  const totalUnrealized = useMemo(
    () => positions.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0),
    [positions]
  )
  const totalRealized = useMemo(
    () => positions.reduce((sum, p) => sum + (p.realized_pnl ?? 0), 0),
    [positions]
  )
  const portfolioValue = wallet.balance + totalUnrealized

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-medium">Portfolio</h3>
        <Link href="/wallet">
          <Button variant="ghost" size="sm" className="h-5 text-[10px]">Manage</Button>
        </Link>
      </div>

      {/* Hero row */}
      <div className="mb-4 flex items-end justify-between">
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-1">Total Value</div>
          <div className="text-2xl font-bold">{formatUSD(portfolioValue)}</div>
        </div>
        <div className="text-right">
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-1">Unrealized P&L</div>
          <PnLBadge value={totalUnrealized} />
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-border/50 my-3" />

      {/* Breakdown */}
      <div className="grid grid-cols-4 gap-3">
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-1">Balance</div>
          <div className="text-sm font-semibold">{formatUSD(wallet.balance)}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-1">Available</div>
          <div className="text-sm font-semibold text-green-500">{formatUSD(wallet.available)}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-1">Locked</div>
          <div className="text-sm font-semibold text-yellow-500">{formatUSD(wallet.locked)}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wider mb-1">Realized P&L</div>
          <PnLBadge value={totalRealized} />
        </div>
      </div>
    </div>
  )
}

export default function PortfolioPage() {
  const { data: wallet, isLoading: walletLoading } = useWallet()
  const { data: positionsData, isLoading: positionsLoading, fetchNextPage: fetchPositionsNextPage, hasNextPage: positionsHasMore } = usePositions()
  const { data: ordersData, isLoading: ordersLoading, fetchNextPage: fetchOrdersNextPage, hasNextPage: ordersHasMore } = useOrders()

  const positions = positionsData?.positions ?? []

  if (walletLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner className="size-5" />
      </div>
    )
  }

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Portfolio</h1>
        <p className="mt-1 text-muted-foreground">Your positions, orders, and wallet</p>
      </div>

      {wallet && (
        <div className="mb-6">
          <PortfolioSummary wallet={wallet} positions={positions} />
        </div>
      )}

      <div className="mb-6">
        <div className="mb-3">
          <h2 className="text-sm font-semibold">Liquidity Positions</h2>
        </div>
        <LPDashboard />
      </div>

      <div className="space-y-6">
        <PositionsList
          positions={positions}
          loading={positionsLoading}
          hasMore={positionsHasMore ?? false}
          onLoadMore={fetchPositionsNextPage}
        />
        <OrdersList
          orders={ordersData?.orders ?? []}
          loading={ordersLoading}
          hasMore={ordersHasMore ?? false}
          onLoadMore={fetchOrdersNextPage}
        />
      </div>
    </div>
  )
}

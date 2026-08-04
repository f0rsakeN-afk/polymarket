"use client"

import { useCallback } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { usePositions } from "@/hooks/api/use-positions"
import { useOrders } from "@/hooks/api/use-orders"
import { useWallet } from "@/hooks/api/use-wallet"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import { Card, CardContent } from "@workspace/ui/components/card"
import { Badge } from "@workspace/ui/components/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@workspace/ui/components/table"
import { Spinner } from "@workspace/ui/components/spinner"
function formatPnL(pnl: number) {
  const sign = pnl >= 0 ? "+" : ""
  return `${sign}$${pnl.toFixed(2)}`
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

export default function PortfolioPage() {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  const { data: positions, isLoading: positionsLoading } = usePositions()
  const { data: orders, isLoading: ordersLoading } = useOrders()
  const { data: wallet, isLoading: walletLoading } = useWallet()

  const handleWsMessage = useCallback(
    (msg: unknown) => {
      const message = msg as { type?: string; notification?: { type?: string } }
      if (message.type === "position:update" || message.notification?.type === "order_filled") {
        qc.invalidateQueries({ queryKey: ["positions"] })
        qc.invalidateQueries({ queryKey: ["orders"] })
      }
    },
    [qc]
  )

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: !!user?.id,
  })

  const recentOrders = orders?.orders.slice(0, 10) ?? []

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-8">
      <h1 className="text-2xl font-bold">Portfolio</h1>

      {/* Wallet Summary */}
      <section>
        <h2 className="text-lg font-semibold mb-4">Wallet</h2>
        {walletLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner className="size-5" />
          </div>
        ) : wallet ? (
          <div className="grid grid-cols-3 gap-4">
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">Available</p>
                <p className="text-2xl font-bold">${wallet.available.toFixed(2)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">Locked</p>
                <p className="text-2xl font-bold">${wallet.locked.toFixed(2)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-sm text-muted-foreground">Balance</p>
                <p className="text-2xl font-bold">${wallet.balance.toFixed(2)}</p>
              </CardContent>
            </Card>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Not connected</p>
        )}
      </section>

      {/* Positions P&L Summary */}
      {positions && positions.positions.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-4">Positions</h2>
          {(() => {
            const totalUnrealized = positions.positions.reduce((s, p) => s + p.unrealized_pnl, 0)
            const totalRealized = positions.positions.reduce((s, p) => s + p.realized_pnl, 0)
            const totalPnL = totalUnrealized + totalRealized
            const pnlColor = (v: number) => (v >= 0 ? "text-green-500" : "text-red-500")
            return (
              <Card className="mb-4">
                <CardContent className="flex justify-around py-4">
                  <div className="text-center">
                    <p className="text-sm text-muted-foreground">Unrealized P&L</p>
                    <p className={`text-xl font-bold tabular-nums ${pnlColor(totalUnrealized)}`}>{formatPnL(totalUnrealized)}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-sm text-muted-foreground">Realized P&L</p>
                    <p className={`text-xl font-bold tabular-nums ${pnlColor(totalRealized)}`}>{formatPnL(totalRealized)}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-sm text-muted-foreground">Total P&L</p>
                    <p className={`text-xl font-bold tabular-nums ${pnlColor(totalPnL)}`}>{formatPnL(totalPnL)}</p>
                  </div>
                </CardContent>
              </Card>
            )
          })()}
        </section>
      )}

      {/* Positions */}
      <section>
        <h2 className="text-lg font-semibold mb-4">Positions</h2>
        {positionsLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner className="size-5" />
          </div>
        ) : positions?.positions.length === 0 ? (
          <Card>
            <CardContent className="flex h-24 items-center justify-center text-sm text-muted-foreground">
              No positions yet
            </CardContent>
          </Card>
        ) : (
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Market</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead className="text-right">Shares</TableHead>
                  <TableHead className="text-right">Avg Price</TableHead>
                  <TableHead className="text-right">Unrealized P&L</TableHead>
                  <TableHead className="text-right">Realized P&L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions?.positions.map((pos) => (
                  <TableRow key={pos.id}>
                    <TableCell className="font-medium max-w-xs truncate">{pos.market_question}</TableCell>
                    <TableCell>
                      <Badge variant={pos.outcome === "yes" ? "default" : "destructive"} className="capitalize">
                        {pos.outcome}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{pos.shares_held.toFixed(0)}</TableCell>
                    <TableCell className="text-right tabular-nums">${pos.average_price.toFixed(3)}</TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${
                        pos.unrealized_pnl >= 0 ? "text-green-500" : "text-red-500"
                      }`}
                    >
                      {formatPnL(pos.unrealized_pnl)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${
                        pos.realized_pnl >= 0 ? "text-green-500" : "text-red-500"
                      }`}
                    >
                      {formatPnL(pos.realized_pnl)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </section>

      {/* Recent Orders */}
      <section>
        <h2 className="text-lg font-semibold mb-4">Recent Orders</h2>
        {ordersLoading ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner className="size-5" />
          </div>
        ) : recentOrders.length === 0 ? (
          <Card>
            <CardContent className="flex h-24 items-center justify-center text-sm text-muted-foreground">
              No orders yet
            </CardContent>
          </Card>
        ) : (
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
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
                {recentOrders.map((order) => (
                  <TableRow key={order.id}>
                    <TableCell className="font-medium max-w-xs truncate">{order.market_question}</TableCell>
                    <TableCell>
                      <Badge
                        variant={order.side === "buy" ? "default" : "destructive"}
                        className="capitalize"
                      >
                        {order.side}
                      </Badge>
                    </TableCell>
                    <TableCell className="capitalize">{order.order_type.replace("_", " ")}</TableCell>
                    <TableCell className="text-right tabular-nums">${order.price.toFixed(3)}</TableCell>
                    <TableCell className="text-right tabular-nums">{order.amount.toFixed(0)}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          order.status === "filled"
                            ? "default"
                            : order.status === "cancelled"
                            ? "destructive"
                            : "secondary"
                        }
                        className="capitalize"
                      >
                        {order.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {formatTime(order.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </section>
    </div>
  )
}

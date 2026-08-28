"use client"

import { useCallback } from "react"
import { Spinner } from "@workspace/ui/components/spinner"
import { Button } from "@workspace/ui/components/button"
import { useLPAnalytics } from "@/hooks/api/use-liquidity"

function formatCurrency(n: string | number) {
  return Number(n).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPct(n: string | number) {
  return `${Number(n) >= 0 ? "+" : ""}${Number(n).toFixed(2)}%`
}

export function LPDashboard() {
  const { data, isLoading, error, refetch } = useLPAnalytics()
  const handleRetry = useCallback((_e: unknown) => { void refetch() }, [refetch])

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Spinner className="size-5" />
      </div>
    )
  }

  if (error) {
    return <div className="py-12 text-center">
      <p className="text-destructive mb-3">Failed to load liquidity positions</p>
      <Button variant="outline" size="sm" onClick={handleRetry}>Retry</Button>
    </div>
  }

  if (!data || data.positions.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-card p-6 text-center text-xs text-muted-foreground">
        No liquidity positions yet. Add liquidity to a market to start earning.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg border border-border bg-card p-4 text-center">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Total Value</div>
          <div className="text-lg font-bold">{formatCurrency(data.total_value)}</div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4 text-center">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Total Deposited</div>
          <div className="text-lg font-bold">{formatCurrency(data.total_deposited)}</div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4 text-center">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">PnL</div>
          <div className={`text-lg font-bold ${Number(data.total_pnl) >= 0 ? "text-green-500" : "text-red-500"}`}>
            {formatCurrency(data.total_pnl)}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-2 px-2 text-muted-foreground font-medium">Market</th>
              <th className="text-right py-2 px-2 text-muted-foreground font-medium">Deposited</th>
              <th className="text-right py-2 px-2 text-muted-foreground font-medium">Value</th>
              <th className="text-right py-2 px-2 text-muted-foreground font-medium">Share</th>
              <th className="text-right py-2 px-2 text-muted-foreground font-medium">Fees</th>
              <th className="text-right py-2 px-2 text-muted-foreground font-medium">PnL</th>
              <th className="text-right py-2 px-2 text-muted-foreground font-medium">Est. APR</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map((pos) => (
              <tr key={pos.market_id} className="border-b border-border/50 hover:bg-muted/30">
                <td className="py-2 px-2">
                  <a href={`/markets/${pos.market_slug}`} className="text-primary hover:underline font-medium truncate block max-w-[200px]">
                    {pos.market_question}
                  </a>
                </td>
                <td className="text-right py-2 px-2 font-medium">{formatCurrency(pos.collateral_deposited)}</td>
                <td className="text-right py-2 px-2 font-medium">{formatCurrency(pos.position_value)}</td>
                <td className="text-right py-2 px-2 text-muted-foreground">{Number(pos.share_pct).toFixed(2)}%</td>
                <td className="text-right py-2 px-2 text-green-500">{formatCurrency(pos.fees_earned)}</td>
                <td className={`text-right py-2 px-2 font-medium ${Number(pos.net_pnl) >= 0 ? "text-green-500" : "text-red-500"}`}>
                  {formatCurrency(pos.net_pnl)}
                </td>
                <td className={`text-right py-2 px-2 font-medium ${Number(pos.estimated_apr) >= 0 ? "text-green-500" : "text-red-500"}`}>
                  {formatPct(pos.estimated_apr)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

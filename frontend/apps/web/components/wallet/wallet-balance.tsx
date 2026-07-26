"use client"

import { Spinner } from "@workspace/ui/components/spinner"
import type { Wallet } from "@/lib/types/api"

function formatUSD(n: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(n)
}

interface WalletBalanceProps {
  wallet: Wallet | null
  loading?: boolean
}

function WalletBalance({ wallet, loading }: WalletBalanceProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 text-xs/relaxed">
      <h3 className="mb-3 text-sm font-medium">Wallet</h3>
      {loading ? (
        <Spinner className="size-5" />
      ) : wallet ? (
        <div className="space-y-2">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Balance</span>
            <span className="font-medium">{formatUSD(wallet.balance)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Locked</span>
            <span className="font-medium text-muted-foreground">
              {formatUSD(wallet.locked)}
            </span>
          </div>
          <div className="flex justify-between border-t border-border pt-2">
            <span className="text-muted-foreground">Available</span>
            <span className="font-bold">{formatUSD(wallet.available)}</span>
          </div>
        </div>
      ) : (
        <div className="text-muted-foreground">Not authenticated</div>
      )}
    </div>
  )
}

export { WalletBalance }

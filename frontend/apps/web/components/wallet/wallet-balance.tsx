"use client"

import { memo } from "react"
import { Spinner } from "@workspace/ui/components/spinner"
import type { Wallet } from "@/hooks/api/types/wallet"

function formatUSD(n: string | number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Number(n))
}

interface WalletBalanceProps {
  wallet: Wallet | null
  loading?: boolean
  /**
   * Why there is no wallet to show.
   *
   * This distinction is the whole point of the component. A null wallet used to
   * render "Not authenticated" unconditionally, which is a guess: `data` is null
   * for a 401, but also for a 404, a 500, or a dropped connection. So any failure
   * told a signed-in user they were not signed in - and told them to go log in,
   * which would not have helped. That is worse than showing nothing, because it
   * confidently misdirects.
   *
   * So the caller states which it is, and unknown failures say "could not load"
   * rather than inventing a reason.
   */
  reason?: "unauthenticated" | "error"
}

const WalletBalance = memo(function WalletBalance({
  wallet,
  loading,
  reason,
}: WalletBalanceProps) {
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
              {formatUSD(wallet.locked_balance)}
            </span>
          </div>
          <div className="flex justify-between border-t border-border pt-2">
            <span className="text-muted-foreground">Available</span>
            <span className="font-bold">
              {formatUSD(wallet.available_balance)}
            </span>
          </div>
        </div>
      ) : reason === "error" ? (
        // Say what is true: we do not know. Anything else here is a guess that
        // sends the user off to do something that will not fix it.
        <div className="text-muted-foreground">
          Could not load your wallet. Try again in a moment.
        </div>
      ) : (
        <div className="text-muted-foreground">Not authenticated</div>
      )}
    </div>
  )
})

export { WalletBalance }

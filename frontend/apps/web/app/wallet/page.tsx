"use client"

import { Button } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import { AmountDialog } from "@/components/shared/amount-dialog"
import { useWallet, useDeposit, useWithdraw } from "@/hooks/use-wallet"

function formatUSD(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n)
}

function WalletCard({ wallet }: { wallet: { balance: number; locked: number; available: number } }) {
  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <h2 className="text-sm font-medium text-muted-foreground mb-4">Wallet Balance</h2>
      <div className="space-y-3">
        <div className="flex justify-between items-baseline">
          <span className="text-muted-foreground text-xs">Total Balance</span>
          <span className="text-2xl font-bold">{formatUSD(wallet.balance)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground text-xs">Available</span>
          <span className="text-sm font-medium text-green-500">{formatUSD(wallet.available)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground text-xs">Locked</span>
          <span className="text-sm font-medium text-yellow-500">{formatUSD(wallet.locked)}</span>
        </div>
      </div>
    </div>
  )
}

export default function WalletPage() {
  const { data: wallet, isLoading } = useWallet()
  const depositMutation = useDeposit()
  const withdrawMutation = useWithdraw()

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner className="size-5" />
      </div>
    )
  }

  if (!wallet) {
    return (
      <div className="container mx-auto max-w-2xl px-4 py-8 text-center text-muted-foreground">
        Unable to load wallet
      </div>
    )
  }

  return (
    <div className="container mx-auto max-w-2xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Wallet</h1>
        <p className="mt-1 text-muted-foreground">Manage your funds</p>
      </div>

      <div className="mb-6">
        <WalletCard wallet={wallet} />
      </div>

      <div className="flex gap-3">
        <AmountDialog
          title="Deposit"
          description="Enter the amount you want to deposit into your wallet."
          trigger={<Button variant="outline" size="sm">Deposit</Button>}
          onConfirm={async (amount) => { await depositMutation.mutateAsync(amount) }}
        />
        <AmountDialog
          title="Withdraw"
          description="Enter the amount you want to withdraw from your wallet."
          trigger={<Button variant="outline" size="sm">Withdraw</Button>}
          onConfirm={async (amount) => { await withdrawMutation.mutateAsync(amount) }}
        />
      </div>
    </div>
  )
}

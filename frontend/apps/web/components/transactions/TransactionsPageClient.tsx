"use client"

import { useCallback } from "react"
import { useTransactions } from "@/hooks/api/use-wallet"
import { Spinner } from "@workspace/ui/components/spinner"
import { Button } from "@workspace/ui/components/button"

function formatUSD(n: string | number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Number(n))
}

function formatDate(iso: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso))
}

const typeLabels: Record<string, string> = {
  deposit: "Deposit",
  withdrawal: "Withdrawal",
  trade: "Trade",
  refund: "Refund",
}

const statusColors: Record<string, string> = {
  completed: "text-green-700",
  pending: "text-yellow-700",
  failed: "text-red-700",
}

export function TransactionsPageClient() {
  const { data, isLoading, fetchNextPage, hasMore, isFetchingNextPage } = useTransactions() as ReturnType<typeof useTransactions> & { hasMore?: boolean }

  const loadMore = useCallback(() => { void fetchNextPage() }, [fetchNextPage])

  if (isLoading) {
    return (
      <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Transactions</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">Your transaction history</p>
        </div>
        <div className="flex h-48 items-center justify-center">
          <Spinner className="size-6" />
        </div>
      </div>
    )
  }

  const transactions = data?.transactions ?? []

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Transactions</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">{transactions.length} transactions</p>
      </div>

      {transactions.length === 0 ? (
        <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-xl border border-border bg-card text-center">
          <p className="text-sm font-medium">No transactions yet</p>
          <p className="max-w-52 text-xs text-muted-foreground">Deposits, withdrawals and trades will appear here.</p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card p-4">
        <ul className="divide-y divide-border">
          {transactions.map((tx) => (
            <li key={tx.id} className="flex items-center justify-between py-3 text-sm">
              <div>
                <p className="font-medium">{typeLabels[tx.type] ?? tx.type}</p>
                <p className="text-xs text-muted-foreground">{formatDate(tx.created_at)}</p>
              </div>
              <div className="text-right">
                <p className="font-medium">
                  {tx.type === "deposit" || tx.type === "refund" ? "+" : "-"}
                  {formatUSD(tx.amount)}
                </p>
                <p className={`text-xs font-medium capitalize ${statusColors[tx.status] ?? ""}`}>{tx.status}</p>
              </div>
            </li>
          ))}
        </ul>
        </div>
      )}

      {hasMore && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            size="sm"
            onClick={loadMore}
            disabled={isFetchingNextPage}
          >
            Load more
          </Button>
        </div>
      )}
    </div>
  )
}

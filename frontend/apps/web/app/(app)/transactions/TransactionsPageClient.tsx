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
  completed: "text-green-500",
  pending: "text-yellow-500",
  failed: "text-red-500",
}

export function TransactionsPageClient() {
  const { data, isLoading, fetchNextPage, hasMore, isFetchingNextPage } = useTransactions() as ReturnType<typeof useTransactions> & { hasMore?: boolean }

  const loadMore = useCallback((_e: unknown) => { void fetchNextPage() }, [fetchNextPage])

  if (isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Spinner className="size-6" />
      </div>
    )
  }

  const transactions = data?.transactions ?? []

  return (
    <div className="p-8 max-w-lg space-y-6">
      <h1 className="text-2xl font-semibold">Transactions</h1>

      {transactions.length === 0 ? (
        <p className="text-muted-foreground">No transactions yet.</p>
      ) : (
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
                <p className={`text-xs ${statusColors[tx.status] ?? ""}`}>{tx.status}</p>
              </div>
            </li>
          ))}
        </ul>
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

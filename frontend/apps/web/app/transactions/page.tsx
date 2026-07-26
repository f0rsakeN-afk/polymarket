"use client"

import { useEffect, useRef } from "react"
import { Spinner } from "@workspace/ui/components/spinner"
import { useTransactions } from "@/hooks/use-wallet"
import type { Transaction } from "@/lib/types/api"

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatUSD(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Math.abs(n))
}

function TransactionRow({ tx }: { tx: Transaction }) {
  const isPositive = tx.type === "deposit" || tx.type === "refund"
  const colorMap: Record<string, string> = {
    deposit: "text-green-500",
    withdrawal: "text-red-500",
    trade: "text-muted-foreground",
    refund: "text-blue-500",
  }

  return (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-0">
      <div className="flex items-center gap-3">
        <span
          className={`text-[10px] font-semibold uppercase ${colorMap[tx.type] ?? "text-muted-foreground"}`}
        >
          {tx.type}
        </span>
        <span className="text-xs text-muted-foreground">{formatDate(tx.created_at)}</span>
      </div>
      <div className="text-right">
        <span className={`text-xs font-medium ${isPositive ? "text-green-500" : "text-red-500"}`}>
          {isPositive ? "+" : "-"}{formatUSD(tx.amount)}
        </span>
        <div className="text-muted-foreground text-[10px] capitalize">{tx.status}</div>
      </div>
    </div>
  )
}

function TransactionsList({
  transactions,
  loading,
  hasMore,
  onLoadMore,
}: {
  transactions: Transaction[]
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
}) {
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasMore && !loading) {
          onLoadMore()
        }
      },
      { threshold: 0.1 }
    )
    if (sentinelRef.current) observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [hasMore, loading, onLoadMore])

  return (
    <div className="rounded-xl border border-border bg-card p-4 text-xs/relaxed">
      <h3 className="mb-3 text-sm font-medium">Transactions</h3>
      {loading && transactions.length === 0 ? (
        <div className="py-6 text-center text-muted-foreground">
          <Spinner className="size-5" />
        </div>
      ) : transactions.length === 0 ? (
        <div className="py-6 text-center text-muted-foreground">No transactions yet</div>
      ) : (
        <>
          <div>
            {transactions.map((tx) => (
              <TransactionRow key={tx.id} tx={tx} />
            ))}
          </div>
          <div ref={sentinelRef} className="flex justify-center py-3">
            {loading && <Spinner className="size-5" />}
            {!hasMore && transactions.length > 0 && (
              <span className="text-muted-foreground">No more transactions</span>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function TransactionsPage() {
  const { data, isLoading, fetchNextPage, hasNextPage } = useTransactions()

  return (
    <div className="container mx-auto max-w-2xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Transactions</h1>
        <p className="mt-1 text-muted-foreground">Your wallet transaction history</p>
      </div>
      <TransactionsList
        transactions={data?.transactions ?? []}
        loading={isLoading}
        hasMore={hasNextPage ?? false}
        onLoadMore={fetchNextPage}
      />
    </div>
  )
}

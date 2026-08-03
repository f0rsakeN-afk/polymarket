"use client"

import { TradeFeed } from "@/components/trades/trade-feed"
import { useGlobalTrades } from "@/hooks/use-markets"

export function TradesPageClient() {
  const { data, isLoading, fetchNextPage, hasNextPage } = useGlobalTrades()

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Trade Feed</h1>
        <p className="mt-1 text-muted-foreground">Recent trades across all markets</p>
      </div>
      <TradeFeed trades={data?.trades ?? []} loading={isLoading} />
      {hasNextPage && (
        <div className="mt-4 flex justify-center">
          <button
            onClick={() => { fetchNextPage() }}
            className="rounded-md border border-border px-4 py-2 text-xs hover:bg-muted"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  )
}

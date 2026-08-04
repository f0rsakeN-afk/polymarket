"use client"

import { useState, useCallback } from "react"
import { TradeFeed } from "@/components/trades/trade-feed"
import { useGlobalTrades } from "@/hooks/use-markets"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import type { Trade } from "@/lib/types/api"

export function TradesPageClient() {
  const { data, isLoading, fetchNextPage, hasNextPage } = useGlobalTrades()
  const { data: user } = useCurrentUser()
  const [realtimeTrades, setRealtimeTrades] = useState<Trade[]>([])

  const handleWsMessage = useCallback((msg: unknown) => {
    const message = msg as { type?: string; trade?: Trade }
    if (message.type === "trade:new" && message.trade) {
      setRealtimeTrades((prev) => [message.trade!, ...prev])
    }
  }, [])

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: !!user?.id,
  })

  const mergedTrades = [...realtimeTrades, ...(data?.trades ?? [])]

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Trade Feed</h1>
        <p className="mt-1 text-muted-foreground">Recent trades across all markets</p>
      </div>
      <TradeFeed trades={mergedTrades} loading={isLoading} />
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

"use client"

import { useState, useCallback, useRef } from "react"
import { TradeFeed } from "@/components/trades/trade-feed"
import { useSimpleGlobalTrades } from "@/hooks/api/use-trades"
import { useCurrentUser } from "@/hooks/use-auth"
import { useUserSocket } from "@/hooks/use-user-socket"
import type { Trade } from "@/hooks/api/types/market"

const MAX_TRADES = 100

export function TradesPageClient() {
  const { data, isLoading } = useSimpleGlobalTrades({ page_size: MAX_TRADES })
  const { data: user } = useCurrentUser()
  const listRef = useRef<HTMLDivElement>(null)

  const [wsTrades, setWsTrades] = useState<Trade[]>([])
  const [pendingCount, setPendingCount] = useState(0)

  const handleWsMessage = useCallback((msg: unknown) => {
    const message = msg as { type?: string; trade?: Trade }
    if (message.type !== "trade:new" || !message.trade) return
    const trade = message.trade

    // Deduplicate against REST trades
    if (data?.trades?.some((t) => t.id === trade.id)) return

    setWsTrades((prev) => {
      if (prev.some((t) => t.id === trade.id)) return prev
      if (prev.length >= MAX_TRADES) {
        setPendingCount((c) => c + 1)
        return prev
      }
      return [trade, ...prev]
    })
  }, [data?.trades])

  useUserSocket({
    userId: user?.id ?? "",
    onMessage: handleWsMessage,
    enabled: !!user?.id,
  })

  const mergedTrades = [...wsTrades, ...(data?.trades ?? [])].slice(0, MAX_TRADES)

  const scrollToTop = useCallback(() => {
    listRef.current?.scrollTo({ top: 0, behavior: "smooth" })
    setWsTrades([])
    setPendingCount(0)
  }, [])

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Trade Feed</h1>
        <p className="mt-1 text-muted-foreground">Recent trades across all markets</p>
      </div>

      {pendingCount > 0 && (
        <button
          onClick={scrollToTop}
          className="mb-3 flex items-center gap-2 rounded-full bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
        >
          <span className="relative flex size-2">
            <span className="absolute inline-flex h-full w-full rounded-full bg-primary-foreground opacity-75 animate-ping" />
            <span className="relative flex size-2 rounded-full bg-primary-foreground" />
          </span>
          {pendingCount} new trade{pendingCount !== 1 ? "s" : ""}
        </button>
      )}

      <TradeFeed trades={mergedTrades} loading={isLoading} listRef={listRef} />
    </div>
  )
}

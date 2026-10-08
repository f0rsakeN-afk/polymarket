"use client"

import { useState, useCallback, useEffect, useRef } from "react"
import { TradeFeed } from "@/components/trades/trade-feed"
import { useSimpleGlobalTrades } from "@/hooks/api/use-trades"
import { useGlobalTradesSocket } from "@/hooks/use-global-trades-socket"
import type { Trade } from "@/hooks/api/types/market"
import { toTrade, type GlobalTradeFrame } from "@/lib/global-trade-frame"

const MAX_TRADES = 100

export function TradesPageClient() {
  const { data, isLoading } = useSimpleGlobalTrades({ page_size: MAX_TRADES })
  const listRef = useRef<HTMLDivElement>(null)

  const [wsTrades, setWsTrades] = useState<Trade[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  /** Ids already seen, so a REST refetch can't produce a duplicate row. */
  const seenIdsRef = useRef<Set<string>>(new Set())

  // Seed from the REST page so a trade that arrived over WS before the fetch
  // resolved is recognised as a duplicate rather than shown twice.
  //
  // In an effect rather than during render: mutating a ref mid-render is a side
  // effect in the render phase, which breaks under StrictMode's double-invoke
  // (the second pass would re-seed over an already-updated set) and under
  // concurrent rendering, where a discarded render must not leave writes behind.
  // This also keeps the dedupe one-directional - REST rows are remembered, WS
  // rows are never forgotten - so the effect needs no cleanup or dependency on
  // the WS side.
  useEffect(() => {
    const restIds = data?.trades
    if (!restIds?.length) return
    const seen = seenIdsRef.current
    for (const t of restIds) seen.add(t.id)
  }, [data?.trades])

  const handleWsMessage = useCallback((msg: unknown) => {
    const frame = msg as GlobalTradeFrame
    if (frame.type !== "trade:new") return

    const trade = toTrade(frame)
    if (!trade) return

    // `seenIdsRef` is deliberately not a dependency: it is a ref precisely so
    // this callback stays referentially stable and never re-subscribes the
    // socket. Reading it is always current.
    if (seenIdsRef.current.has(trade.id)) return
    seenIdsRef.current.add(trade.id)

    setWsTrades((prev) => {
      if (prev.some((t) => t.id === trade.id)) return prev
      // Full: the row still belongs in the feed, it just waits behind the "N new
      // trades" button rather than pushing everything else out of view.
      if (prev.length >= MAX_TRADES) {
        setPendingCount((c) => c + 1)
        return prev
      }
      return [trade, ...prev]
    })
  }, [])

  const { status: wsStatus } = useGlobalTradesSocket({
    onMessage: handleWsMessage,
  })

  const mergedTrades = [...wsTrades, ...(data?.trades ?? [])].slice(0, MAX_TRADES)

  const scrollToTop = useCallback(() => {
    listRef.current?.scrollTo({ top: 0, behavior: "smooth" })
    setWsTrades([])
    setPendingCount(0)
  }, [])

  return (
    <div className="container mx-auto max-w-7xl px-4 py-6 sm:py-8">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 sm:mb-8">
        <div>
          <h1 className="text-xl font-bold tracking-tight sm:text-2xl">Trade Feed</h1>
          <p className="mt-1 text-sm text-muted-foreground sm:text-base">
            Recent trades across all markets
          </p>
        </div>
        {/* Same convention as the market page's indicator, so "is this feed live?"
            reads identically wherever the user meets it. */}
        <span className="flex items-center gap-1.5" role="status" aria-live="polite">
          <span
            aria-hidden="true"
            className={`size-2 rounded-full ${
              wsStatus === "connected"
                ? "bg-green-600 dark:bg-green-400"
                : wsStatus === "connecting"
                  ? "animate-pulse bg-yellow-600 dark:bg-yellow-400"
                  : "bg-muted-foreground/40"
            }`}
          />
          <span className="text-xs font-medium text-muted-foreground">
            {wsStatus === "connected" ? "Live" : wsStatus === "connecting" ? "Syncing" : "Offline"}
          </span>
        </span>
      </div>

      {pendingCount > 0 && (
        <button
          onClick={scrollToTop}
          className="mb-3 flex items-center gap-2 rounded-full bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <span className="flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary-foreground opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-primary-foreground" />
          </span>
          {pendingCount} new trade{pendingCount > 1 ? "s" : ""}
        </button>
      )}

      <TradeFeed trades={mergedTrades} loading={isLoading} listRef={listRef} />
    </div>
  )
}

"use client"

import { useState, useRef, useEffect, memo, useCallback } from "react"
import { useMarketSocket } from "@/hooks/use-market-socket"
import { cn } from "@workspace/ui/lib/utils"

interface TickerItem {
  id: string
  username: string
  side: "buy" | "sell"
  outcome: string
  price: number
  amount: number
  createdAt: number
}

function formatAmount(n: number) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return n.toFixed(0)
}

const TickerBar = memo(function TickerBar({ item }: { item: TickerItem }) {
  const isBuy = item.side === "buy"
  const colorClass = isBuy
    ? "bg-green-600/90 text-white"
    : "bg-red-600/90 text-white"

  return (
    <div
      className={cn(
        "flex items-center justify-between px-3 pr-8 py-1.5 rounded text-xs font-bold animate-in slide-in-from-bottom motion-reduce:animate-none",
        colorClass
      )}
    >
      <span className="truncate max-w-[35%]">{item.username}</span>
      <span className="truncate text-right">
        {isBuy ? "BUY" : "SELL"} · {item.outcome} · ${item.price.toFixed(2)} · ×{formatAmount(item.amount)}
      </span>
    </div>
  )
})

function LiveTradeTicker({ marketId }: { marketId: string }) {
  const [items, setItems] = useState<TickerItem[]>([])
  const idRef = useRef(0)
  const timeoutsRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; outcome?: string; side?: "buy" | "sell"; price?: string | number; amount?: string | number; username?: string }
    if (msg.type !== "trade:new" || !msg.outcome || !msg.side) return

    // The frame carries `price`/`amount` as strings (the REST feed's MoneyField
    // serialisation), so normalise explicitly. Truthiness was the wrong test
    // before: a fill at price 0 is a legitimate trade, not a missing value, and
    // `Number("0")` is finite where `if (!msg.price)` was false.
    const price = Number(msg.price)
    const amount = Number(msg.amount)
    if (!Number.isFinite(price) || !Number.isFinite(amount)) return

    const n = idRef.current++
    const id = `ticker-${n}`
    const item: TickerItem = {
      id,
      outcome: msg.outcome,
      side: msg.side,
      price,
      amount,
      username: msg.username ?? "Unknown",
      createdAt: Date.now(),
    }
    setItems((prev) => [item, ...prev].slice(0, 5))
    const timeoutId = setTimeout(() => {
      setItems((prev) => prev.filter((i) => i.id !== id))
      timeoutsRef.current.delete(timeoutId)
    }, 3200)
    timeoutsRef.current.add(timeoutId)
  }, [])

  useMarketSocket({
    marketId,
    onMessage: handleWSMessage,
    enabled: !!marketId,
  })

  useEffect(() => {
    const timeouts = timeoutsRef.current
    return () => {
      for (const t of timeouts) clearTimeout(t)
      timeouts.clear()
    }
  }, [])

  return (
    <div className="flex flex-col gap-1 overflow-hidden" aria-live="polite" role="status">
      {items.map((item) => (
        <TickerBar key={item.id} item={item} />
      ))}
    </div>
  )
}

export { LiveTradeTicker }

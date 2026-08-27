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
}

function formatAmount(n: number) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return n.toFixed(0)
}

const TickerBar = memo(function TickerBar({
  item,
  style,
}: {
  item: TickerItem
  style: React.CSSProperties
}) {
  const isBuy = item.side === "buy"
  const colorClass = isBuy
    ? "bg-green-500/80 text-green-100"
    : "bg-red-500/80 text-red-100"

  return (
    <div
      className={cn(
        "absolute left-0 right-0 flex items-center justify-between px-3 pr-8 py-1.5 rounded text-[10px] font-bold",
        colorClass
      )}
      style={style}
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
  const animRef = useRef<Map<string, number>>(new Map())
  const frameRef = useRef<number>(0)
  const mountedRef = useRef(true)

  const animateRef = useRef<() => void>(() => {
    if (!mountedRef.current) return
    const now = Date.now()
    const firstTs = animRef.current.values().next().value
    const elapsed = firstTs ? now - firstTs : 3000
    if (elapsed < 3000) {
      frameRef.current = requestAnimationFrame(animateRef.current)
    }
  })

  const handleWSMessage = useCallback((data: unknown) => {
    const msg = data as { type?: string; outcome?: string; side?: "buy" | "sell"; price?: number; amount?: number; username?: string }
    if (msg.type === "trade:new" && msg.outcome && msg.side && msg.price != null && msg.amount != null) {
      const item: TickerItem = {
        id: Math.random().toString(36).slice(2),
        outcome: msg.outcome,
        side: msg.side,
        price: msg.price,
        amount: msg.amount,
        username: msg.username ?? "Unknown",
      }
      setItems((prev) => [item, ...prev].slice(0, 5))
      animRef.current.set(item.id, Date.now())
      if (mountedRef.current) {
        cancelAnimationFrame(frameRef.current)
        frameRef.current = requestAnimationFrame(animateRef.current)
      }
    }
  }, [])

  useMarketSocket({
    marketId,
    onMessage: handleWSMessage,
    enabled: !!marketId,
  })

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      cancelAnimationFrame(frameRef.current)
      animRef.current.clear()
    }
  }, [])

  return (
    <div className="relative h-12 overflow-hidden">
      <div className="absolute inset-0 flex flex-col justify-end">
        {items.length === 0 ? null : (
          items.map((item, i) => {
            const startTime = animRef.current.get(item.id)
            const progress = startTime ? Math.min((Date.now() - startTime) / 3000, 1) : 1
            const isBuy = item.side === "buy"
            const bottom = isBuy
              ? `${progress * (100 / items.length) * (i + 1) - 12}%`
              : `${(1 - progress) * (100 / items.length) * (items.length - i)}%`
            const opacity = progress < 0.8 ? 1 : 1 - (progress - 0.8) / 0.2

            return (
              <TickerBar
                key={item.id}
                item={item}
                style={{
                  position: "absolute",
                  bottom,
                  left: 0,
                  right: 0,
                  opacity,
                  transition: "bottom 0.3s ease-out, opacity 0.3s ease-out",
                }}
              />
            )
          })
        )}
      </div>
    </div>
  )
}

export { LiveTradeTicker }

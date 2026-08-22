"use client"

import { useState, useRef, useEffect, memo } from "react"
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

  const handleWSMessage = (data: unknown) => {
    const msg = data as { type?: string; trade?: TickerItem }
    if (msg.type === "trade:new" && msg.trade) {
      const item = { ...msg.trade, id: Math.random().toString(36).slice(2) }
      setItems((prev) => [item, ...prev].slice(0, 5))
      animRef.current.set(item.id, Date.now())
      animate()
    }
  }

  function animate() {
    const now = Date.now()
    const elapsed = now - (animRef.current.values().next().value ?? now)
    if (elapsed < 3000) {
      frameRef.current = requestAnimationFrame(animate)
    }
  }

  const { status } = useMarketSocket({
    marketId,
    onMessage: handleWSMessage,
    enabled: !!marketId,
  })

  // Cancel RAF loop on unmount to prevent memory leak
  useEffect(() => {
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
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

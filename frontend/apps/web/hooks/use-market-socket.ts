"use client"

import { useEffect, useRef, useState } from "react"
import { config } from "@/lib/config"

export type WSStatus = "connecting" | "connected" | "disconnected" | "error"

interface UseMarketSocketOptions {
  marketId: string
  onMessage: (data: unknown) => void
  enabled?: boolean
}

export function useMarketSocket({ marketId, onMessage, enabled = true }: UseMarketSocketOptions) {
  const [status, setStatus] = useState<WSStatus>("disconnected")
  const wsRef = useRef<WebSocket | null>(null)
  const retriesRef = useRef(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = () => {
    if (!enabled || !marketId) return

    setStatus("connecting")
    const ws = new WebSocket(`${config.wsUrl}/ws/markets/${marketId}`)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus("connected")
      retriesRef.current = 0
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string)
        onMessage(data)
      } catch { /* ignore */ }
    }

    ws.onclose = () => {
      setStatus("disconnected")
      const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30_000)
      retriesRef.current++
      timeoutRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      setStatus("error")
      ws.close()
    }
  }

  useEffect(() => {
    connect()
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      wsRef.current?.close()
    }
  }, [marketId, enabled])

  return { status }
}

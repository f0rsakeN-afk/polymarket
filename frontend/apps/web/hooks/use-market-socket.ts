"use client"

import { useEffect, useRef, useCallback, useState } from "react"
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
  const onMessageRef = useRef(onMessage)
  const enabledRef = useRef(enabled)
  const marketIdRef = useRef(marketId)
  const mountedRef = useRef(true)

  onMessageRef.current = onMessage
  enabledRef.current = enabled
  marketIdRef.current = marketId

  const connect = useCallback(() => {
    if (!enabledRef.current || !marketIdRef.current) return

    setStatus("connecting")

    const ws = new WebSocket(`${config.wsUrl}/ws/markets/${marketIdRef.current}`)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close()
        return
      }
      setStatus("connected")
      retriesRef.current = 0
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string)
        onMessageRef.current(data)
      } catch { /* ignore parse errors */ }
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setStatus("disconnected")
      const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30_000)
      retriesRef.current++
      timeoutRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      if (!mountedRef.current) return
      setStatus("error")
      ws.close()
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()

    return () => {
      mountedRef.current = false
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [connect])

  return { status }
}

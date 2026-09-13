"use client"

import { useEffect, useRef, useCallback, useState } from "react"
import { config } from "@/lib/config"

export type WSStatus = "connecting" | "connected" | "disconnected" | "error"

interface UseUserSocketOptions {
  userId: string
  onMessage: (data: unknown) => void
  enabled?: boolean
}

export function useUserSocket({ userId, onMessage, enabled = true }: UseUserSocketOptions) {
  const [statusState, setStatusState] = useState<WSStatus>("disconnected")
  const wsRef = useRef<WebSocket | null>(null)
  const retriesRef = useRef(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  const enabledRef = useRef(enabled)
  const userIdRef = useRef(userId)
  const mountedRef = useRef(true)

  // Keep message handler ref in sync
  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  // Keep enabled ref in sync
  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  // Keep userId ref in sync
  useEffect(() => {
    userIdRef.current = userId
  }, [userId])

  // Named function expression so the reconnect timeout can reference itself
  // without touching the outer `connect` binding during initialization.
  const connect: () => void = useCallback(function connectFn() {
    if (!enabledRef.current || !userIdRef.current) return

    setStatusState("connecting")

    // Auth: access_token cookie is sent automatically by browser on WS handshake
    const ws = new WebSocket(`${config.wsUrl}/ws/notifications/${userIdRef.current}`)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close()
        return
      }
      setStatusState("connected")
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
      setStatusState("disconnected")
      const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30_000)
      retriesRef.current++
      timeoutRef.current = setTimeout(() => {
        if (mountedRef.current) connectFn()
      }, delay)
    }

    ws.onerror = () => {
      if (!mountedRef.current) return
      setStatusState("error")
      ws.close()
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      // enabled flipped to false — close the socket immediately
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      wsRef.current?.close()
      wsRef.current = null
      return
    }

    mountedRef.current = true
    connect()

    return () => {
      mountedRef.current = false
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [connect, enabled])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { status: enabled ? statusState : "disconnected", send }
}

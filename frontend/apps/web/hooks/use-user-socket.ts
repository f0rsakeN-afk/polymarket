"use client"

import { useEffect, useRef, useCallback, useState } from "react"
import { config } from "@/lib/config"

export type WSStatus = "connecting" | "connected" | "disconnected" | "error"

interface UseUserSocketOptions {
  userId: string
  onMessage: (data: unknown) => void
  enabled?: boolean
}

/**
 * Consecutive reconnect attempts before the loop parks itself. Backoff stretches
 * to 30s, so this is ~2 minutes of trying — enough to ride out a deploy or a
 * dropped connection, without hammering the API for the lifetime of the tab when
 * the endpoint stays unreachable (or the session dies and every handshake is
 * refused). `enabled` flipping back to true restarts the loop.
 */
const MAX_RECONNECT_ATTEMPTS = 8

export function useUserSocket({ userId, onMessage, enabled = true }: UseUserSocketOptions) {
  const [statusState, setStatusState] = useState<WSStatus>("disconnected")
  const wsRef = useRef<WebSocket | null>(null)
  const retriesRef = useRef(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  const enabledRef = useRef(enabled)
  const userIdRef = useRef(userId)
  const mountedRef = useRef(true)
  const gaveUpRef = useRef(false)

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
    if (gaveUpRef.current) return

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
      if (!enabledRef.current) return
      if (retriesRef.current >= MAX_RECONNECT_ATTEMPTS) {
        gaveUpRef.current = true
        setStatusState("error")
        return
      }
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
      gaveUpRef.current = false
      retriesRef.current = 0
      return
    }

    mountedRef.current = true
    // Re-enabled (or first enabled) — clear the parked state and try again.
    gaveUpRef.current = false
    retriesRef.current = 0
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

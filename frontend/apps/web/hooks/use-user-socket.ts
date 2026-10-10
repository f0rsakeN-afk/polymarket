"use client"

import { useEffect, useRef, useCallback, useState } from "react"
import { config } from "@/lib/config"
import { reconnectDelayMs } from "@/lib/ws-backoff"

export type WSStatus = "connecting" | "connected" | "disconnected" | "error"

interface UseUserSocketOptions {
  userId: string
  onMessage: (data: unknown) => void
  enabled?: boolean
}

/**
 * Personal feed (`/ws/notifications/{user_id}`) - fills, positions and
 * notifications.
 *
 * The reconnect loop retries forever on a capped, jittered delay rather than
 * parking: this is the socket that makes a user's own portfolio live, and a
 * parked one means their positions silently stop updating while the page still
 * looks healthy. See `lib/ws-backoff`.
 *
 * It also recovers from a socket that died *without* a close event, and
 * announces a resync on reconnect. Both were missing here while the other two
 * hooks had them, which made the private feed the weakest of the three - and the
 * private feed is the one carrying fills. A laptop that slept mid-session left
 * a portfolio page disconnected until it was remounted, and a reconnect
 * silently skipped every fill that had happened while it was away.
 */
export function useUserSocket({ userId, onMessage, enabled = true }: UseUserSocketOptions) {
  const [statusState, setStatusState] = useState<WSStatus>("disconnected")
  const wsRef = useRef<WebSocket | null>(null)
  const retriesRef = useRef(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  const enabledRef = useRef(enabled)
  const userIdRef = useRef(userId)
  const mountedRef = useRef(true)
  /** Distinguishes a first connect (nothing to resync) from a reconnect. */
  const everConnectedRef = useRef(false)

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
      // Tell the consumer its cached portfolio may be behind. This is the only
      // catch-up available on a private feed: the channels are not sequenced, so
      // there is nothing to diff against and no way to notice a gap here. Fills
      // that happened while the socket was down are simply gone, and without
      // this the portfolio just keeps rendering the position it had before.
      //
      // Reconnects only - on a first connect the queries have just run.
      if (everConnectedRef.current) {
        onMessageRef.current({ type: "__ws_resync__", reason: "reconnect" })
      }
      everConnectedRef.current = true
    }

    ws.onmessage = (event) => {
      let data: unknown
      try {
        data = JSON.parse(event.data as string)
      } catch {
        return /* ignore parse errors - a bad frame must not kill the socket */
      }
      // Answer the server's heartbeat probe. This socket is the long-lived one -
      // a page left open all day is the archetypal half-open connection - and
      // the server reaps anything silent past its pong deadline. Not replying is
      // how a healthy session gets disconnected for being quiet.
      const frame = data as { type?: string; ts?: number }
      if (frame?.type === "ping") {
        try {
          ws.send(JSON.stringify({ type: "pong", ts: frame.ts }))
        } catch { /* closing; onclose handles it */ }
        return
      }
      onMessageRef.current(data)
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setStatusState("disconnected")
      if (!enabledRef.current) return
      const delay = reconnectDelayMs(retriesRef.current)
      retriesRef.current++
      timeoutRef.current = setTimeout(() => {
        if (mountedRef.current) connectFn()
      }, delay)
    }

    ws.onerror = () => {
      if (!mountedRef.current) return
      // `onclose` always follows and owns the retry; see the equivalent note in
      // use-global-trades-socket for why this must not write "error" itself.
      ws.close()
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      // enabled flipped to false • close the socket immediately
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      wsRef.current?.close()
      wsRef.current = null
      retriesRef.current = 0
      everConnectedRef.current = false
      return
    }

    mountedRef.current = true
    retriesRef.current = 0
    connect()

    // Recover a socket that died without a close event.
    //
    // A suspended laptop, a NAT timeout or a network handover can leave the
    // socket dead while the browser still reports OPEN - no `close` event fires,
    // so nothing in the reconnect loop ever runs. `online` and tab focus are the
    // only signals the browser gives us. This hook had neither, while the market
    // and trades hooks both had them, so the private feed was the one that could
    // stay dead longest - and it is the one carrying fills.
    //
    // `force` distinguishes them. `online` means the network changed state, so
    // redial whatever the socket claims to be. Tab focus fires constantly, so it
    // only redials when there is something to replace or a retry to restart -
    // but note it *does* replace a socket that still reports OPEN, because that
    // is precisely the half-dead state a suspended machine leaves behind and
    // `readyState` cannot tell it from a healthy one. One handshake per tab
    // switch, against showing a portfolio that missed fills.
    const recover = (force: boolean) => {
      if (!mountedRef.current || !enabledRef.current) return

      const retryWasPending = timeoutRef.current !== null
      const hasSocket = wsRef.current !== null
      if (!force && !hasSocket && !retryWasPending) return

      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }

      const ws = wsRef.current
      if (ws) {
        // Detach `onclose` first: `close()` is async, so this socket fires it
        // after its successor is live, and a live handler would queue another
        // reconnect for a socket already replaced.
        ws.onclose = null
        ws.close()
      }
      wsRef.current = null
      retriesRef.current = 0
      connect()
    }

    const onOnline = () => recover(true)
    const onVisible = () => {
      if (document.visibilityState === "visible") recover(false)
    }
    window.addEventListener("online", onOnline)
    document.addEventListener("visibilitychange", onVisible)

    return () => {
      mountedRef.current = false
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      window.removeEventListener("online", onOnline)
      document.removeEventListener("visibilitychange", onVisible)
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        // Detach `onclose` before closing: `close()` is async, so it fires after
        // this cleanup has run, and a live handler would schedule a reconnect for
        // a socket the component just abandoned.
        ws.onclose = null
        ws.close()
      }
    }
  }, [connect, enabled])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { status: enabled ? statusState : "disconnected", send }
}

"use client"

import { useEffect, useRef, useState } from "react"
import { config } from "@/lib/config"
import { reconnectDelayMs } from "@/lib/ws-backoff"

export type GlobalTradesWSStatus = "connecting" | "connected" | "disconnected" | "error"

interface UseGlobalTradesSocketOptions {
  onMessage: (data: unknown) => void
  enabled?: boolean
}

/**
 * Platform-wide trade feed socket (`/ws/trades`).
 *
 * This is deliberately a separate socket rather than a reuse of
 * `use-market-socket`, for two reasons that are both load-bearing:
 *
 *  1. The right server endpoint. `/ws/markets/{id}` only subscribes the Redis
 *     channels for one market, and `global:trades` is a different channel. The
 *     market socket physically cannot deliver this feed.
 *  2. The right failure domain. That socket is a module-level singleton shared
 *     per tab, so mounting a page for a *second* feed through it would couple
 *     the trades page's liveness to whichever market page happened to be open.
 *
 * The feed is public (`GET /trades` needs no auth), so this deliberately does
 * not gate on a session - an anonymous visitor should see live trades too. The
 * `access_token` cookie rides along automatically when present, which is all the
 * server needs it for.
 *
 * Reconnect also triggers on `online` and on tab focus: a socket dropped by a
 * sleeping laptop produces no close event, so without those the feed would sit
 * "connected" and silently dead for the rest of the session.
 *
 * The reconnect loop never gives up - see `lib/ws-backoff` for why a permanent
 * park is worse than a slow retry.
 */
export function useGlobalTradesSocket({
  onMessage,
  enabled = true,
}: UseGlobalTradesSocketOptions) {
  const [status, setStatus] = useState<GlobalTradesWSStatus>("disconnected")
  const wsRef = useRef<WebSocket | null>(null)
  const retriesRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  const mountedRef = useRef(true)
  /** Has this socket ever opened? Distinguishes a first connect - where React
   *  Query has just fetched and there is nothing to resync - from a reconnect,
   *  where a window of trades is certainly missing. */
  const everConnectedRef = useRef(false)

  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    mountedRef.current = true

    if (!enabled) {
      if (timerRef.current) clearTimeout(timerRef.current)
      const ws = wsRef.current
      // Identity-captured close: `close()` is async, so a socket replaced later in
      // the same tick fires its `onclose` *after* its successor is live. Clearing
      // `wsRef` unconditionally made the live socket untracked.
      if (ws) {
        ws.onclose = null
        ws.close()
        wsRef.current = null
      }
      retriesRef.current = 0
      // No `setStatus("disconnected")` here. The returned status is derived from
      // `enabled` below, so the disabled case is already correct without a state
      // write - and writing it synchronously in the effect body triggers an extra
      // cascading render on every toggle.
      return
    }

    const connect = (): void => {
      if (!mountedRef.current) return
      if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return

      setStatus("connecting")
      const ws = new WebSocket(`${config.wsUrl}/ws/trades`)
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) {
          ws.close()
          return
        }
        retriesRef.current = 0
        setStatus("connected")
        // Tell the consumer its REST-derived baseline may be behind. The feed
        // is a firehose with no sequence numbers (it is not worth them - the
        // client reconciles by trade id against `GET /trades`), so there is
        // nothing to diff against and this hook cannot notice a gap on its own.
        // Refetching is the whole repair.
        //
        // Reconnects only. On a first connect the query has just run and there
        // is nothing to repair; announcing one would make every page load do a
        // redundant duplicate fetch.
        if (everConnectedRef.current) {
          onMessageRef.current({ type: "__ws_resync__", reason: "reconnect" })
        }
        everConnectedRef.current = true
      }

      ws.onmessage = (event) => {
        let parsed: unknown
        try {
          parsed = JSON.parse(event.data as string)
        } catch {
          return  /* ignore parse errors - a bad frame must not kill the socket */
        }
        // Answer the server's heartbeat. This frame has no `market_id` and no
        // payload the feed cares about, but the server reaps any socket that
        // goes quiet, so staying silent means being disconnected for being
        // silent.
        const frame = parsed as { type?: string; ts?: number }
        if (frame?.type === "ping") {
          try {
            ws.send(JSON.stringify({ type: "pong", ts: frame.ts }))
          } catch { /* closing; onclose handles it */ }
          return
        }
        onMessageRef.current(parsed)
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        if (wsRef.current === ws) wsRef.current = null
        setStatus("disconnected")

        // Retry forever on a capped, jittered delay. The previous loop parked
        // itself after 8 attempts and only un-parked on `online` or a tab focus
        // - neither of which the browser guarantees, so a dropped feed could stay
        // dead for the rest of the session while still looking connected.
        const delay = reconnectDelayMs(retriesRef.current)
        retriesRef.current++
        // Nulled on fire. `recover` uses "is a retry pending?" to tell a parked
        // feed from one that is merely between attempts, and a stale non-null id
        // left behind by a timer that already fired made every parked hook look
        // like it was still retrying - so recovery never un-parked it.
        timerRef.current = setTimeout(() => {
          timerRef.current = null
          connect()
        }, delay)
      }

      ws.onerror = () => {
        if (!mountedRef.current) return
        // Deliberately does NOT set "error".
        //
        // `onerror` is always followed by `onclose`, and `onclose` owns the status
        // machine. Writing "error" here meant every ordinary blip flashed an
        // error for one frame before `onclose` immediately overwrote it with
        // "disconnected" - so the indicator flickered between two unrelated
        // meanings on every single retry. "error" now means exactly one thing:
        // a handshake the browser refused outright (see the `catch` in `connect`).
        ws.close()
      }
    }

    retriesRef.current = 0
    connect()

    // A socket that died without a close event (sleep, NAT timeout) leaves
    // `readyState` looking OPEN, so the guard in `connect` would refuse to
    // redial. Force a reconnect when the browser says it is back.
    /**
     * Re-dial after the browser reports the connection changed.
     *
     * `force` distinguishes the two signals bound to this:
     *
     *  - `online` (force) means the *network* changed state. Whatever the socket
     *     was doing, the world underneath it moved, so redial unconditionally.
     *  - tab focus (no force) only forces a redial when there is already a
     *     socket to replace or a retry to restart. Both matter: a socket killed
     *     by a suspended machine can still report OPEN, because the browser may
     *     not notice until it next writes, so `readyState` alone cannot tell it
     *     from a healthy one. Tab focus is the only browser-side evidence that
     *     time passed, and replacing the socket costs one handshake - far less
     *     than showing stale trades until the server's pong deadline expires.
     */
    const recover = (force: boolean) => {
      if (!mountedRef.current) return

      // Read the retry state *before* clearing the timer below, otherwise every
      // parked feed looks like it is mid-attempt and a tab focus tears down a
      // healthy socket.
      const retryWasPending = timerRef.current !== null
      const hasSocket = wsRef.current !== null
      if (!force && !hasSocket && !retryWasPending) return

      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }

      if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
        // Nulled first: `close()` is async, so this socket fires `onclose` after
        // its successor is live, and a live `onclose` would queue a reconnect for
        // a socket already replaced.
        wsRef.current.onclose = null
        wsRef.current.close()
      }
      retriesRef.current = 0
      wsRef.current = null
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
      if (timerRef.current) clearTimeout(timerRef.current)
      window.removeEventListener("online", onOnline)
      document.removeEventListener("visibilitychange", onVisible)
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        ws.onclose = null
        ws.close()
      }
    }
  }, [enabled])

  // Derived rather than stored: while disabled the hook holds no socket at all,
  // so reporting "disconnected" is a fact about `enabled`, not a transition to
  // record. This is also what removed the setState-in-effect warning.
  return { status: enabled ? status : ("disconnected" as const) }
}
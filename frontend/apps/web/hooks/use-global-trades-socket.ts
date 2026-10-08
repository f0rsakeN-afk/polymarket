"use client"

import { useEffect, useRef, useState } from "react"
import { config } from "@/lib/config"

export type GlobalTradesWSStatus = "connecting" | "connected" | "disconnected" | "error"

/**
 * Consecutive reconnect attempts before parking. Backoff reaches 30s, so this is
 * roughly two minutes of retrying - enough to ride out a deploy or a dropped
 * connection without hammering the endpoint for the lifetime of the tab.
 */
const MAX_RECONNECT_ATTEMPTS = 8

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
  const gaveUpRef = useRef(false)

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
      gaveUpRef.current = false
      retriesRef.current = 0
      // No `setStatus("disconnected")` here. The returned status is derived from
      // `enabled` below, so the disabled case is already correct without a state
      // write - and writing it synchronously in the effect body triggers an extra
      // cascading render on every toggle.
      return
    }

    const connect = (): void => {
      if (!mountedRef.current || gaveUpRef.current) return
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
      }

      ws.onmessage = (event) => {
        try {
          onMessageRef.current(JSON.parse(event.data as string))
        } catch {
          /* ignore parse errors - a bad frame must not kill the socket */
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        if (wsRef.current === ws) wsRef.current = null
        // Parked state is sticky, and is checked *before* the generic
        // "disconnected" write. Reporting disconnected first meant any later close
        // event on an already-closed socket downgraded "error" back to
        // "disconnected", hiding the fact that the feed is permanently parked and
        // will not retry until `online` or a tab focus.
        if (gaveUpRef.current) return
        setStatus("disconnected")

        if (retriesRef.current >= MAX_RECONNECT_ATTEMPTS) {
          gaveUpRef.current = true
          setStatus("error")
          return
        }
        const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30_000)
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
        // machine: it decides between "disconnected" (retry) and "error" (parked).
        // Writing "error" here meant every ordinary blip flashed a permanent-looking
        // error for one frame before `onclose` immediately overwrote it with
        // "disconnected" - so the indicator flickered between two unrelated
        // meanings on every single retry.
        ws.close()
      }
    }

    gaveUpRef.current = false
    retriesRef.current = 0
    connect()

    // A socket that died without a close event (sleep, NAT timeout) leaves
    // `readyState` looking OPEN, so the guard in `connect` would refuse to
    // redial. Force a reconnect when the browser says it is back.
    /**
     * Re-dial after the browser reports the connection changed.
     *
     * `force` distinguishes the two very different signals bound to this:
     *
     *  - `online` (force) means the *network* changed state. A feed parked
     *     because the endpoint was refusing us is exactly what should be retried,
     *     so the park is always cleared.
     *  - tab focus (no force) is routine user activity that fires constantly.
     *     Clearing the park there would mean an endpoint down for two minutes
     *     gets re-attempted on every tab switch - the retry ceiling becomes no
     *     ceiling, and a refusing endpoint is hammered all day. So focus only
     *     repairs a socket that looks dead or a retry that is genuinely pending.
     */
    const recover = (force: boolean) => {
      if (!mountedRef.current) return

      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }

      const ws = wsRef.current
      const retryWasPending = timerRef.current !== null
      const hasSocket = ws !== null

      if (!force && !hasSocket && !retryWasPending) return

      gaveUpRef.current = false
      retriesRef.current = 0

      if (ws && ws.readyState <= WebSocket.OPEN) {
        // Nulled first: `close()` is async, so this socket fires `onclose` after
        // its successor is live, and a live `onclose` would queue a reconnect for
        // a socket already replaced.
        ws.onclose = null
        ws.close()
      }
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
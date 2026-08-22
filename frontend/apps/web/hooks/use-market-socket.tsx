"use client"

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react"
import { config } from "@/lib/config"

export type WSStatus = "connecting" | "connected" | "disconnected" | "error"

type MessageHandler = (data: unknown) => void

// ─── Per-market subscription state ─────────────────────────────────────────────

interface MarketSub {
  /** Sequence number — incrementing counter used to discard stale messages */
  seq: number
  /** Set of handlers currently subscribed to this market */
  handlers: Set<MessageHandler>
  /** Whether a WS subscribe message has been sent to the server for this market */
  wsSubscribed: boolean
}

// ─── Shared connection singleton ────────────────────────────────────────────────

interface SharedConnection {
  ws: WebSocket | null
  status: WSStatus
  /** Per-market subscription metadata */
  subs: Map<string, MarketSub>
  /** Per-market mutex — prevents double-subscribe on rapid add/remove */
  subLocks: Map<string, boolean>
  retries: number
  reconnectTimer: ReturnType<typeof setTimeout> | null
  /** All markets this WS is subscribed to on the server (re-subscribed on reconnect) */
  serverSubs: Set<string>
  /** Set of status-change handlers */
  statusHandlers: Set<MessageHandler>
}

// Module-level singleton — one WebSocket per browser tab
let _conn: SharedConnection | null = null

function getConnection(): SharedConnection {
  if (!_conn) {
    _conn = {
      ws: null,
      status: "disconnected",
      subs: new Map(),
      subLocks: new Map(),
      retries: 0,
      reconnectTimer: null,
      serverSubs: new Set(),
      statusHandlers: new Set(),
    }
  }
  return _conn
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

function setStatus(conn: SharedConnection, status: WSStatus) {
  conn.status = status
  for (const h of conn.statusHandlers) {
    try { h({ type: "__ws_status__", status }) } catch { /* ignore */ }
  }
}

function sendWs(conn: SharedConnection, data: unknown) {
  if (conn.ws?.readyState === WebSocket.OPEN) {
    conn.ws.send(JSON.stringify(data))
  }
}

/** Atomically subscribe to a market on the wire — mutex prevents double-send. */
async function wsSubscribe(conn: SharedConnection, marketId: string): Promise<void> {
  // Aquire per-market mutex
  let locked = conn.subLocks.get(marketId)
  while (locked) {
    await new Promise((r) => setTimeout(r, 5))
    locked = conn.subLocks.get(marketId)
  }
  conn.subLocks.set(marketId, true)
  try {
    const sub = conn.subs.get(marketId)
    if (!sub || sub.wsSubscribed) return  // already sent
    sendWs(conn, { type: "subscribe", market_id: marketId })
    sub.wsSubscribed = true
    conn.serverSubs.add(marketId)
  } finally {
    conn.subLocks.set(marketId, false)
  }
}

/** Unsubscribe from a market on the wire. */
function wsUnsubscribe(conn: SharedConnection, marketId: string) {
  if (!conn.serverSubs.has(marketId)) return
  sendWs(conn, { type: "unsubscribe", market_id: marketId })
  conn.serverSubs.delete(marketId)
  const sub = conn.subs.get(marketId)
  if (sub) sub.wsSubscribed = false
}

// ─── Connect / Reconnect ────────────────────────────────────────────────────────

function connect(conn: SharedConnection, firstMarketId: string) {
  if (conn.ws) return  // already open or pending

  const token = document.cookie
    .split("; ")
    .find((r) => r.startsWith("access_token="))
    ?.split("=")[1] ?? ""

  const ws = new WebSocket(
    `${config.wsUrl}/ws/markets/${firstMarketId}?token=${encodeURIComponent(token)}`
  )
  conn.ws = ws
  setStatus(conn, "connecting")

  ws.onopen = () => {
    conn.retries = 0
    setStatus(conn, "connected")
    // Re-subscribe to all markets we had active before the disconnect
    for (const m of conn.serverSubs) {
      ws.send(JSON.stringify({ type: "subscribe", market_id: m }))
    }
    // Also send any pending subscriptions that weren't yet ACKed
    for (const [marketId, sub] of conn.subs) {
      if (!sub.wsSubscribed) {
        ws.send(JSON.stringify({ type: "subscribe", market_id: marketId }))
        sub.wsSubscribed = true
        conn.serverSubs.add(marketId)
      }
    }
  }

  ws.onmessage = (event) => {
    let data: unknown
    try {
      data = typeof event.data === "string" ? JSON.parse(event.data) : event.data
    } catch {
      return  // ignore unparseable
    }

    const d = data as { market_id?: string; type?: string }
    if (!d.market_id) return

    const sub = conn.subs.get(d.market_id)
    if (!sub) return  // no handler registered for this market — discard

    // Increment seq so any in-flight messages from before an unsubscribe are dropped
    sub.seq++

    // Deliver to all handlers for this market — each in try/catch so one bad
    // handler doesn't break the socket for other handlers or corrupt state
    const currentSeq = sub.seq
    for (const h of sub.handlers) {
      try {
        h(data)
      } catch {
        /* user handler threw — socket survives */
      }
      // If seq changed while iterating, a re-subscribe happened — stop delivering
      // stale messages from before the re-subscribe
      if (sub.seq !== currentSeq) break
    }
  }

  ws.onclose = () => {
    conn.ws = null
    setStatus(conn, "disconnected")
    const delay = Math.min(1000 * Math.pow(2, conn.retries), 30_000)
    conn.retries++
    conn.reconnectTimer = setTimeout(() => {
      const first = conn.serverSubs.values().next().value
        ?? conn.subs.keys().next().value
        ?? "default"
      connect(conn, first)
    }, delay)
  }

  ws.onerror = () => {
    setStatus(conn, "error")
    ws.close()
  }
}

// ─── Context ───────────────────────────────────────────────────────────────────

interface MarketSocketCtx {
  subscribe: (marketId: string, handler: MessageHandler) => () => void
  getStatus: () => WSStatus
}

const MarketSocketContext = createContext<MarketSocketCtx>({
  subscribe: () => () => {},
  getStatus: () => "disconnected",
})

export function MarketSocketProvider({ children }: { children: React.ReactNode }) {
  const conn = useRef<SharedConnection>(getConnection())
  const [, tick] = useState(0)

  const subscribe = useCallback((marketId: string, handler: MessageHandler) => {
    const c = conn.current

    // Initialise market sub if first subscriber
    if (!c.subs.has(marketId)) {
      c.subs.set(marketId, { seq: 0, handlers: new Set(), wsSubscribed: false })
    }
    const sub = c.subs.get(marketId)!
    sub.handlers.add(handler)

    // If no WS open yet, connect to first subscribed market
    if (!c.ws) {
      connect(c, marketId)
    } else {
      // WS is open — subscribe on the wire if not already
      wsSubscribe(c, marketId)
    }

    // Return unsubscribe
    return () => {
      const currentSub = c.subs.get(marketId)
      if (!currentSub) return

      currentSub.handlers.delete(handler)

      // Last handler for this market gone — unsubscribe from it on the wire
      if (currentSub.handlers.size === 0) {
        c.subs.delete(marketId)
        wsUnsubscribe(c, marketId)

        // If all markets desubscribed, close the WS
        if (c.subs.size === 0) {
          if (c.reconnectTimer) clearTimeout(c.reconnectTimer)
          c.ws?.close()
          c.ws = null
          setStatus(c, "disconnected")
          c.retries = 0
        }
      }
    }
  }, [])

  const getStatus = useCallback(() => conn.current.status, [])

  // Track status changes to force re-render so hooks see fresh status
  useEffect(() => {
    const c = conn.current
    const statusHandler: MessageHandler = () => tick((n) => n + 1)
    c.statusHandlers.add(statusHandler)
    return () => { c.statusHandlers.delete(statusHandler) }
  }, [])

  return (
    <MarketSocketContext.Provider value={{ subscribe, getStatus }}>
      {children}
    </MarketSocketContext.Provider>
  )
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useMarketSocket({
  marketId,
  onMessage,
  enabled = true,
}: {
  marketId: string
  onMessage: (data: unknown) => void
  enabled?: boolean
}) {
  const [status, setStatus] = useState<WSStatus>("disconnected")
  const onMessageRef = useRef(onMessage)
  const marketIdRef = useRef(marketId)

  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])
  useEffect(() => { marketIdRef.current = marketId }, [marketId])

  const ctx = useContext(MarketSocketContext)

  useEffect(() => {
    if (!enabled || !marketId) return () => {}

    const statusHandler: MessageHandler = (data) => {
      const d = data as { type?: string; status?: WSStatus }
      if (d.type === "__ws_status__" && d.status) setStatus(d.status)
    }

    const unsubMsg = ctx.subscribe(marketId, (data) => onMessageRef.current(data))
    const unsubStatus = ctx.subscribe(marketId, statusHandler)
    setStatus(ctx.getStatus())

    return () => {
      unsubMsg()
      unsubStatus()
    }
  }, [enabled, marketId, ctx])

  return { status }
}

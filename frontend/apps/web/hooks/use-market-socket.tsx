"use client"

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
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
  /** Market used in WS URL — the most recently active market for reconnect path */
  lastConnectedMarket: string | null
  /** Reconnect loop parked after too many consecutive failures */
  gaveUp: boolean
  /** The socket being closed on purpose — its `onclose` must not queue a reconnect */
  intentionalCloseSocket: WebSocket | null
  /** Deferred "registry is empty, close the socket" timer (see the unsubscribe path) */
  closeTimer: ReturnType<typeof setTimeout> | null
}

/**
 * Consecutive reconnect attempts before the loop parks itself.
 *
 * Backoff already stretches to 30s, so this is ~2 minutes of trying. Without a
 * ceiling an endpoint that is down (or refusing us) is retried for the lifetime
 * of the tab, which is what filled the API log with identical handshake
 * rejections. The park clears on `online` / tab focus.
 */
const MAX_RECONNECT_ATTEMPTS = 8

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
      lastConnectedMarket: null,
      gaveUp: false,
      intentionalCloseSocket: null,
      closeTimer: null,
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
  if (conn.gaveUp) return  // reconnect loop parked — cleared by network recovery

  // No auth gate here, deliberately. Market data is public over REST
  // (`/markets/{slug}/orderbook`, `/markets/{slug}/trades`) and this socket pushes
  // exactly that, so the server accepts an anonymous handshake. Gating the client
  // on a session would deny live prices to logged-out visitors — who can already
  // read the same numbers over HTTP. The `access_token` cookie rides along
  // automatically when there is a session, which is all the server needs it for.
  //
  // Clear any pending reconnect timer — prevents duplicate connections on rapid calls
  if (conn.reconnectTimer) {
    clearTimeout(conn.reconnectTimer)
    conn.reconnectTimer = null
  }
  // A pending deferred close is now moot — something asked for a socket.
  if (conn.closeTimer) {
    clearTimeout(conn.closeTimer)
    conn.closeTimer = null
  }

  conn.lastConnectedMarket = firstMarketId
  const ws = new WebSocket(`${config.wsUrl}/ws/markets/${firstMarketId}`)
  conn.ws = ws
  // Identity of the socket being closed on purpose. A bare boolean was wrong:
  // it is shared across sockets, so a *late* close event from a socket we have
  // already replaced would read the flag its successor reset.
  conn.intentionalCloseSocket = null
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
    // A superseded socket must not touch shared state. `close()` is async, so a
    // socket we already replaced fires `onclose` *after* its successor is live;
    // nulling `conn.ws` unconditionally here made the live socket untracked, and
    // the next subscribe opened a second one — two sockets, both receiving, and
    // the flap repeated on every subscribe/unsubscribe cycle.
    if (conn.ws !== ws) return
    conn.ws = null
    setStatus(conn, "disconnected")

    // Closed on purpose (last subscriber left) — the reconnect loop must stay
    // parked until something actually asks for a socket.
    if (conn.intentionalCloseSocket === ws) {
      conn.intentionalCloseSocket = null
      return
    }

    if (conn.retries >= MAX_RECONNECT_ATTEMPTS) {
      conn.gaveUp = true
      setStatus(conn, "error")
      return
    }

    const delay = Math.min(1000 * Math.pow(2, conn.retries), 30_000)
    conn.retries++
    // Reconnect to the market the user is currently viewing — not the first subscribed
    const market = conn.lastConnectedMarket
      ?? conn.serverSubs.values().next().value
      ?? conn.subs.keys().next().value
      ?? "default"
    conn.reconnectTimer = setTimeout(() => connect(conn, market), delay)
  }

  ws.onerror = () => {
    if (conn.ws !== ws) return
    setStatus(conn, "error")
    ws.close()
  }
}

// ─── Context ───────────────────────────────────────────────────────────────────

interface MarketSocketCtx {
  subscribe: (marketId: string, handler: MessageHandler) => () => void
  getStatus: () => WSStatus
}

const NOOP_SUBSCRIBE = () => () => {}
const NOOP_GET_STATUS = () => "disconnected" as WSStatus

const MarketSocketContext = createContext<MarketSocketCtx>({
  subscribe: NOOP_SUBSCRIBE,
  getStatus: NOOP_GET_STATUS,
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
      // Update the reconnect target to the most recently active market
      c.lastConnectedMarket = marketId
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
        c.subLocks.delete(marketId)  // ponytail: prevent subLocks Map leak
        wsUnsubscribe(c, marketId)

        // If all markets desubscribed, close the WS — but not synchronously.
        // React Strict Mode is on by default with the app router (Next 13.5.1+),
        // so in dev every component unmounts and remounts, and a registry that
        // briefly empties would close the socket and immediately reopen it.
        // Anything that re-subscribes on the next tick keeps it; a genuinely
        // empty registry still closes.
        if (c.subs.size === 0) {
          if (c.closeTimer) clearTimeout(c.closeTimer)
          c.closeTimer = setTimeout(() => {
            c.closeTimer = null
            if (c.subs.size > 0) return
            if (c.reconnectTimer) clearTimeout(c.reconnectTimer)
            const ws = c.ws
            c.intentionalCloseSocket = ws
            c.ws = null
            ws?.close()
            setStatus(c, "disconnected")
            c.retries = 0
          }, 0)
        }
      }
    }
  }, [])

  const getStatus = useCallback(() => conn.current.status, [])

  const ctxValue = useMemo(() => ({ subscribe, getStatus }), [subscribe, getStatus])

  // Track status changes to force re-render so hooks see fresh status
  useEffect(() => {
    const c = conn.current
    const statusHandler: MessageHandler = () => tick((n) => n + 1)
    c.statusHandlers.add(statusHandler)
    return () => { c.statusHandlers.delete(statusHandler) }
  }, [])

  // Recover a parked or sleeping socket when the network comes back. A laptop
  // resuming from sleep drops the socket silently — `online` and
  // `visibilitychange` are the only signals the browser gives us, and without
  // them a parked socket stays parked for the rest of the session.
  useEffect(() => {
    const c = conn.current

    const recover = () => {
      if (!c.subs.size) return
      if (c.ws && !c.gaveUp) return  // still healthy
      c.gaveUp = false
      c.retries = 0
      if (c.reconnectTimer) {
        clearTimeout(c.reconnectTimer)
        c.reconnectTimer = null
      }
      const market = c.lastConnectedMarket ?? c.subs.keys().next().value
      if (market) connect(c, market)
    }

    const onVisible = () => {
      if (document.visibilityState === "visible") recover()
    }

    window.addEventListener("online", recover)
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      window.removeEventListener("online", recover)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [])

  return (
    <MarketSocketContext.Provider value={ctxValue}>
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
  const ctx = useContext(MarketSocketContext)

  const [status, setStatus] = useState<WSStatus>(() => ctx.getStatus())
  const onMessageRef = useRef(onMessage)
  const marketIdRef = useRef(marketId)

  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])
  useEffect(() => { marketIdRef.current = marketId }, [marketId])

  useEffect(() => {
    if (!enabled || !marketId) return () => {}

    const statusHandler: MessageHandler = (data) => {
      const d = data as { type?: string; status?: WSStatus }
      if (d.type === "__ws_status__" && d.status) setStatus(d.status)
    }

    const unsubMsg = ctx.subscribe(marketId, (data) => onMessageRef.current(data))
    const unsubStatus = ctx.subscribe(marketId, statusHandler)

    return () => {
      unsubMsg()
      unsubStatus()
    }
  }, [enabled, marketId, ctx])

  return { status }
}

"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react"
import { config } from "@/lib/config"

export type WSStatus = "connecting" | "connected" | "disconnected" | "error"

interface UseMarketSocketOptions {
  marketId: string
  onMessage: (data: unknown) => void
  enabled?: boolean
}

// ─── Shared connection per market via module-level singleton ────────────────────

type MessageHandler = (data: unknown) => void

interface SharedSocket {
  ws: WebSocket | null
  status: WSStatus
  handlers: Set<MessageHandler>
  retries: number
  timeout: ReturnType<typeof setTimeout> | null
  marketId: string | null
}

const sockets = new Map<string, SharedSocket>()

function getOrCreateSocket(marketId: string): SharedSocket {
  if (!sockets.has(marketId)) {
    sockets.set(marketId, {
      ws: null,
      status: "disconnected",
      handlers: new Set(),
      retries: 0,
      timeout: null,
      marketId,
    })
  }
  return sockets.get(marketId)!
}

function closeSocket(sock: SharedSocket) {
  if (sock.timeout) clearTimeout(sock.timeout)
  sock.ws?.close()
  sock.ws = null
  sock.status = "disconnected"
}

function connectSocket(sock: SharedSocket) {
  if (!sock.marketId) return

  sock.status = "connecting"
  // Notify all subscribers of status change
  notifyAll(sock, { type: "__ws_status__", status: "connecting" })

  const ws = new WebSocket(`${config.wsUrl}/ws/markets/${sock.marketId}`)
  sock.ws = ws

  ws.onopen = () => {
    sock.status = "connected"
    sock.retries = 0
    notifyAll(sock, { type: "__ws_status__", status: "connected" })
  }

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data as string)
      sock.handlers.forEach((h) => h(data))
    } catch { /* ignore parse errors */ }
  }

  ws.onclose = () => {
    sock.status = "disconnected"
    notifyAll(sock, { type: "__ws_status__", status: "disconnected" })
    const delay = Math.min(1000 * Math.pow(2, sock.retries), 30_000)
    sock.retries++
    sock.timeout = setTimeout(() => connectSocket(sock), delay)
  }

  ws.onerror = () => {
    sock.status = "error"
    notifyAll(sock, { type: "__ws_status__", status: "error" })
    ws.close()
  }
}

function notifyAll(sock: SharedSocket, data: unknown) {
  sock.handlers.forEach((h) => h(data))
}

// ─── Context ───────────────────────────────────────────────────────────────────

interface MarketSocketCtx {
  subscribe: (marketId: string, handler: MessageHandler) => () => void
  getStatus: (marketId: string) => WSStatus
}

const MarketSocketContext = createContext<MarketSocketCtx>({
  subscribe: () => () => {},
  getStatus: () => "disconnected",
})

export function MarketSocketProvider({ children }: { children: React.ReactNode }) {
  const handlersRef = useRef(new Map<string, Set<MessageHandler>>())

  const subscribe = useCallback((marketId: string, handler: MessageHandler) => {
    const sock = getOrCreateSocket(marketId)

    // Attach handler (filter out the synthetic status events)
    const wrapped: MessageHandler = (data) => {
      if ((data as {type?: string}).type?.startsWith("__ws_")) return
      handler(data)
    }
    sock.handlers.add(wrapped)

    // If this is the first handler for this market, open the socket
    if (sock.handlers.size === 1) {
      connectSocket(sock)
    }

    // Return unsubscribe
    return () => {
      sock.handlers.delete(wrapped)
      if (sock.handlers.size === 0) {
        closeSocket(sock)
        sockets.delete(marketId)
      }
    }
  }, [])

  const getStatus = useCallback((marketId: string) => {
    return sockets.get(marketId)?.status ?? "disconnected"
  }, [])

  return (
    <MarketSocketContext.Provider value={{ subscribe, getStatus }}>
      {children}
    </MarketSocketContext.Provider>
  )
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useMarketSocket({ marketId, onMessage, enabled = true }: UseMarketSocketOptions) {
  const [status, setStatus] = useState<WSStatus>("disconnected")
  const onMessageRef = useRef(onMessage)
  const enabledRef = useRef(enabled)
  const marketIdRef = useRef(marketId)

  // Keep refs fresh without re-subscribing
  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])
  useEffect(() => { enabledRef.current = enabled }, [enabled])
  useEffect(() => { marketIdRef.current = marketId }, [marketId])

  const handlerRef = useRef<MessageHandler>(() => {})
  handlerRef.current = (data: unknown) => onMessageRef.current(data)

  const ctx = useContext(MarketSocketContext)

  useEffect(() => {
    if (!enabled || !marketId) return () => {}

    const statusHandler: MessageHandler = (data) => {
      const d = data as {type?: string; status?: WSStatus}
      if (d.type === "__ws_status__" && d.status) {
        setStatus(d.status)
      }
    }

    // Subscribe to both the user's message handler and status updates
    const unsub = ctx.subscribe(marketId, handlerRef.current)
    const unsubStatus = ctx.subscribe(marketId, statusHandler)

    // Set initial status
    setStatus(ctx.getStatus(marketId))

    return () => {
      unsub()
      unsubStatus()
    }
  }, [enabled, marketId, ctx]) // intentionally NOT including onMessage

  return { status }
}

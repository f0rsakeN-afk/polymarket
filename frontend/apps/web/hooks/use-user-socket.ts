"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { config } from "@/lib/config"
import { reconnectDelayMs } from "@/lib/ws-backoff"

export type WSStatus = "connecting" | "connected" | "disconnected" | "error"

type Listener = (data: unknown) => void

interface UseUserSocketOptions {
  userId: string
  onMessage: Listener
  enabled?: boolean
}

interface Subscriber {
  onMessage: Listener
  onStatus: (status: WSStatus) => void
}

/**
 * One socket per user, shared by every component that subscribes.
 *
 * This used to build a socket per hook instance, which produced two bugs. On
 * `/portfolio` the page and the notification bell both subscribe, so **two**
 * sockets opened, the server delivered every private frame to both, and each
 * consumer acted on it - so one event produced two notifications, and positions
 * and orders were refetched twice per frame. Two tabs apart, that same
 * duplication shows up inside a single tab.
 *
 * It also spent two of the gateway's per-IP and per-user connection budgets on
 * one browser tab, against caps measured at 50 per IP. A few open tabs could
 * exhaust the limit and start refusing sockets for reasons that have nothing to
 * do with the user.
 *
 * So the connection is a module-level resource keyed by user id, and components
 * subscribe to it. The first subscriber opens it; the last one closes it.
 */
interface SharedConnection {
  ws: WebSocket | null
  status: WSStatus
  subscribers: Set<Subscriber>
  retries: number
  /** Pending reconnect after a close. */
  retry: ReturnType<typeof setTimeout> | null
  /** Pending teardown after the last subscriber leaves. */
  linger: ReturnType<typeof setTimeout> | null
  /** Distinguishes a first connect (nothing to resync) from a reconnect. */
  everConnected: boolean
  recoveryBound: boolean
}

const connections = new Map<string, SharedConnection>()

/**
 * How long an idle socket is kept open with no subscribers.
 *
 * Not zero. Navigating between two private pages unmounts one consumer as the
 * next mounts, and tearing down immediately turns every route change into a fresh
 * handshake, a fresh resync and a fresh round of refetches. The window absorbs
 * that; much longer and we are only holding a connection nobody is using.
 */
const LINGER_MS = 2000

function createConnection(): SharedConnection {
  return {
    ws: null,
    status: "disconnected",
    subscribers: new Set(),
    retries: 0,
    retry: null,
    linger: null,
    everConnected: false,
    recoveryBound: false,
  }
}

/** Deliver a frame to every subscriber. */
function emit(conn: SharedConnection, data: unknown): void {
  for (const subscriber of [...conn.subscribers]) {
    try {
      subscriber.onMessage(data)
    } catch (error) {
      // One consumer throwing must not stop delivery to the rest, and must not
      // kill the socket. The failure belongs to that consumer alone; letting it
      // escape here would take every other subscriber's realtime data with it as
      // collateral. The component's own error boundary is the right place for it.
      console.error("[use-user-socket] subscriber threw while handling a frame", error)
    }
  }
}

function setStatus(conn: SharedConnection, status: WSStatus): void {
  if (conn.status === status) return
  conn.status = status
  for (const subscriber of [...conn.subscribers]) {
    try {
      subscriber.onStatus(status)
    } catch {
      /* a status render failing must not break the others' state updates */
    }
  }
}

function detach(ws: WebSocket): void {
  ws.onopen = null
  ws.onmessage = null
  ws.onclose = null
  ws.onerror = null
}

function open(conn: SharedConnection, userId: string): void {
  setStatus(conn, "connecting")

  // Auth: the access_token cookie is sent automatically on the handshake.
  const ws = new WebSocket(`${config.wsUrl}/ws/notifications/${userId}`)
  conn.ws = ws

  ws.onopen = () => {
    if (conn.ws !== ws) return // superseded while connecting
    setStatus(conn, "connected")
    conn.retries = 0
    // Tell every consumer its cached data may be behind. This is the only
    // catch-up available on a private feed: the channels are not sequenced, so
    // there is nothing to diff against and no way to notice a gap locally. Fills
    // that happened while the socket was down are simply gone, and without this
    // the page keeps rendering the position it had before.
    //
    // Reconnects only - on a first connect the queries have just run.
    if (conn.everConnected) {
      emit(conn, { type: "__ws_resync__", reason: "reconnect" })
    }
    conn.everConnected = true
  }

  ws.onmessage = (event) => {
    let data: unknown
    try {
      data = JSON.parse(event.data as string)
    } catch {
      return // a bad frame must not kill the socket
    }
    // Answer the server's heartbeat probe. This is the long-lived socket - a page
    // left open all day is the archetypal half-open connection - and the server
    // reaps anything silent past its pong deadline. Not replying is how a
    // healthy session gets disconnected for being quiet.
    const frame = data as { type?: string; ts?: number }
    if (frame?.type === "ping") {
      try {
        ws.send(JSON.stringify({ type: "pong", ts: frame.ts }))
      } catch {
        /* closing; onclose handles it */
      }
      return
    }
    emit(conn, data)
  }

  ws.onclose = () => {
    if (conn.ws !== ws) return
    conn.ws = null
    setStatus(conn, "disconnected")
    if (conn.subscribers.size === 0) return // nobody left to serve
    const delay = reconnectDelayMs(conn.retries)
    conn.retries++
    conn.retry = setTimeout(() => {
      conn.retry = null
      if (conn.subscribers.size > 0 && !conn.ws) open(conn, userId)
    }, delay)
  }

  ws.onerror = () => {
    // `onclose` always follows and owns the retry.
    ws.close()
  }
}

/**
 * Recover a socket that died *without* a close event.
 *
 * A suspended laptop, a NAT timeout or a network handover can leave the socket
 * dead while the browser still reports OPEN - no `close` event fires, so nothing
 * in the reconnect loop ever runs. `online` and tab focus are the only signals
 * the browser gives us.
 *
 * `force` distinguishes them. `online` means the network changed state, so
 * redial whatever the socket claims to be. Tab focus fires constantly, so it
 * only redials when there is something to replace or a retry to restart - but it
 * *does* replace a socket that still reports OPEN, because that is precisely the
 * half-dead state a suspended machine leaves behind and `readyState` cannot tell
 * it from a healthy one. One handshake per tab switch, against showing a
 * portfolio that missed fills.
 */
function bindRecovery(conn: SharedConnection, userId: string): void {
  if (conn.recoveryBound) return
  conn.recoveryBound = true

  const recover = (force: boolean) => {
    if (conn.subscribers.size === 0) return
    const retryPending = conn.retry !== null
    const hasSocket = conn.ws !== null
    if (!force && !hasSocket && !retryPending) return

    if (conn.retry) {
      clearTimeout(conn.retry)
      conn.retry = null
    }
    const ws = conn.ws
    if (ws) {
      // Detach first: `close()` is async, so this socket fires `close` after its
      // successor is live, and a live handler would queue another reconnect for a
      // socket already replaced.
      detach(ws)
      ws.close()
    }
    conn.ws = null
    conn.retries = 0
    open(conn, userId)
  }

  window.addEventListener("online", () => recover(true))
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") recover(false)
  })
}

function acquire(userId: string, subscriber: Subscriber): () => void {
  let conn = connections.get(userId)
  if (!conn) {
    conn = createConnection()
    connections.set(userId, conn)
  }
  if (conn.linger) {
    clearTimeout(conn.linger)
    conn.linger = null
  }

  conn.subscribers.add(subscriber)
  subscriber.onStatus(conn.status)
  bindRecovery(conn, userId)
  if (!conn.ws && !conn.retry) open(conn, userId)

  return () => {
    const current = connections.get(userId)
    if (!current) return
    current.subscribers.delete(subscriber)
    if (current.subscribers.size > 0) return

    // Nobody is listening, but do not tear down on the spot: see LINGER_MS.
    current.linger = setTimeout(() => {
      const live = connections.get(userId)
      if (!live || live.subscribers.size > 0) return
      connections.delete(userId)
      if (live.retry) clearTimeout(live.retry)
      const ws = live.ws
      live.ws = null
      live.status = "disconnected"
      if (ws) {
        detach(ws)
        ws.close()
      }
    }, LINGER_MS)
  }
}

export function useUserSocket({ userId, onMessage, enabled = true }: UseUserSocketOptions) {
  const [status, setStatusState] = useState<WSStatus>("disconnected")

  // Held in a ref so a new inline callback on every render does not churn the
  // registry: the effect below keys off identity, and an unstable handler would
  // unsubscribe and resubscribe on each render.
  const handlerRef = useRef(onMessage)
  useEffect(() => {
    handlerRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    // No setState here: a synchronous update inside an effect forces a second
    // render pass. The disabled case is derived at the return instead, which is
    // both cheaper and impossible to get out of step with `enabled`.
    if (!enabled || !userId) return

    const subscriber: Subscriber = {
      onMessage: (data) => handlerRef.current(data),
      onStatus: setStatusState,
    }
    return acquire(userId, subscriber)
  }, [userId, enabled])

  const send = useCallback(
    (data: unknown) => {
      const ws = connections.get(userId)?.ws
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data))
    },
    [userId]
  )

  return { status: enabled && userId ? status : "disconnected", send }
}
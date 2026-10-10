"use client"

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { config } from "@/lib/config"
import { reconnectDelayMs } from "@/lib/ws-backoff"

export type WSStatus = "connecting" | "connected" | "disconnected" | "error"

type MessageHandler = (data: unknown) => void

/** Synthetic frame: frames were demonstrably lost for this market. */
export const WS_GAP = "__ws_gap__"
/** Synthetic frame: state may be stale, refetch from REST. */
export const WS_RESYNC = "__ws_resync__"
/** Synthetic frame: connection status transition (never sent by the server). */
export const WS_STATUS = "__ws_status__"

/**
 * How long a tab may stay hidden before we assume it missed something.
 *
 * A background tab keeps its socket, so nothing looks broken - but the browser
 * may freeze timers, the OS may suspend the machine, or the network may have
 * quietly swapped underneath it. Come back after an hour and the UI is
 * confidently rendering whatever the last frame said. One cheap invalidation on
 * return is the difference between "live" and "live, as of this morning".
 */
const RESYNC_AFTER_HIDDEN_MS = 60_000

// ─── Per-market subscription state ─────────────────────────────────────────────

interface MarketSub {
  /** Sequence number • incrementing counter used to discard stale messages */
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
  /** Per-market mutex • serialises the subscribe frame for one market.
   *  A promise chain, not a boolean: `Map<string, Promise<void>>`. */
  subLocks: Map<string, Promise<void>>
  retries: number
  reconnectTimer: ReturnType<typeof setTimeout> | null
  /** All markets this WS is subscribed to on the server (re-subscribed on reconnect) */
  serverSubs: Set<string>
  /** Set of status-change handlers */
  statusHandlers: Set<MessageHandler>
  /** Market used in WS URL • the most recently active market for reconnect path */
  lastConnectedMarket: string | null
  /** The socket being closed on purpose • its `onclose` must not queue a reconnect */
  intentionalCloseSocket: WebSocket | null
  /** Deferred "registry is empty, close the socket" timer (see the unsubscribe path) */
  closeTimer: ReturnType<typeof setTimeout> | null
  /** Highest server `seq` seen per market • the proof that nothing went missing.
   *  `undefined` means "nothing received yet", which is not the same as zero:
   *  the first frame establishes a baseline and is never treated as a gap. */
  lastSeq: Map<string, number>
  /** Has this connection ever reached `open`? Separates a first connect (React
   *  Query has just fetched, nothing owed) from a reconnect (frames were missed
   *  for certain and a resync is owed even if the market never trades again). */
  everConnected: boolean
  /** When the tab last went to background • drives the return-from-hidden resync */
  hiddenSince: number | null
}

// Module-level singleton • one WebSocket per browser tab
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
      intentionalCloseSocket: null,
      closeTimer: null,
      lastSeq: new Map(),
      everConnected: false,
      hiddenSince: null,
    }
  }
  return _conn
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

function setStatus(conn: SharedConnection, status: WSStatus) {
  conn.status = status
  for (const h of conn.statusHandlers) {
    try { h({ type: WS_STATUS, status }) } catch { /* ignore */ }
  }
}

/** Fan a frame out to every handler registered for one market.
 *
 * Each handler is isolated: one throwing must not stop the others, and must
 * never take the socket down with it.
 */
function deliverToMarket(conn: SharedConnection, marketId: string, data: unknown) {
  const sub = conn.subs.get(marketId)
  if (!sub) return
  sub.seq++
  const currentSeq = sub.seq
  for (const h of sub.handlers) {
    try {
      h(data)
    } catch {
      /* user handler threw • socket survives */
    }
    // If seq changed while iterating, a re-subscribe happened • stop delivering
    // stale messages from before the re-subscribe
    if (sub.seq !== currentSeq) break
  }
}

/** Tell every handler on a market that its cached state may be behind. */
function emitResync(conn: SharedConnection, marketId: string, reason: string) {
  deliverToMarket(conn, marketId, {
    type: WS_RESYNC,
    market_id: marketId,
    reason,
  })
}

/**
 * Detect frames the client provably never received and ask for a repair.
 *
 * The server stamps every market frame with a per-market monotonic `seq`. A
 * jump larger than one means frames went missing somewhere between Redis and
 * this tab - a reconnect window, a Redis blip, a send that timed out. That used
 * to be invisible: nothing carried a sequence number, the local `sub.seq` was a
 * receive counter rather than a server one, and the gap check that existed could
 * never fire. So a client could sit on a stale orderbook indefinitely, looking
 * perfectly healthy, on a market that had simply gone quiet since.
 *
 * Detection is the point; the repair is a plain REST refetch, because the
 * database is the source of truth and replaying the socket would only reproduce
 * the same gap.
 */
/**
 * Compare the server's advertised position against ours, and repair anything
 * behind.
 *
 * `checkForGap` can only ever see a hole when a later frame shows up to reveal
 * it. On a market that trades once and then goes quiet - resolved, closed, or
 * simply calm - no later frame arrives, so a genuine loss stays invisible and
 * the page renders pre-loss state indefinitely while reporting itself
 * connected. This is the server telling us directly rather than the client
 * inferring, so it is exact rather than a "it's been quiet a while, refetch
 * just in case" heuristic that would fire on healthy quiet markets too.
 *
 * Anything at or ahead of us is left alone. The server's mark is per-node, so a
 * socket that just landed on this node can legitimately be behind without
 * having lost anything - it was never on the previous node.
 */
function reconcileAgainstBeacon(conn: SharedConnection, serverSeq: Record<string, number>) {
  for (const [marketId, serverAt] of Object.entries(serverSeq)) {
    const ours = conn.lastSeq.get(marketId)
    // No baseline for this market means we have not received anything for it
    // yet. That is "arrived late", not "lost", and re-fetching would be theatre.
    if (ours === undefined) continue
    // Never move backwards: the beacon may come from a node that joined the
    // channel earlier than ours.
    if (serverAt > ours) {
      if (process.env.NODE_ENV !== "production") {
        console.warn(
          `[ws] missed ${serverAt - ours} frame(s) on market ${marketId} (we are at ${ours}, server at ${serverAt}) • resyncing`
        )
      }
      // Advance the baseline to the server's position. The frames in between are
      // gone; pretending otherwise would make every subsequent frame look
      // contiguous again.
      conn.lastSeq.set(marketId, serverAt)
      emitResync(conn, marketId, "beacon")
    }
  }
}

/**
 * Detect frames the client provably never received and ask for a repair.
 *
 * The server stamps every market frame with a per-market monotonic `seq`. A
 * jump larger than one means frames went missing somewhere between Redis and
 * this tab - a reconnect window, a Redis blip, a send that timed out. That used
 * to be invisible: nothing carried a sequence number, the local `sub.seq` was a
 * receive counter rather than a server one, and the gap check that existed could
 * never fire. So a client could sit on a stale orderbook indefinitely, looking
 * perfectly healthy, on a market that had simply gone quiet since.
 *
 * This covers loss that is *followed* by more traffic. Loss on a market that
 * then goes quiet needs the server's own account of where the stream reached,
 * which is what `reconcileAgainstBeacon` is for - the two are complementary and
 * neither subsumes the other.
 *
 * Detection is the point; the repair is a plain REST refetch, because the
 * database is the source of truth and replaying the socket would only reproduce
 * the same gap.
 */
function checkForGap(conn: SharedConnection, marketId: string, seq: number) {
  const prev = conn.lastSeq.get(marketId)
  if (prev === undefined) {
    // First frame on this subscription: establish a baseline, never a gap.
    conn.lastSeq.set(marketId, seq)
    return
  }
  if (seq <= prev) {
    // Duplicate or reordered delivery. Harmless, and must not move the
    // baseline backwards.
    return
  }
  if (seq > prev + 1) {
    const missing = seq - prev - 1
    conn.lastSeq.set(marketId, seq)
    if (process.env.NODE_ENV !== "production") {
      console.warn(
        `[ws] ${missing} frame(s) lost for market ${marketId} (seq ${prev} -> ${seq}) • resyncing`
      )
    }
    emitResync(conn, marketId, "gap")
    return
  }
  conn.lastSeq.set(marketId, seq)
}

function sendWs(conn: SharedConnection, data: unknown) {
  if (conn.ws?.readyState === WebSocket.OPEN) {
    conn.ws.send(JSON.stringify(data))
  }
}

/** Serialise work per market via a promise chain.
 *
 * The previous version was a spin-wait:
 *
 *   while (locked) { await new Promise(r => setTimeout(r, 5)); locked = ... }
 *
 * which burns a 5 ms timer per contended market and busy-waits the event loop
 * for the whole duration. Chaining onto the previous promise instead costs one
 * microtask turn, never a timer, and cannot starve anything else.
 *
 * Failures must not poison the chain • hence `.catch()` on both the tail and the
 * stored promise, so one throwing caller doesn't deadlock every later one.
 */
function withMarketLock<T>(conn: SharedConnection, marketId: string, fn: () => T): Promise<T> {
  const prev = conn.subLocks.get(marketId) ?? Promise.resolve()
  const run = prev.then(fn, fn) // run regardless of how the previous link settled
  const tail = run.then(
    () => undefined,
    () => undefined
  )
  conn.subLocks.set(marketId, tail)
  // Drop the entry once this is the tail, so the Map doesn't grow unbounded.
  void tail.then(() => {
    if (conn.subLocks.get(marketId) === tail) conn.subLocks.delete(marketId)
  })
  return run
}

/** Subscribe to a market on the wire. Idempotent: `wsSubscribed` short-circuits,
 *  so the flag is the real guard and the lock only prevents two callers in the
 *  same tick from both passing that check.
 *
 *  Note there is deliberately NO `readyState === OPEN` check here. If a second
 *  market is subscribed while the socket is still CONNECTING, `sendWs` no-ops •
 *  but we must still record it in `serverSubs`, because `onopen` replays that
 *  set. Returning early here instead would drop that market permanently: the
 *  URL only ever names the *first* market. */
function wsSubscribe(conn: SharedConnection, marketId: string): Promise<void> {
  return withMarketLock(conn, marketId, () => {
    const sub = conn.subs.get(marketId)
    if (!sub || sub.wsSubscribed) return // already sent, or nobody left to send for
    sendWs(conn, { type: "subscribe", market_id: marketId })
    sub.wsSubscribed = true
    conn.serverSubs.add(marketId)
  })
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

  // No auth gate here, deliberately. Market data is public over REST
  // (`/markets/{slug}/orderbook`, `/markets/{slug}/trades`) and this socket pushes
  // exactly that, so the server accepts an anonymous handshake. Gating the client
  // on a session would deny live prices to logged-out visitors • who can already
  // read the same numbers over HTTP. The `access_token` cookie rides along
  // automatically when there is a session, which is all the server needs it for.
  //
  // Clear any pending reconnect timer • prevents duplicate connections on rapid calls
  if (conn.reconnectTimer) {
    clearTimeout(conn.reconnectTimer)
    conn.reconnectTimer = null
  }
  // A pending deferred close is now moot • something asked for a socket.
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

    // A reconnect means frames were missed for certain. Announce it even when
    // the market never trades again - which is the case gap detection cannot
    // cover, because a gap is only *observable* once a later frame arrives, and
    // on a quiet market no later frame ever does. Without this the tab
    // reconnects successfully and then renders whatever it had before the drop,
    // indefinitely, with a green "live" indicator.
    if (conn.everConnected) {
      for (const marketId of conn.subs.keys()) {
        emitResync(conn, marketId, "reconnect")
      }
    }
    conn.everConnected = true
  }

  ws.onmessage = (event) => {
    let data: unknown
    try {
      data = typeof event.data === "string" ? JSON.parse(event.data) : event.data
    } catch {
      return  // ignore unparseable
    }

    const d = data as {
      market_id?: string
      type?: string
      seq?: number
      ts?: number
      // Heartbeat beacons carry the server's per-market high-water mark.
      serverSeq?: Record<string, number>
    }

    // Server heartbeat probe. Handled *before* the `market_id` check below,
    // because a ping carries no market id and that guard used to drop it
    // silently - which meant the client never once answered, so the server had
    // no way to tell a live socket from a half-open one and eventually reaped
    // healthy connections. Refusing to answer is a self-inflicted disconnect.
    if (d.type === "ping") {
      // The probe also says where the server's stream has reached. Comparing it
      // against our own position is what closes the one hole client-side gap
      // detection cannot: a loss is only observable when a *later* frame arrives,
      // so on a market that trades once and then goes quiet, frames lost in
      // between are invisible forever - stale UI, indicator reading "connected",
      // nothing ever correcting it. Here the server tells us directly.
      if (d.serverSeq) reconcileAgainstBeacon(conn, d.serverSeq)
      try {
        ws.send(JSON.stringify({ type: "pong", ts: d.ts }))
      } catch { /* socket closing; onclose handles it */ }
      return
    }

    if (!d.market_id) return

    // `__ws_status__`, `__ws_resync__` and `__ws_gap__` are synthetic frames
    // this module produces itself and pushes straight to handlers, so they can
    // never arrive here. Guarding on them keeps that invariant from rotting into
    // a real dispatch if the registries are ever unified.
    if (d.type === WS_STATUS || d.type === WS_RESYNC || d.type === WS_GAP) return

    if (!conn.subs.has(d.market_id)) return  // no handler registered • discard

    // Proven-loss check, before delivery: the repair frame is dispatched from
    // inside here, so it must not be entangled with this frame's own delivery.
    if (typeof d.seq === "number") {
      checkForGap(conn, d.market_id, d.seq)
    }

    deliverToMarket(conn, d.market_id, data)
  }

  ws.onclose = () => {
    // A superseded socket must not touch shared state. `close()` is async, so a
    // socket we already replaced fires `onclose` *after* its successor is live;
    // nulling `conn.ws` unconditionally here made the live socket untracked, and
    // the next subscribe opened a second one • two sockets, both receiving, and
    // the flap repeated on every subscribe/unsubscribe cycle.
    if (conn.ws !== ws) return
    conn.ws = null
    setStatus(conn, "disconnected")

    // Closed on purpose (last subscriber left) • the reconnect loop must stay
    // parked until something actually asks for a socket.
    if (conn.intentionalCloseSocket === ws) {
      conn.intentionalCloseSocket = null
      conn.everConnected = false
      return
    }

    // Never give up. The old loop parked itself after 8 attempts and only
    // recovered on `online` / tab focus - two signals the browser may never
    // send. A laptop that sleeps with the network down, or a deploy that
    // bounces the backend, left the tab permanently dead with a plausible-looking
    // UI and no way back. The delay is capped, so this is at most one attempt
    // every 30s, and `everConnected` stays true so the next successful connect
    // triggers a resync for everything missed while we were away.
    const delay = reconnectDelayMs(conn.retries)
    conn.retries++
    // Reconnect to the market the user is currently viewing • not the first subscribed
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
  /**
   * Subscribe to *connection status* changes.
   *
   * Deliberately not the same channel as `subscribe`. Status frames are
   * synthetic • `setStatus` pushes `{type:"__ws_status__"}` into
   * `conn.statusHandlers` and the server never sends that type • so a status
   * handler registered through `subscribe` lands in `subs[marketId].handlers`,
   * which is only ever drained by `ws.onmessage`. It would therefore never fire.
   */
  subscribeStatus: (handler: MessageHandler) => () => void
}

const NOOP_SUBSCRIBE = () => () => {}
const NOOP_GET_STATUS = () => "disconnected" as WSStatus
const NOOP_SUBSCRIBE_STATUS = () => () => {}

const MarketSocketContext = createContext<MarketSocketCtx>({
  subscribe: NOOP_SUBSCRIBE,
  getStatus: NOOP_GET_STATUS,
  subscribeStatus: NOOP_SUBSCRIBE_STATUS,
})

export function MarketSocketProvider({ children }: { children: React.ReactNode }) {
  const conn = useRef<SharedConnection>(getConnection())

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
      // WS is open • subscribe on the wire if not already
      wsSubscribe(c, marketId)
    }

    // Return unsubscribe
    return () => {
      const currentSub = c.subs.get(marketId)
      if (!currentSub) return

      currentSub.handlers.delete(handler)

      // Last handler for this market gone • unsubscribe from it on the wire
      if (currentSub.handlers.size === 0) {
        c.subs.delete(marketId)
        c.subLocks.delete(marketId)  // ponytail: prevent subLocks Map leak
        // Forget the sequence baseline with the subscription. Keeping it would
        // make the next visit to this market look like a huge gap on its very
        // first frame - technically true, but it would fire a pointless resync
        // for a market the client has not seen a single frame of yet.
        c.lastSeq.delete(marketId)
        wsUnsubscribe(c, marketId)

        // If all markets desubscribed, close the WS • but not synchronously.
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

  // Status lives in its own registry • see the `subscribeStatus` doc comment.
  const subscribeStatus = useCallback((handler: MessageHandler) => {
    const c = conn.current
    c.statusHandlers.add(handler)
    // Seed with the current value: a late subscriber must not sit at the
    // initialiser's stale reading until the next transition happens.
    handler({ type: WS_STATUS, status: c.status })
    return () => {
      c.statusHandlers.delete(handler)
    }
  }, [])

  const ctxValue = useMemo(
    () => ({ subscribe, getStatus, subscribeStatus }),
    [subscribe, getStatus, subscribeStatus]
  )

  // NOTE: there is deliberately no "re-render the provider on status change"
  // effect here any more. It existed because the hook could not observe status
  // itself, so a provider re-render was the only way to propagate it. Hooks now
  // call `subscribeStatus` and hold their own state, so re-rendering the whole
  // subtree twice per connect cycle (connecting → connected) was pure cost.

  // Recover a sleeping or wedged socket when the browser says the world changed.
/// A laptop resuming from sleep drops the socket silently - `online` and
  // `visibilitychange` are the only signals the browser gives us.
  useEffect(() => {
    const c = conn.current

    const recover = () => {
      if (!c.subs.size) return
      if (c.ws && c.ws.readyState <= WebSocket.OPEN) return  // still healthy
      c.retries = 0
      if (c.reconnectTimer) {
        clearTimeout(c.reconnectTimer)
        c.reconnectTimer = null
      }
      const market = c.lastConnectedMarket ?? c.subs.keys().next().value
      if (market) connect(c, market)
    }

    // Coming back to a long-hidden tab is its own failure mode. The socket may
    // still read OPEN - the browser keeps it in the background - so `recover`
    // does nothing, yet the page may have missed anything that happened while
    // it was frozen or suspended. Measure the hidden period and, if it was long
    // enough to have missed a frame, invalidate what we are showing.
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        c.hiddenSince = Date.now()
        return
      }
      const hiddenFor = c.hiddenSince ? Date.now() - c.hiddenSince : 0
      c.hiddenSince = null
      recover()
      if (hiddenFor >= RESYNC_AFTER_HIDDEN_MS) {
        for (const marketId of c.subs.keys()) {
          emitResync(c, marketId, "visible")
        }
      }
    }

    window.addEventListener("online", recover)
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      window.removeEventListener("online", recover)
      document.removeEventListener("visibilitychange", onVisibility)
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
  // `onMessage` is almost always an inline arrow, so keeping it in a ref is what
  // stops the subscribe effect below from re-running on every parent render.
  const onMessageRef = useRef(onMessage)
  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])

  useEffect(() => {
    if (!enabled || !marketId) return () => {}

    const statusHandler: MessageHandler = (data) => {
      const d = data as { type?: string; status?: WSStatus }
      if (d.type === WS_STATUS && d.status) setStatus(d.status)
    }

    const unsubMsg = ctx.subscribe(marketId, (data) => onMessageRef.current(data))
    // Status via the status registry, NOT `ctx.subscribe`. Going through
    // `subscribe` put this handler in `subs[marketId].handlers`, which only
    // `ws.onmessage` drains • and the server never sends `__ws_status__`, so the
    // indicator never updated. It sat at whatever `getStatus()` returned on
    // mount, which is exactly the kind of bug that looks fine in a demo because
    // the first state you see is usually correct.
    const unsubStatus = ctx.subscribeStatus(statusHandler)

    return () => {
      unsubMsg()
      unsubStatus()
    }
  }, [enabled, marketId, ctx])

  return { status }
}

// ─── Teardown: HMR + page unload ───────────────────────────────────────────────
//
// `_conn` is module scope, which is what makes the socket per-tab rather than
// per-component • but it also means nothing tears it down when the module is
// replaced or the page goes away:
//
//  - **HMR (dev):** reloading this module creates a *new* `_conn = null` while
//    the old socket is still open and still referenced by the old module's
//    closures. The browser keeps the TCP connection and the server keeps the
//    file descriptor and the per-IP counter slot. A handful of edits and you've
//    leaked several sockets the app can no longer reference • and the server
//    will eventually refuse new connections for that IP.
//  - **Unload:** bfcache navigation away and back restores the page, but a
//    socket closed by the server while hidden is never noticed until the first
//    send fails, so the UI sits there "connected" and silently dead.
//
// Both handlers close explicitly instead of trusting TCP teardown.

function teardownSocket(reason: "hmr" | "unload"): void {
  const c = _conn
  if (!c) return

  // Clear timers unconditionally • a pending reconnect would otherwise resurrect
  // the socket after we deliberately closed it.
  if (c.closeTimer) clearTimeout(c.closeTimer)
  if (c.reconnectTimer) clearTimeout(c.reconnectTimer)

  // The socket is the only part that must die. Clearing `subs` and
  // `serverSubs` here would strand every mounted consumer: the provider's
  // `useRef` still holds this object, so consumers would keep their handlers
  // while the socket they route through was gone • silent dead updates. Instead
  // drop `ws` only; the next `subscribe` sees `!c.ws` and calls `connect()`, so
  // recovery happens through the normal path rather than a second code path.
  const ws = c.ws
  c.ws = null
  c.serverSubs.clear()
  c.subs.clear()
  c.lastSeq.clear()
  c.lastConnectedMarket = null
  c.everConnected = false
  c.hiddenSince = null
  c.retries = 0

  if (!ws) return
  c.intentionalCloseSocket = ws // our own close must not queue a reconnect
  try {
    ws.close(1000, reason)
  } catch {
    /* already closing */
  }

  // Only null the module singleton on HMR. On `pagehide` we must keep it: the
  // provider captured this exact object in a ref, so replacing the module
  // variable would leave the provider pointing at a dead connection while any
  // newly-mounted component got a fresh, second one • two connections, one of
  // them orphaned, which is the flapping this whole design avoids.
  if (reason === "hmr") _conn = null
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => teardownSocket("unload"))
}

// Vite/Turbopack HMR dispose hook. Guarded: this file is also read by tooling
// that has no `import.meta.hot`, and referencing it would throw at module load.
const hot = (import.meta as { hot?: { dispose: (cb: () => void) => void } }).hot
if (hot?.dispose) {
  hot.dispose(() => teardownSocket("hmr"))
}

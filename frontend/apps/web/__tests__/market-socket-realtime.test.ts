/**
 * Realtime regressions on the client half.
 *
 * The server now stamps every market frame with a per-market monotonic `seq`.
 * These tests pin the behaviour that makes that useful - a client that can prove
 * it missed something and repairs itself instead of quietly going stale - plus
 * the two properties the whole reconnect story rests on: the socket answers the
 * heartbeat, and it never gives up.
 *
 * Unlike most of the other socket tests these exercise the *real* hook, because
 * the bugs pinned here live in the message dispatch and the reconnect loop, and
 * a mock of the hook cannot test either.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { MarketSocketProvider, useMarketSocket } from "@/hooks/use-market-socket"

// ── Fake WebSocket ───────────────────────────────────────────────────────────

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  static CLOSED = 3
  static latest(): FakeWebSocket {
    return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]!
  }

  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  readyState = 1
  sent: string[] = []
  closed = false

  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }

  open() {
    this.onopen?.()
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.closed = true
    this.readyState = 3
  }
  /** Deliver a frame from the server. */
  emit(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }
  /** A clean close from the server. */
  drop() {
    this.readyState = 3
    this.onclose?.()
  }
}

let received: Array<Record<string, unknown>>
const handler = (data: unknown) => {
  received.push(data as Record<string, unknown>)
}

/**
 * Mount the hook inside its provider - `useMarketSocket` needs the real context.
 *
 * A fixed pair of hook calls rather than a loop over `marketIds`: rules-of-hooks
 * is right that a hook in a loop is a bug, and a test helper is not somewhere to
 * teach the opposite. Two markets is all the independence test needs.
 */
function mountFirst() {
  return renderHook(
    () => useMarketSocket({ marketId: "mkt-1", onMessage: handler, enabled: true }),
    { wrapper: MarketSocketProvider }
  )
}

function mountTwoMarkets() {
  return renderHook(
    () => {
      const a = useMarketSocket({ marketId: "mkt-a", onMessage: handler, enabled: true })
      const b = useMarketSocket({ marketId: "mkt-b", onMessage: handler, enabled: true })
      return { a: a.status, b: b.status }
    },
    { wrapper: MarketSocketProvider }
  )
}

const resyncs = () => received.filter((m) => m.type === "__ws_resync__")

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.instances = []
  received = []
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket)
})

afterEach(() => {
  // The connection is a module-level singleton, so it outlives the component.
  // Unmount first, then fire the teardown the hook registers for `pagehide` to
  // drop its registry - otherwise the next test inherits live subscriptions and
  // its handlers.
  cleanup()
  window.dispatchEvent(new Event("pagehide"))
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

/** Advance past the capped backoff and let any queued reconnect run. */
function tick() {
  act(() => {
    vi.advanceTimersByTime(30_000)
  })
}

// ── Heartbeat ────────────────────────────────────────────────────────────────

describe("heartbeat", () => {
  it("answers a server ping with a pong", () => {
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "ping", ts: 12345 }))

    const pongs = ws.sent.map((s) => JSON.parse(s)).filter((m) => m.type === "pong")
    expect(pongs).toHaveLength(1)
    expect(pongs[0].ts).toBe(12345)
  })

  it("answers a ping that carries no market_id", () => {
    // The server's heartbeat is exactly this shape. A `market_id` guard placed
    // ahead of the ping check - which is what the hook used to do - drops it
    // silently, so the client never once replies and the server eventually
    // reaps a healthy socket for being quiet.
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "ping", ts: 1 }))

    expect(ws.sent.some((s) => JSON.parse(s).type === "pong")).toBe(true)
  })

  it("does not route a ping to the market's message handlers", () => {
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "ping", ts: 1 }))

    expect(received.some((m) => m.type === "ping")).toBe(false)
  })
})

// ── Server beacons ───────────────────────────────────────────────────────────
//
// The hole in pure client-side gap detection: a gap is only observable when a
// *later* frame arrives. Frames lost on a market that then goes quiet are
// invisible forever - stale UI, indicator reading "connected", nothing ever
// correcting it. The heartbeat carries the server's position so the client does
// not have to infer it from its own arrival pattern.

describe("server sequence beacon", () => {
  it("asks for a resync when the server is ahead of us", () => {
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    // We received seq 10.
    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 10 }))
    // The market then goes quiet, so no further frame ever reveals the gap.
    // The heartbeat says the server is at 13.
    act(() => ws.emit({ type: "ping", ts: 1, serverSeq: { "mkt-1": 13 } }))

    const out = resyncs()
    expect(out).toHaveLength(1)
    expect(out[0]!.reason).toBe("beacon")
    expect(out[0]!.market_id).toBe("mkt-1")
  })

  it("stays quiet when the server agrees with us", () => {
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 10 }))
    act(() => ws.emit({ type: "ping", ts: 1, serverSeq: { "mkt-1": 10 } }))
    act(() => ws.emit({ type: "ping", ts: 2, serverSeq: { "mkt-1": 10 } }))

    // A healthy socket must not refetch every 30 seconds.
    expect(resyncs()).toHaveLength(0)
  })

  it("never resyncs a market it has received nothing for", () => {
    // No baseline means "arrived late", not "lost". The beacon omits markets the
    // node has not fanned out for, and a market we have never seen a frame of is
    // not behind - it is early. Re-fetching here would be theatre.
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "ping", ts: 1, serverSeq: { "mkt-1": 500 } }))

    expect(resyncs()).toHaveLength(0)
  })

  it("never moves our baseline backwards", () => {
    // The beacon is per-node. A socket that just landed on a node which joined
    // the channel earlier can legitimately see a lower number there, and
    // treating that as a gap would fire a resync on every fresh subscription.
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 50 }))
    act(() => ws.emit({ type: "ping", ts: 1, serverSeq: { "mkt-1": 20 } }))

    expect(resyncs()).toHaveLength(0)

    // And the baseline is intact: a contiguous next frame is not a new hole.
    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 51 }))
    expect(resyncs()).toHaveLength(0)
  })

  it("does not re-fire for a hole the beacon already reported", () => {
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 10 }))
    act(() => ws.emit({ type: "ping", ts: 1, serverSeq: { "mkt-1": 13 } }))
    // Next heartbeat, nothing new happened.
    act(() => ws.emit({ type: "ping", ts: 2, serverSeq: { "mkt-1": 13 } }))

    expect(resyncs()).toHaveLength(1)
  })

  it("handles a beacon for one market without disturbing the others", () => {
    mountTwoMarkets()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => {
      ws.emit({ type: "market:price_update", market_id: "mkt-a", seq: 10 })
      ws.emit({ type: "market:price_update", market_id: "mkt-b", seq: 10 })
    })
    act(() => ws.emit({ type: "ping", ts: 1, serverSeq: { "mkt-a": 10, "mkt-b": 99 } }))

    const out = resyncs()
    expect(out).toHaveLength(1)
    expect(out[0]!.market_id).toBe("mkt-b")
  })

  it("tolerates a ping with no beacon at all", () => {
    // A socket with no sequenced traffic yet gets a bare ping.
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "ping", ts: 1 }))

    expect(resyncs()).toHaveLength(0)
    expect(ws.sent.some((s) => JSON.parse(s).type === "pong")).toBe(true)
  })
})

// ── Gap detection ────────────────────────────────────────────────────────────

describe("sequence gaps", () => {
  it("accepts a contiguous sequence silently", () => {
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => {
      ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 1, yes_price: 0.5 })
      ws.emit({ type: "trade:new", market_id: "mkt-1", seq: 2 })
      ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 3, yes_price: 0.6 })
    })

    expect(resyncs()).toHaveLength(0)
    expect(received.filter((m) => m.type === "market:price_update")).toHaveLength(2)
  })

  it("treats the first frame as a baseline, never as a gap", () => {
    // A market busy for hours sends seq 4002 to a client that has seen nothing.
    // That is not loss, it is the client arriving late.
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 4002, yes_price: 0.5 }))

    expect(resyncs()).toHaveLength(0)
  })

  it("asks for a resync when frames are provably missing", () => {
    // seq 1 then seq 5: three frames went somewhere between Redis and this tab.
    // Before sequencing existed the client had no way to know, so it rendered a
    // book missing those trades and nothing ever corrected it.
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 1 }))
    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 5 }))

    const out = resyncs()
    expect(out).toHaveLength(1)
    expect(out[0]!.reason).toBe("gap")
    expect(out[0]!.market_id).toBe("mkt-1")
  })

  it("does not resync twice for the same hole", () => {
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 1 }))
    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 5 }))
    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 6 }))

    // The baseline advanced, so the next contiguous frame is not a new hole.
    expect(resyncs()).toHaveLength(1)
  })

  it("ignores a duplicated frame without resyncing or moving the baseline", () => {
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 1 }))
    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 1 }))
    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", seq: 2 }))

    expect(resyncs()).toHaveLength(0)
  })

  it("tracks each market's sequence independently", () => {
    // One shared baseline would report every carousel item as gapped whenever
    // any single one of them jumped.
    mountTwoMarkets()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => {
      ws.emit({ type: "market:price_update", market_id: "mkt-a", seq: 10 })
      ws.emit({ type: "market:price_update", market_id: "mkt-b", seq: 3 })
      ws.emit({ type: "market:price_update", market_id: "mkt-a", seq: 11 })
      ws.emit({ type: "market:price_update", market_id: "mkt-b", seq: 4 })
    })

    expect(resyncs()).toHaveLength(0)
  })

  it("tolerates frames from before sequencing existed", () => {
    // A frame with no `seq` is simply delivered; "unknown" is not "lost".
    mountFirst()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "market:price_update", market_id: "mkt-1", yes_price: 0.5 }))

    expect(resyncs()).toHaveLength(0)
    expect(received.some((m) => m.type === "market:price_update")).toBe(true)
  })
})

// ── Reconnect ────────────────────────────────────────────────────────────────

describe("reconnect", () => {
  it("asks for a resync after a reconnect, but not on first connect", () => {
    // Gap detection cannot cover a market that went quiet after the drop: a gap
    // is only observable once a later frame arrives, and on a quiet market none
    // ever does. Without an explicit resync the tab reconnects successfully and
    // then shows pre-drop state forever, with a green "live" indicator.
    mountFirst()
    const first = FakeWebSocket.latest()
    act(() => first.open())
    act(() => first.drop())

    expect(resyncs()).toHaveLength(0)

    tick()
    act(() => FakeWebSocket.latest().open())

    const out = resyncs()
    expect(out.length).toBeGreaterThan(0)
    expect(out[0]!.reason).toBe("reconnect")
  })

  it("keeps retrying rather than giving up", () => {
    // The old loop parked itself after 8 attempts and only resumed on `online`
    // or a tab focus - neither guaranteed by the browser - so a feed lost to a
    // sleeping laptop or a deploy stayed dead for the rest of the session while
    // the UI still looked healthy.
    mountFirst()

    for (let i = 0; i < 20; i++) {
      tick()
      act(() => FakeWebSocket.latest().drop())
    }

    expect(FakeWebSocket.instances.length).toBeGreaterThan(12)
  })

  it("re-subscribes every market after reconnecting", () => {
    // The socket URL only ever names the first market, so anything else the
    // page cares about has to be re-asked for explicitly.
    mountTwoMarkets()
    const first = FakeWebSocket.latest()
    act(() => first.open())
    act(() => first.emit({ type: "market:price_update", market_id: "mkt-a", seq: 1 }))
    act(() => first.drop())

    tick()
    const second = FakeWebSocket.latest()
    act(() => second.open())

    const subs = second.sent.map((s) => JSON.parse(s)).filter((m) => m.type === "subscribe")
    const markets = subs.map((m) => m.market_id)
    expect(markets).toContain("mkt-a")
    expect(markets).toContain("mkt-b")
  })
})
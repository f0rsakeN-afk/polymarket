/**
 * The grid protocol: one subscription, one aggregated frame.
 *
 * The naive implementation - one subscription per visible market - costs a
 * subscription slot per card against a hard per-connection cap, and puts one
 * frame per market per tick on the wire. Thirty live cards means thirty frames
 * and thirty re-renders a second, which is how a realtime page ends up slower
 * than the static one it replaced. Client-side coalescing cannot fix that: the
 * frames have already arrived.
 *
 * So the server aggregates. These tests pin the client half of that contract -
 * including the parts that fail silently if they regress: batches carrying no
 * top-level `market_id`, and reconnect losing the declaration.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { MarketSocketProvider, useMarketGrid, useMarketSocket } from "@/hooks/use-market-socket"

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  static latest(): FakeWebSocket {
    return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]!
  }

  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  /** CONNECTING, as a real socket is at construction. */
  readyState = 0
  sent: string[] = []

  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }
  open() { this.readyState = 1; this.onopen?.() }
  send(d: string) { this.sent.push(d) }
  close() { this.readyState = 3 }
  emit(o: unknown) { this.onmessage?.({ data: JSON.stringify(o) }) }
  drop() { this.readyState = 3; this.onclose?.() }
  /** Frames of a given protocol type sent to the server. */
  frames(type: string) {
    return this.sent.map((s) => JSON.parse(s)).filter((m) => m.type === type)
  }
}

let batches: Array<Record<string, Record<string, unknown>>>

/**
 * Mount a grid.
 *
 * `useMarketGrid` does not itself open the tab's socket - it is a *second*
 * consumer of the connection that `useMarketSocket` establishes, and the shared
 * singleton is only created when something asks for a market subscription. So a
 * grid-only page has to be opened the way production opens it: the connection
 * exists (from a market page, or the first per-market subscription) and the grid
 * attaches to it.
 *
 * Getting this wrong is not hypothetical: a grid whose socket never opened would
 * silently declare nothing and never update, which looks exactly like a broken
 * server.
 */
const mount = (marketIds: string[]) =>
  renderHook(
    () => {
      // Opens the shared connection, then declares the grid on it.
      useMarketSocket({
        marketId: "__connect__",
        onMessage: () => {},
        enabled: true,
      })
      useMarketGrid(marketIds, (p) => { batches.push(p) })
    },
    { wrapper: MarketSocketProvider }
  )

/**
 * Open the connection.
 *
 * `useMarketGrid` only sends its declaration once a socket exists: `sendWs`
 * no-ops while CONNECTING, and the declaration is replayed on open exactly as any
 * other subscription is. Tests that assert on what reached the server therefore
 * have to open it first - the same order production takes.
 */
function openSocket(): FakeWebSocket {
  const ws = FakeWebSocket.latest()
  if (!ws) throw new Error("no socket was created")
  act(() => ws.open())
  return ws
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.instances = []
  batches = []
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket)
})

afterEach(() => {
  cleanup()
  window.dispatchEvent(new Event("pagehide"))
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("declaring a grid", () => {
  it("sends ONE frame for thirty markets, not thirty frames", () => {
    const ids = Array.from({ length: 30 }, (_, i) => `m${i}`)
    mount(ids)
    const ws = openSocket()

    const grids = ws.frames("grid")
    expect(grids).toHaveLength(1)
    expect(grids[0].market_ids).toHaveLength(30)
  })

  it("does not re-send when the caller rebuilds an equal array", () => {
    const { rerender } = renderHook(
      ({ ids }: { ids: string[] }) => {
        useMarketSocket({ marketId: "__connect__", onMessage: () => {}, enabled: true })
        useMarketGrid(ids, (p) => { batches.push(p) })
      },
      { wrapper: MarketSocketProvider, initialProps: { ids: ["a", "b"] } }
    )
    const ws = openSocket()
    const before = ws.frames("grid").length

    // A parent re-render rebuilding the array must not re-declare the grid: each
    // declaration is a round-trip and the server replaces its whole set on it.
    rerender({ ids: ["b", "a"] })
    rerender({ ids: ["a", "b"] })

    expect(ws.frames("grid").length).toBe(before)
  })

  it("re-declares when the visible set genuinely changes", () => {
    const { rerender } = renderHook(
      ({ ids }: { ids: string[] }) => {
        useMarketSocket({ marketId: "__connect__", onMessage: () => {}, enabled: true })
        useMarketGrid(ids, (p) => { batches.push(p) })
      },
      { wrapper: MarketSocketProvider, initialProps: { ids: ["a", "b"] } }
    )
    const ws = openSocket()

    // Paging the catalogue.
    rerender({ ids: ["c", "d"] })
    expect(ws.frames("grid").pop().market_ids).toEqual(["c", "d"])
  })

  it("clears the declaration when the grid empties", () => {
    // Otherwise the server keeps buffering prices for a list that has scrolled
    // away or navigated off, for a socket nobody is reading.
    const { rerender } = renderHook(
      ({ ids }: { ids: string[] }) => {
        useMarketSocket({ marketId: "__connect__", onMessage: () => {}, enabled: true })
        useMarketGrid(ids, (p) => { batches.push(p) })
      },
      { wrapper: MarketSocketProvider, initialProps: { ids: ["a", "b"] } }
    )
    const ws = openSocket()

    rerender({ ids: [] })

    expect(ws.frames("grid").pop().market_ids).toEqual([])
  })

  it("re-declares after a reconnect", () => {
    // The new socket is a new server-side grid subscriber. Without a replay it
    // silently stops updating after every reconnect - the exact failure this
    // whole layer exists to prevent.
    mount(["a", "b"])
    const first = FakeWebSocket.latest()
    act(() => first.open())
    act(() => first.drop())

    act(() => { vi.advanceTimersByTime(30_000) })
    const second = openSocket()

    expect(second.frames("grid").length).toBeGreaterThan(0)
    expect(second.frames("grid").pop().market_ids).toEqual(["a", "b"])
  })
})

/**
 * A grid-only page must be able to open the socket by itself.
 *
 * Not hypothetical: the tab-wide connection is a module singleton created on
 * demand, and until something asks for a per-market subscription it does not
 * exist. A user who lands straight on /markets has asked for no market - only a
 * grid - so the grid has to be able to bring the connection up itself. Getting
 * this wrong produces a page that is quietly, permanently static: no error, no
 * failed request, just prices that never move.
 */
describe("grid-only pages", () => {
  it("opens the connection on its own and then declares", () => {
    renderHook(
      () => useMarketGrid(["a", "b", "c"], (p) => { batches.push(p) }),
      { wrapper: MarketSocketProvider }
    )

    // No per-market subscriber anywhere - this is the /markets case.
    const ws = openSocket()

    expect(ws.url).toContain("/ws/markets/")
    expect(ws.frames("grid")).toHaveLength(1)
    expect(ws.frames("grid")[0].market_ids).toEqual(["a", "b", "c"])
  })

  it("still delivers prices when nothing else subscribed", () => {
    renderHook(
      () => useMarketGrid(["a"], (p) => { batches.push(p) }),
      { wrapper: MarketSocketProvider }
    )
    const ws = openSocket()

    act(() => ws.emit({
      type: "market:prices_batch",
      prices: { a: { market_id: "a", yes_price: 0.71, no_price: 0.29, seq: 3 } },
    }))

    expect(batches).toHaveLength(1)
    expect(batches[0]!.a!.yes_price).toBe(0.71)
  })
})

describe("receiving aggregated prices", () => {
  it("delivers a batch even though it has no top-level market_id", () => {
    // The per-market dispatch path drops any frame without a `market_id`. A
    // batch carries many markets in one frame and has none at the top level, so
    // routing it through that path silently discards every price - the same
    // shape of bug as the heartbeat ping being dropped for having no market_id.
    mount(["a", "b"])
    const ws = openSocket()

    act(() => ws.emit({
      type: "market:prices_batch",
      prices: {
        a: { market_id: "a", yes_price: 0.6, no_price: 0.4, seq: 1 },
        b: { market_id: "b", yes_price: 0.3, no_price: 0.7, seq: 9 },
      },
    }))

    expect(batches).toHaveLength(1)
    expect(Object.keys(batches[0]!).sort()).toEqual(["a", "b"])
    expect(batches[0]!.a!.yes_price).toBe(0.6)
  })

  it("preserves per-outcome prices through the batch", () => {
    // On a parimutuel market `yes_price`/`no_price` say nothing about any
    // individual outcome, so flattening them away would freeze every line but
    // the first.
    mount(["m"])
    const ws = openSocket()

    act(() => ws.emit({
      type: "market:prices_batch",
      prices: {
        m: {
          market_id: "m", yes_price: 0.5, no_price: 0.5, seq: 1,
          outcome_prices: { Yes: 0.4, No: 0.35, Draw: 0.25 },
        },
      },
    }))

    expect(batches[0]!.m!.outcome_prices).toEqual({ Yes: 0.4, No: 0.35, Draw: 0.25 })
  })

  it("carries sequence numbers so a grid can still detect a gap", () => {
    mount(["a"])
    const ws = openSocket()

    act(() => ws.emit({
      type: "market:prices_batch",
      prices: { a: { market_id: "a", yes_price: 0.5, seq: 42 } },
    }))

    expect(batches[0]!.a!.seq).toBe(42)
  })

  it("ignores unrelated frames", () => {
    mount(["a"])
    const ws = openSocket()

    act(() => ws.emit({ type: "ping", ts: 1 }))
    act(() => ws.emit({ type: "trade:new", market_id: "a" }))
    act(() => ws.emit({ type: "market:prices_batch" }))  // no prices

    expect(batches).toHaveLength(0)
  })

  it("still answers the heartbeat", () => {
    // The batch path and the heartbeat path coexist; a grid must not lose
    // liveness proving by taking the batching branch.
    mount(["a"])
    const ws = openSocket()

    act(() => ws.emit({ type: "ping", ts: 5 }))

    expect(ws.sent.some((s) => JSON.parse(s).type === "pong")).toBe(true)
  })

  it("stops delivering after unmount", () => {
    const { unmount } = mount(["a"])
    const ws = openSocket()

    unmount()
    act(() => ws.emit({
      type: "market:prices_batch",
      prices: { a: { market_id: "a", yes_price: 0.6 } },
    }))

    expect(batches).toHaveLength(0)
  })
})
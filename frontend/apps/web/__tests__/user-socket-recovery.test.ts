/**
 * The private feed's recovery contract.
 *
 * `/ws/notifications/{uid}` carries fills, position changes and notifications -
 * the frames that make a user's own portfolio live. It was the only one of the
 * three hooks with no `online` / `visibilitychange` recovery and no resync on
 * reconnect, which meant:
 *
 *  - a socket killed by a suspended laptop or a NAT timeout (no close event, so
 *    the reconnect loop never ran) stayed dead until the component remounted;
 *  - a reconnect silently skipped every fill that had happened meanwhile, so
 *    the portfolio carried on showing the position it had before.
 *
 * Unlike the market socket there is no sequence number here - private channels
 * are not sequenced - so a gap cannot be detected locally. The reconnect is the
 * only moment we *know* something was missed, which is why it has to announce
 * itself.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { useUserSocket } from "@/hooks/use-user-socket"

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

  open() { this.onopen?.() }
  send(d: string) { this.sent.push(d) }
  close() { this.closed = true; this.readyState = 3 }
  emit(o: unknown) { this.onmessage?.({ data: JSON.stringify(o) }) }
  drop() { this.readyState = 3; this.onclose?.() }
  /** The peer vanishes without a FIN - the case no close event ever reports. */
  vanish() { this.readyState = 1 }
}

let received: Array<Record<string, unknown>>
const handler = (d: unknown) => { received.push(d as Record<string, unknown>) }

const mount = () =>
  renderHook(() => useUserSocket({ userId: "user-1", onMessage: handler, enabled: true }))

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.instances = []
  received = []
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const tick = () => act(() => { vi.advanceTimersByTime(30_000) })
const resyncs = () => received.filter((m) => m.type === "__ws_resync__")

describe("heartbeat", () => {
  it("answers the server's ping", () => {
    mount()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "ping", ts: 7 }))

    // This is the long-lived socket - a page open all day - and the server reaps
    // anything silent past its deadline, so refusing to answer is how a healthy
    // session gets disconnected for being quiet.
    const pongs = ws.sent.map((s) => JSON.parse(s)).filter((m) => m.type === "pong")
    expect(pongs).toHaveLength(1)
    expect(pongs[0].ts).toBe(7)
  })

  it("does not hand the ping to the consumer as if it were data", () => {
    mount()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => ws.emit({ type: "ping", ts: 1 }))

    expect(received.some((m) => m.type === "ping")).toBe(false)
  })
})

describe("recovery from a silent death", () => {
  it("redials when the network comes back", () => {
    mount()
    const first = FakeWebSocket.latest()
    act(() => first.open())
    act(() => first.vanish())  // no close event - the laptop slept

    act(() => { window.dispatchEvent(new Event("online")) })

    expect(FakeWebSocket.instances.length).toBeGreaterThan(1)
    expect(first.closed).toBe(true)
  })

  it("redials when the tab becomes visible again", () => {
    mount()
    const first = FakeWebSocket.latest()
    act(() => first.open())
    act(() => first.vanish())

    act(() => { document.dispatchEvent(new Event("visibilitychange")) })

    expect(FakeWebSocket.instances.length).toBeGreaterThan(1)
    expect(first.closed).toBe(true)
  })

  it("replaces the socket on a tab switch, which is how the sleep case repairs", () => {
    // A socket killed by a suspended machine can still report OPEN - the
    // browser may not notice until it next writes - so `readyState` cannot
    // distinguish it from a healthy one. Tab focus is the only browser-side
    // evidence that time passed, so the socket is replaced rather than trusted:
    // one handshake, against a portfolio that silently missed fills.
    mount()
    const ws = FakeWebSocket.latest()
    act(() => ws.open())

    act(() => { document.dispatchEvent(new Event("visibilitychange")) })

    expect(FakeWebSocket.instances.length).toBeGreaterThan(1)
    expect(ws.closed).toBe(true)
  })
})

describe("catch-up after a reconnect", () => {
  it("announces a resync on reconnect, not on first connect", () => {
    mount()
    const first = FakeWebSocket.latest()
    act(() => first.open())

    // Nothing to repair on a first connect - the queries have just run.
    expect(resyncs()).toHaveLength(0)

    act(() => first.drop())
    tick()
    act(() => FakeWebSocket.latest().open())

    // Fills that happened while it was down are simply gone; nothing local can
    // detect that, so the reconnect has to say so.
    expect(resyncs()).toHaveLength(1)
    expect(resyncs()[0]!.reason).toBe("reconnect")
  })

  it("keeps retrying rather than parking", () => {
    mount()

    for (let i = 0; i < 20; i++) {
      tick()
      act(() => FakeWebSocket.latest().drop())
    }

    expect(FakeWebSocket.instances.length).toBeGreaterThan(12)
  })
})
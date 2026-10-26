import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"

/**
 * One private socket per user, however many components want it.
 *
 * `useUserSocket` used to build a socket per hook instance. Six components use
 * it - the portfolio, orders, positions and notifications pages, the wallet, and
 * the notification bell in the layout - so any page showing more than one of them
 * opened **multiple** sockets for the same user.
 *
 * The server broadcasts every private frame to every socket it holds for that
 * user, so with two sockets each frame arrived twice and each subscriber acted
 * on it: *one* event, *two* notifications. Positions and orders were also
 * refetched twice per frame, and two of the gateway's per-IP / per-user
 * connection budgets were spent on one tab, against caps measured at 50 per IP.
 *
 * A fake `WebSocket` because the property under test is the *count* of
 * connections and deliveries, which is not observable from outside.
 *
 * `vi.resetModules()` per test, rather than an exported reset hook: the
 * connection registry is module state by design, so a test-only way to clear it
 * would be production API existing only for the tests.
 */

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  readyState = FakeWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(payload: string) {
    this.sent.push(payload)
  }

  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.()
  }

  // ── test drivers ───────────────────────────────────────────────────────────

  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }

  deliver(frame: unknown) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }

  deliverRaw(raw: string) {
    this.onmessage?.({ data: raw })
  }

  fail() {
    this.onerror?.()
  }
}

type Hook = typeof import("../hooks/use-user-socket")["useUserSocket"]

/** The single open socket under test, asserting it exists. */
function socket(): FakeWebSocket {
  const ws = FakeWebSocket.instances[0]
  if (!ws) throw new Error("no WebSocket was opened")
  return ws
}

/** A freshly loaded module, so each test gets its own connection registry. */
async function loadHook(): Promise<Hook> {
  const mod = await import("../hooks/use-user-socket")
  return mod.useUserSocket
}

const USER = "bdd1a187-81d1-4a99-b33f-f52b0a546321"

describe("useUserSocket", () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal("WebSocket", FakeWebSocket)
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it("opens one socket for several subscribers, not one each", async () => {
    const useUserSocket = await loadHook()
    renderHook(() => {
      useUserSocket({ userId: USER, onMessage: vi.fn() })
      useUserSocket({ userId: USER, onMessage: vi.fn() })
      useUserSocket({ userId: USER, onMessage: vi.fn() })
    })
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it("delivers each frame to every subscriber exactly once", async () => {
    const useUserSocket = await loadHook()
    const first = vi.fn()
    const second = vi.fn()

    renderHook(() => {
      useUserSocket({ userId: USER, onMessage: first })
      useUserSocket({ userId: USER, onMessage: second })
    })

    socket().open()
    socket().deliver({ type: "notification", payload: { id: "n1" } })

    // One event, one delivery each. The bug was both seeing it twice.
    expect(first).toHaveBeenCalledTimes(1)
    expect(second).toHaveBeenCalledTimes(1)
  })

  it("keeps serving the remaining subscriber when one unsubscribes", async () => {
    const useUserSocket = await loadHook()
    const staying = vi.fn()
    const leaving = vi.fn()

    const { rerender } = renderHook(
      ({ withExtra }: { withExtra: boolean }) => {
        useUserSocket({ userId: USER, onMessage: staying })
        // Always called, conditionally subscribed - a conditional `useUserSocket`
        // would break the rules of hooks and not describe what consumers do.
        useUserSocket({ userId: USER, onMessage: leaving, enabled: withExtra })
      },
      { initialProps: { withExtra: true } }
    )

    const ws = socket()
    ws.open()

    rerender({ withExtra: false })
    ws.deliver({ type: "order:fill" })

    expect(staying).toHaveBeenCalledTimes(1)
    expect(leaving).toHaveBeenCalledTimes(0)
  })

  it("does not let one throwing subscriber starve the others", async () => {
    const useUserSocket = await loadHook()
    const good = vi.fn()
    const bad = vi.fn(() => {
      throw new Error("consumer exploded")
    })
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})

    renderHook(() => {
      useUserSocket({ userId: USER, onMessage: bad })
      useUserSocket({ userId: USER, onMessage: good })
    })

    socket().open()
    socket().deliver({ type: "position:update" })

    // A consumer's bug must not silently cost every other surface its realtime
    // data, which is what letting the throw escape the fan-out did.
    expect(good).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it("answers the heartbeat once, not once per subscriber", async () => {
    const useUserSocket = await loadHook()
    renderHook(() => {
      useUserSocket({ userId: USER, onMessage: vi.fn() })
      useUserSocket({ userId: USER, onMessage: vi.fn() })
      useUserSocket({ userId: USER, onMessage: vi.fn() })
    })

    const ws = socket()
    ws.open()
    ws.deliver({ type: "ping", ts: 1234 })

    expect(ws.sent).toEqual([JSON.stringify({ type: "pong", ts: 1234 })])
  })

  it("survives an unparseable frame", async () => {
    const useUserSocket = await loadHook()
    const onMessage = vi.fn()
    renderHook(() => useUserSocket({ userId: USER, onMessage }))

    const ws = socket()
    ws.open()
    ws.deliverRaw("{not json")
    ws.deliver({ type: "notification" })

    expect(onMessage).toHaveBeenCalledTimes(1)
  })

  it("reports a reconnect so consumers can re-read", async () => {
    const useUserSocket = await loadHook()
    const onMessage = vi.fn()
    renderHook(() => useUserSocket({ userId: USER, onMessage }))

    socket().open()
    expect(onMessage).not.toHaveBeenCalled()

    vi.useFakeTimers()
    socket().close()
    vi.advanceTimersByTime(30_000)

    expect(FakeWebSocket.instances.length).toBeGreaterThan(1)
    FakeWebSocket.instances[1]!.open()

    expect(onMessage).toHaveBeenCalledWith({ type: "__ws_resync__", reason: "reconnect" })
  })

  it("does not connect at all when disabled", async () => {
    const useUserSocket = await loadHook()
    renderHook(() => useUserSocket({ userId: USER, onMessage: vi.fn(), enabled: false }))
    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it("closes once the last subscriber leaves", async () => {
    vi.useFakeTimers()
    const useUserSocket = await loadHook()
    const { unmount } = renderHook(() => useUserSocket({ userId: USER, onMessage: vi.fn() }))
    const ws = socket()
    ws.open()

    unmount()
    // Linger first, so a route change does not cost a handshake.
    expect(ws.readyState).not.toBe(FakeWebSocket.CLOSED)
    vi.advanceTimersByTime(3000)
    expect(ws.readyState).toBe(FakeWebSocket.CLOSED)
  })

  it("keeps the socket across a route change instead of redialling", async () => {
    vi.useFakeTimers()
    const useUserSocket = await loadHook()
    const first = renderHook(() => useUserSocket({ userId: USER, onMessage: vi.fn() }))
    socket().open()

    first.unmount()
    // The next page subscribes immediately; the linger window is what makes that
    // cheap rather than a fresh handshake plus a resync on every route change.
    renderHook(() => useUserSocket({ userId: USER, onMessage: vi.fn() }))
    vi.advanceTimersByTime(3000)

    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it("rejects a socket error by closing, leaving the retry to onclose", async () => {
    const useUserSocket = await loadHook()
    renderHook(() => useUserSocket({ userId: USER, onMessage: vi.fn() }))

    const ws = socket()
    ws.open()
    ws.fail()

    expect(ws.readyState).toBe(FakeWebSocket.CLOSED)
  })

  it("reports connection status to every subscriber", async () => {
    const useUserSocket = await loadHook()
    const a = renderHook(() => useUserSocket({ userId: USER, onMessage: vi.fn() }))
    const b = renderHook(() => useUserSocket({ userId: USER, onMessage: vi.fn() }))

    expect(a.result.current.status).toBe("connecting")

    // `open()` drives a status setState, so it has to happen inside act().
    act(() => socket().open())

    expect(a.result.current.status).toBe("connected")
    expect(b.result.current.status).toBe("connected")
  })

  it("uses separate sockets for different users", async () => {
    const useUserSocket = await loadHook()
    renderHook(() => {
      useUserSocket({ userId: "user-a", onMessage: vi.fn() })
      useUserSocket({ userId: "user-b", onMessage: vi.fn() })
    })
    // Sharing across users would be worse than the bug: it would deliver one
    // user's fills to another.
    expect(FakeWebSocket.instances).toHaveLength(2)
  })
})
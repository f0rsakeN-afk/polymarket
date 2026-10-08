/**
 * `useGlobalTradesSocket` reconnect behaviour.
 *
 * This hook is the reason a dropped connection can go unnoticed for the rest of
 * a session. A laptop that sleeps drops the WebSocket with no close event, and
 * `readyState` still reads OPEN — so a naive implementation reports "connected"
 * forever while delivering nothing. The recovery paths (`online`, tab focus) are
 * the only signals the browser offers, and they have to actually redial.
 *
 * Also pinned: the socket is closed with `onclose` nulled first, so a socket
 * replaced later in the same tick cannot fire a stale close and queue a
 * reconnect for a connection that no longer exists.
 *
 * A fake WebSocket is used rather than a real one because the behaviour under
 * test is *when we call close()*, which a real socket would make untestable.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

/** Minimal WebSocket stand-in exposing only what the hook touches. */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;

  readyState = 0; // CONNECTING
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  url: string;
  closed = false;
  closeCalls = 0;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(): void {}

  close(): void {
    this.closed = true;
    this.closeCalls++;
    this.readyState = 3;
  }

  /** Simulate the server accepting the handshake. */
  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** Simulate a socket dying without a close event (sleep, NAT timeout). */
  dieSilently(): void {
    this.readyState = FakeWebSocket.OPEN; // still *looks* healthy - the trap
  }

  emit(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  /** Simulate a real close, which fires onclose. */
  drop(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  static latest(): FakeWebSocket {
    return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]!;
  }
}

beforeEach(() => {
  // Stubbed per-test, not once at module scope. An earlier version stubbed at the
  // top level and called `unstubAllGlobals()` in `afterEach`, which restored
  // jsdom's real WebSocket - so the first test passed against the fake and every
  // test after it silently ran against the real implementation with an empty
  // `instances` array.
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  FakeWebSocket.instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

import { useGlobalTradesSocket } from "@/hooks/use-global-trades-socket";

function setup(enabled = true) {
  const handler = vi.fn();
  const view = renderHook(() => useGlobalTradesSocket({ onMessage: handler, enabled }));
  return { handler, view };
}

describe("connection", () => {
  it("dials the public global feed endpoint", () => {
    setup();
    expect(FakeWebSocket.latest().url).toContain("/ws/trades");
  });

  it("reports connected once the handshake completes", () => {
    const { view } = setup();

    act(() => FakeWebSocket.latest().open());

    // No `waitFor`: it polls on real timers, which fake timers never advance, so
    // it hangs until the test times out. The state update is synchronous inside
    // act, so the value is already committed here.
    expect(view.result.current.status).toBe("connected");
  });

  it("delivers frames to the handler", () => {
    const { handler } = setup();
    act(() => FakeWebSocket.latest().open());

    act(() => FakeWebSocket.latest().emit({ type: "trade:new", id: "t1" }));

    expect(handler).toHaveBeenCalledWith({ type: "trade:new", id: "t1" });
  });

  it("does not flash 'error' on an ordinary error/close pair", () => {
    // `onerror` is always followed by `onclose`, and `onclose` owns the status
    // machine. Writing "error" in `onerror` made every retryable blip flash a
    // permanent-looking error before `onclose` overwrote it with "disconnected" -
    // so the indicator flickered between two unrelated meanings on each attempt.
    //
    // Two separate `act()` calls, deliberately. Firing both inside one act
    // batches them, the intermediate value is never committed, and the assertion
    // reads only the final state - which passed even with the bug present.
    const { view } = setup();
    const ws = FakeWebSocket.latest();

    act(() => ws.open());
    act(() => ws.onerror?.());

    // Observable state between the error and the close that follows it.
    expect(view.result.current.status).toBe("connected");

    act(() => ws.onclose?.());

    expect(view.result.current.status).toBe("disconnected");
  });

  it("survives an unparseable frame instead of tearing down", () => {
    const handler = vi.fn();
    renderHook(() => useGlobalTradesSocket({ onMessage: handler }));
    const ws = FakeWebSocket.latest();
    act(() => ws.open());

    act(() => {
      ws.onmessage?.({ data: "not json" });
    });

    // The bad frame is dropped, and the socket is still usable afterwards.
    expect(handler).not.toHaveBeenCalled();
    act(() => ws.emit({ type: "trade:new", id: "t2" }));
    expect(handler).toHaveBeenCalledWith({ type: "trade:new", id: "t2" });
  });

  it("does not dial at all when disabled", () => {
    setup(false);
    expect(FakeWebSocket.instances).toHaveLength(0);
  });
});

describe("reconnect", () => {
  it("redials after a close event, with backoff", async () => {
    setup();
    const first = FakeWebSocket.latest();
    act(() => first.open());
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => first.drop());
    expect(FakeWebSocket.instances).toHaveLength(1); // waiting on the timer

    // Backoff starts at 1s.
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("redials when the browser reports it is back online", async () => {
    // The sleep case: no close event fires, so `readyState` still reads OPEN and
    // a readyState guard alone would refuse to redial. `online` must force it.
    const { view } = setup();
    const first = FakeWebSocket.latest();
    act(() => first.open());
    act(() => first.dieSilently());

    expect(first.closed).toBe(false);

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    expect(FakeWebSocket.instances.length).toBeGreaterThan(1);
    // The stale socket is closed rather than left dangling on the server.
    expect(first.closed).toBe(true);
    expect(view.result.current.status).toBe("connecting");
  });

  it("redials when the tab becomes visible again", async () => {
    setup();
    const first = FakeWebSocket.latest();
    act(() => first.open());
    act(() => first.dieSilently());

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(FakeWebSocket.instances.length).toBeGreaterThan(1);
    expect(first.closed).toBe(true);
  });

  it("closes the stale socket with onclose nulled so it cannot queue a spurious reconnect", async () => {
    setup();
    const first = FakeWebSocket.latest();
    act(() => first.open());
    act(() => first.dieSilently());

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    // A late close from the replaced socket must not enqueue another dial.
    expect(first.onclose).toBeNull();
    const countAfterRecovery = FakeWebSocket.instances.length;

    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });

    expect(FakeWebSocket.instances.length).toBe(countAfterRecovery);
  });

  it("gives up after repeated failures rather than dialling forever", async () => {
    const { view } = setup();

    // More rounds than MAX_RECONNECT_ATTEMPTS (8), so the park is reached.
    for (let i = 0; i < 12; i++) {
      await act(async () => {
        vi.advanceTimersByTime(30_000);
      });
      if (FakeWebSocket.instances.length === 0) break; // parked: nothing to drop
      act(() => FakeWebSocket.latest().drop());
    }

    expect(view.result.current.status).toBe("error");
  });

  it("un-parks when the network genuinely returns", async () => {
    // The parked state must not be permanent: `online` is the signal that the
    // endpoint might be serving again.
    const { view } = setup();
    for (let i = 0; i < 12; i++) {
      await act(async () => {
        vi.advanceTimersByTime(30_000);
      });
      if (FakeWebSocket.instances.length === 0) break;
      act(() => FakeWebSocket.latest().drop());
    }
    expect(view.result.current.status).toBe("error");

    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    expect(view.result.current.status).not.toBe("error");
  });

  it("does NOT un-park on an ordinary tab switch while parked", async () => {
    // `recover` is bound to both `online` and tab focus, so it fires on routine
    // user activity. If it cleared the park unconditionally, a feed whose
    // endpoint is down would re-attempt on every tab switch - the retry ceiling
    // becomes no ceiling, and an endpoint refusing us is hammered all day.
    const { view } = setup();
    for (let i = 0; i < 12; i++) {
      await act(async () => {
        vi.advanceTimersByTime(30_000);
      });
      if (FakeWebSocket.instances.length === 0) break;
      act(() => FakeWebSocket.latest().drop());
    }
    expect(view.result.current.status).toBe("error");

    const countWhenParked = FakeWebSocket.instances.length;
    for (let i = 0; i < 5; i++) {
      await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
    }

    expect(FakeWebSocket.instances.length).toBe(countWhenParked);
    expect(view.result.current.status).toBe("error");
  });

  it("still recovers from the sleep case after many silent tab switches", async () => {
    // Guards the guard: a genuinely dead-but-open socket must still be replaced.
    setup();
    const first = FakeWebSocket.latest();
    act(() => first.open());
    act(() => first.dieSilently());

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(FakeWebSocket.instances.length).toBeGreaterThan(1);
    expect(first.closed).toBe(true);
  });
});

describe("teardown", () => {
  it("closes the socket on unmount", () => {
    const { view } = setup();
    const ws = FakeWebSocket.latest();
    act(() => ws.open());

    view.unmount();

    expect(ws.closed).toBe(true);
  });

  it("does not reconnect after unmount", async () => {
    const { view } = setup();
    const ws = FakeWebSocket.latest();
    act(() => ws.open());

    view.unmount();
    const count = FakeWebSocket.instances.length;

    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });

    expect(FakeWebSocket.instances.length).toBe(count);
  });

  it("removes its listeners on unmount", () => {
    const winRemove = vi.spyOn(window, "removeEventListener");
    // `visibilitychange` is registered on document, not window - spying only on
    // window is what made this miss the leak it was written to catch.
    const docRemove = vi.spyOn(document, "removeEventListener");
    const { view } = setup();
    act(() => FakeWebSocket.latest().open());

    view.unmount();

    expect(winRemove).toHaveBeenCalledWith("online", expect.any(Function));
    expect(docRemove).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
  });

  it("closes the socket when disabled flips to false", async () => {
    const handler = vi.fn();
    const view = renderHook(
      ({ enabled }: { enabled: boolean }) => useGlobalTradesSocket({ onMessage: handler, enabled }),
      { initialProps: { enabled: true } }
    );
    const ws = FakeWebSocket.latest();
    act(() => ws.open());

    view.rerender({ enabled: false });

    expect(ws.closed).toBe(true);
    expect(view.result.current.status).toBe("disconnected");
  });
});
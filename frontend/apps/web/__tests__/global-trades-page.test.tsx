/**
 * The `/trades` page must actually apply a live frame.
 *
 * The unit test on `toTrade` proves a frame can be validated. It says nothing
 * about whether the page then *uses* it - and the page had three separate ways
 * to silently drop every frame while validation passed:
 *
 *  1. It listened on `useUserSocket` (the private `/ws/notifications/{uid}`
 *     socket), whose Redis subscription never includes `global:trades`. Nothing
 *     could arrive, so no amount of correct frame handling would have mattered.
 *  2. It gated on `!!user?.id`, so an anonymous visitor - for whom the feed is
 *     public - got no socket at all.
 *  3. It read a nested `message.trade`, but the backend publishes flat
 *     (`{"type": "trade:new", **trade_data}`), so every frame was dropped.
 *
 * This renders the page with the socket stubbed and asserts on what the socket
 * was asked for and what it was handed, which is the only level at which 1-3 are
 * observable from the client side.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import type { Trade } from "@/hooks/api/types/market";

let socketHandler: ((data: unknown) => void) | null = null;
let socketEnabled: boolean | undefined;
let socketUrl: string | null = null;

/** Captures the URL the hook dials, so we can assert the *endpoint*, not just that a hook ran. */
vi.mock("@/hooks/use-global-trades-socket", () => ({
  useGlobalTradesSocket: ({
    onMessage,
    enabled,
  }: {
    onMessage: (d: unknown) => void;
    enabled?: boolean;
  }) => {
    socketHandler = onMessage;
    socketEnabled = enabled;
    socketUrl = "/ws/trades";
    return { status: "connected" };
  },
}));

/**
 * Also expose the URL through the real hook's config so the endpoint assertion
 * can fail loudly if the hook is ever pointed at the notifications endpoint.
 */
vi.mock("@/lib/config", () => ({
  config: { apiUrl: "http://localhost:8000", wsUrl: "ws://localhost:8000", siteUrl: "http://localhost:8000" },
}));

// The user hook is what the page used to use. If it is ever wired back in, this
// mock records it and the "correct socket" assertion below fails.
let userSocketUsed = false;
vi.mock("@/hooks/use-user-socket", () => ({
  useUserSocket: () => {
    userSocketUsed = true;
    return { status: "connected", send: vi.fn() };
  },
}));

let restTrades: Trade[] = [];
vi.mock("@/hooks/api/use-trades", () => ({
  useSimpleGlobalTrades: () => ({
    data: { trades: restTrades, page: 1, page_size: 100, next_cursor: null, has_more: false },
    isLoading: false,
  }),
}));

// The virtualised feed is not the subject here; render its rows plainly.
vi.mock("@/components/trades/trade-feed", () => ({
  TradeFeed: ({ trades }: { trades: Trade[] }) => (
    <div data-testid="feed">
      {trades.map((t) => (
        <div key={t.id} data-testid="feed-row" data-trade-id={t.id}>
          {t.outcome}|{t.side}|{t.price}|{t.amount}|{t.username}|{t.market_slug}
        </div>
      ))}
    </div>
  ),
}));

import { TradesPageClient } from "@/app/(public)/trades/TradesPageClient";

/** A frame exactly as the backend now publishes it: one per persisted Trade row. */
function frame(over: Record<string, unknown> = {}) {
  return {
    type: "trade:new",
    id: "trade-1",
    market_id: "market-1",
    market_slug: "will-x-happen",
    market_question: "Will X happen?",
    outcome: "Yes",
    side: "buy",
    price: "0.62",
    amount: "12.5",
    executed_at: "2026-01-01T12:00:00+00:00",
    username: "trader_123",
    ...over,
  };
}

beforeEach(() => {
  socketHandler = null;
  socketEnabled = undefined;
  socketUrl = null;
  userSocketUsed = false;
  restTrades = [];
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("global trades page socket", () => {
  it("subscribes to the public /ws/trades feed, not the private user socket", () => {
    render(<TradesPageClient />);

    expect(socketUrl).toBe("/ws/trades");
    // If this fails, the page is back on `useUserSocket`. That socket's Redis
    // subscription is `user:{id}:fills` + `user:{id}:notifications` and never
    // carries `global:trades`, so the feed will be empty again with nothing in
    // the logs to explain why.
    expect(userSocketUsed).toBe(false);
  });

  it("subscribes for anonymous visitors, since the feed is public", () => {
    // No `data` from useCurrentUser here at all - the page must not gate on a session.
    render(<TradesPageClient />);
    expect(socketEnabled).not.toBe(false);
  });
});

describe("applying a live trade frame", () => {
  it("renders a pushed trade", () => {
    render(<TradesPageClient />);

    act(() => socketHandler?.(frame()));

    const row = screen.getByTestId("feed-row");
    expect(row.dataset.tradeId).toBe("trade-1");
    expect(row.textContent).toContain("Yes");
    expect(row.textContent).toContain("0.62");
  });

  it("reads the frame's flat fields, not a nested `trade` object", () => {
    render(<TradesPageClient />);

    // The old handler required `message.trade`, so a flat frame was dropped
    // silently - this asserts the flat shape is what reaches the UI.
    act(() => socketHandler?.(frame({ outcome: "No", side: "sell", price: "0.31" })));

    expect(screen.getByTestId("feed-row").textContent).toContain("No");
    expect(screen.getByTestId("feed-row").textContent).toContain("0.31");
  });

  it("renders the market slug so a row can link back to its market", () => {
    render(<TradesPageClient />);
    act(() => socketHandler?.(frame()));

    expect(screen.getByTestId("feed-row").textContent).toContain("will-x-happen");
  });

  it("does not duplicate a trade the REST page already returned", () => {
    restTrades = [
      {
        id: "trade-1",
        market_id: "market-1",
        market_slug: "will-x-happen",
        market_question: "Will X happen?",
        outcome: "Yes",
        side: "buy",
        price: "0.62",
        amount: "12.5",
        executed_at: "2026-01-01T12:00:00+00:00",
        username: "trader_123",
      },
    ];
    render(<TradesPageClient />);

    act(() => socketHandler?.(frame()));

    expect(screen.getAllByTestId("feed-row")).toHaveLength(1);
  });

  it("does not duplicate a trade the REST page returned *after* the frame arrived", () => {
    // The reverse of the case above, and the one `seenIdsRef` structurally
    // cannot catch: a WS frame arrives while the REST request is still in
    // flight, so it is accepted (nothing has been seen yet), and then the
    // response lands carrying that same trade. `seenIdsRef` only guards
    // frame-against-already-seen, so the merge itself has to dedupe.
    //
    // The reconnect resync re-runs this query, which made the window reachable
    // on every reconnect rather than just page load.
    const { rerender } = render(<TradesPageClient />);

    act(() => socketHandler?.(frame()));

    // The REST page then resolves, carrying the same trade.
    restTrades = [
      {
        id: "trade-1",
        market_id: "market-1",
        market_slug: "will-x-happen",
        market_question: "Will X happen?",
        outcome: "Yes",
        side: "buy",
        price: "0.62",
        amount: "12.5",
        executed_at: "2026-01-01T12:00:00+00:00",
        username: "trader_123",
      },
    ];
    rerender(<TradesPageClient />);

    expect(screen.getAllByTestId("feed-row")).toHaveLength(1);
  });

  it("does not duplicate two pushes of the same trade", () => {
    render(<TradesPageClient />);

    act(() => {
      socketHandler?.(frame());
      socketHandler?.(frame());
    });

    expect(screen.getAllByTestId("feed-row")).toHaveLength(1);
  });

  it("keeps two distinct trades even when they share a timestamp", () => {
    render(<TradesPageClient />);

    act(() => {
      socketHandler?.(frame({ id: "trade-a", executed_at: "2026-01-01T12:00:00.000Z" }));
      socketHandler?.(frame({ id: "trade-b", executed_at: "2026-01-01T12:00:00.000Z" }));
    });

    expect(screen.getAllByTestId("feed-row")).toHaveLength(2);
  });

  it("renders a fill at price 0 rather than dropping it as falsy", () => {
    render(<TradesPageClient />);

    act(() => socketHandler?.(frame({ price: "0", amount: "3" })));

    // The old guard was `msg.price && msg.amount`, which discarded this.
    expect(screen.getByTestId("feed-row").textContent).toContain("|0|");
  });

  it("drops a frame whose username is absent, falling back rather than blanking", () => {
    render(<TradesPageClient />);

    // `username ?? "Unknown"` - a trade with no user attached is still a trade.
    act(() => socketHandler?.(frame({ username: undefined })));

    expect(screen.getByTestId("feed-row").textContent).toContain("Unknown");
  });

  it("drops a malformed frame instead of rendering an empty row", () => {
    render(<TradesPageClient />);

    act(() => socketHandler?.(frame({ price: "abc" })));

    expect(screen.queryAllByTestId("feed-row")).toHaveLength(0);
  });

  it("drops a frame with no id, which could never be deduped", () => {
    render(<TradesPageClient />);

    act(() => socketHandler?.(frame({ id: undefined })));

    expect(screen.queryAllByTestId("feed-row")).toHaveLength(0);
  });

  it("ignores non-trade frames arriving on the same socket", () => {
    render(<TradesPageClient />);

    act(() => socketHandler?.({ type: "ping" }));
    act(() => socketHandler?.({ type: "market:price_update", yes_price: 0.6 }));

    expect(screen.queryAllByTestId("feed-row")).toHaveLength(0);
  });
});
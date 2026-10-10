/**
 * The market page must render a pushed trade, and must not double-render it.
 *
 * The old handler had three ways to lose a trade while everything looked fine:
 *
 *  1. It required `msg.price && msg.amount && msg.username` to be *truthy*, so a
 *     legitimate fill at price 0 was silently discarded.
 *  2. It minted a synthetic `ws-${Date.now()}` id. That id matches no database
 *     row, so once `staleTime` expired and REST refetched, the same trade
 *     appeared twice - once from the socket, once from the fetch - with no way to
 *     match them. Two trades inside one millisecond also collided outright.
 *  3. It read only outcome/side/price/amount/username, dropping the fields a row
 *     needs to be identifiable at all.
 *
 * The backend now sends one frame per persisted Trade row, carrying the same
 * fields as the REST feed. These tests assert the page uses them.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

let socketHandler: ((data: unknown) => void) | null = null;

vi.mock("@/hooks/use-market-socket", () => ({
  // The synthetic frame types are values, not behaviour - they must survive
  // the mock or the component's resync branch compares against `undefined` and
  // silently never matches.
  WS_RESYNC: "__ws_resync__",
  WS_GAP: "__ws_gap__",
  useMarketSocket: ({ onMessage }: { onMessage: (d: unknown) => void }) => {
    socketHandler = onMessage;
    return { status: "connected" };
  },
}));

const market = {
  id: "market-1",
  slug: "will-x-happen",
  question: "Will X happen?",
  description: null,
  category: null,
  status: "active",
  total_liquidity: 1000,
  total_volume: 500,
  yes_price: "0.50",
  no_price: "0.50",
  spread: 0,
  closes_at: "2030-01-01T00:00:00Z",
  winning_outcome_name: null,
  outcomes: [
    { id: "o1", name: "Yes", outcome_index: 0, price: 0.5 },
    { id: "o2", name: "No", outcome_index: 1, price: 0.5 },
  ],
};

vi.mock("@/hooks/api/use-markets", () => ({
  useMarket: () => ({ data: market, isLoading: false }),
  useMarketActivity: () => ({ data: null }),
  useFAQs: () => ({ data: [] }),
  useRelatedMarkets: () => ({ data: [] }),
  usePriceHistory: () => ({ data: [] }),
  useResolveMarket: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useOrderBook: () => ({ data: { success: true, data: { outcomes: {} } } }),
}));

vi.mock("@/hooks/api/use-trades", () => ({
  useSimpleMarketTrades: () => ({ data: { trades: [] }, isLoading: false }),
}));

vi.mock("@/hooks/use-auth", () => ({ useCurrentUser: () => ({ data: null }) }));
vi.mock("@/lib/api/markets", () => ({ claimWinnings: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiErrorMessage: vi.fn() }));

/** Plain rows, so the assertion is about data and not about the virtualiser. */
vi.mock("@/components/trades/trade-feed", () => ({
  TradeFeed: ({ trades }: { trades: { id: string }[] }) => (
    <div data-testid="feed">
      {trades.map((t) => (
        <div key={t.id} data-testid="feed-row" data-trade-id={t.id}>
          {t.id}
        </div>
      ))}
    </div>
  ),
}));

vi.mock("@/components/markets/live-trade-ticker", () => ({
  LiveTradeTicker: () => <div data-testid="ticker" />,
}));
vi.mock("@/components/markets/order-book", () => ({ OrderBook: () => <div /> }));
vi.mock("@/components/markets/trade-form", () => ({ TradeForm: () => <div /> }));
vi.mock("@/components/markets/comment-list", () => ({
  CommentList: () => <div />,
  CommentForm: () => <div />,
}));
vi.mock("@/components/liquidity/add-liquidity-form", () => ({
  AddLiquidityForm: () => <div />,
}));
vi.mock("@/components/alerts/alert-dialog", () => ({ AlertDialog: () => <div /> }));

import { MarketDetail } from "@/components/markets/market-detail";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { queryKeys } from "@/lib/api/queryKeys";

/** A frame exactly as the backend publishes it: one per persisted Trade row. */
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

function feedRows(): HTMLElement[] {
  return screen.queryAllByTestId("feed-row");
}

/**
 * Open the Trades tab before asserting on the feed.
 *
 * `Tabs` renders only the active panel and Orderbook is the default, so without
 * this the feed is never in the DOM and every "renders a pushed trade" assertion
 * passes vacuously against an empty panel - the exact shape of test that hides a
 * regression.
 */
async function openTradesTab(): Promise<void> {
  const user = (await import("@testing-library/user-event")).default.setup();
  await user.click(screen.getByRole("tab", { name: "Trades" }));
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // Seeded so the page has its market data synchronously.
  client.setQueryData(queryKeys.market("will-x-happen"), market);
  render(
    <QueryClientProvider client={client}>
      <MarketDetail slug="will-x-happen" />
    </QueryClientProvider>
  );
  return client;
}

beforeEach(() => {
  socketHandler = null;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("market page live trade frames", () => {
  it("renders a pushed trade", async () => {
    renderDetail();
    await openTradesTab();

    act(() => socketHandler?.(frame()));

    expect(feedRows()).toHaveLength(1);
  });

  it("renders a fill at price 0, which a truthiness guard used to discard", async () => {
    renderDetail();
    await openTradesTab();

    // Numeric 0 on purpose. The old guard was `msg.price && msg.amount`, and it
    // only dropped this because the pre-fix backend published floats - `"0"` as a
    // string is truthy and would have slipped through, which is why an earlier
    // version of this test asserting on the string form passed against broken
    // code and proved nothing.
    act(() => socketHandler?.(frame({ price: 0, amount: 3 })));

    expect(feedRows()).toHaveLength(1);
  });

  it("does not render the same pushed trade twice", async () => {
    renderDetail();
    await openTradesTab();

    act(() => {
      socketHandler?.(frame());
      socketHandler?.(frame());
    });

    expect(feedRows()).toHaveLength(1);
  });

  it("keeps two trades that share a timestamp", async () => {
    renderDetail();
    await openTradesTab();

    act(() => {
      socketHandler?.(frame({ id: "a", executed_at: "2026-01-01T12:00:00.000Z" }));
      socketHandler?.(frame({ id: "b", executed_at: "2026-01-01T12:00:00.000Z" }));
    });

    // The synthetic `ws-${Date.now()}` id made these indistinguishable: both rows
    // existed but collided on React key and on any dedupe, so asserting only the
    // count would pass against broken code. The ids must differ.
    expect(feedRows()).toHaveLength(2);
    expect(new Set(feedRows().map((r) => r.dataset.tradeId)).size).toBe(2);
  });

  it("keys the pushed row by its real database id", async () => {
    renderDetail();
    await openTradesTab();

    act(() => socketHandler?.(frame()));

    // Identity is the point: a `ws-${Date.now()}` id matches no row, so the
    // pushed trade and the same trade from a refetch could never be matched.
    expect(feedRows()[0]!.dataset.tradeId).toBe("trade-1");
  });

  it("drops a frame with no id, which could never be deduped", async () => {
    renderDetail();
    await openTradesTab();

    act(() => socketHandler?.(frame({ id: undefined })));

    expect(feedRows()).toHaveLength(0);
  });

  it("drops a frame whose price is not a number", async () => {
    renderDetail();
    await openTradesTab();

    act(() => socketHandler?.(frame({ price: "abc" })));

    expect(feedRows()).toHaveLength(0);
  });

  it("ignores non-trade frames", async () => {
    renderDetail();
    await openTradesTab();

    act(() => socketHandler?.({ type: "ping" }));
    act(() => socketHandler?.({ type: "orderbook:update", outcomes: {} }));

    expect(feedRows()).toHaveLength(0);
  });
});

describe("market page live price frames", () => {
  it("pushes a new price into the cached market so the header follows the trade", () => {
    const client = renderDetail();

    act(() =>
      socketHandler?.({ type: "market:price_update", yes_price: 0.66, no_price: 0.34 })
    );

    const cached = client.getQueryData(queryKeys.market("will-x-happen")) as {
      yes_price: string;
      no_price: string;
    };
    expect(cached.yes_price).toBe("0.66");
    expect(cached.no_price).toBe("0.34");
  });

  it("moves per-outcome prices, which is what the header and order form read", () => {
    // `market.outcomes[].price` was only ever written by the initial fetch, so on
    // a 3+ outcome market every number froze while the chart lines moved.
    const client = renderDetail();

    act(() =>
      socketHandler?.({
        type: "market:price_update",
        yes_price: 0.66,
        no_price: 0.34,
        outcome_prices: { Yes: 0.66, No: 0.34 },
      })
    );

    const cached = client.getQueryData(queryKeys.market("will-x-happen")) as {
      outcomes: { price: number }[];
    };
    expect(cached.outcomes[0]!.price).toBe(0.66);
    expect(cached.outcomes[1]!.price).toBe(0.34);
  });

  it("writes prices as strings, matching the API's Decimal serialisation", () => {
    const client = renderDetail();

    act(() => socketHandler?.({ type: "market:price_update", yes_price: 0.66, no_price: 0.34 }));

    const cached = client.getQueryData(queryKeys.market("will-x-happen")) as {
      yes_price: unknown;
    };
    expect(typeof cached.yes_price).toBe("string");
  });
});
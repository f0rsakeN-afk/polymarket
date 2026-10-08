/**
 * The trending carousel card must show ONE live price.
 *
 * It used to re-read `market.yes_price` for everything it displayed while a
 * separate state array tracked live frames. The sparkline moved and the "62%"
 * next to it stayed frozen, so the two disagreed on screen - the same class of
 * bug as the market page, where a trade moved the chart but not the price.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import type { MarketResponse } from "@/hooks/api/types/market";

let socketHandler: ((data: unknown) => void) | null = null;

vi.mock("@/hooks/use-market-socket", () => ({
  useMarketSocket: ({ onMessage }: { onMessage: (d: unknown) => void }) => {
    socketHandler = onMessage;
    return { status: "connected" };
  },
}));

// The chart is dynamically imported with ssr:false; stub it so the card renders
// synchronously and we can inspect the props it was handed.
const chartProps: { data: unknown[]; value: number }[] = [];
vi.mock("next/dynamic", () => ({
  default: (_loader: () => Promise<unknown>) =>
    function Stub(props: { data: unknown[]; value: number; children?: unknown }) {
      chartProps.push({ data: props.data, value: props.value });
      return <div data-testid="sparkline" />;
    },
}));

import TrendingCarouselItem from "@/components/home/trending-carousel-item";

const market = {
  id: "mkt-1",
  slug: "will-x-happen",
  question: "Will X happen?",
  category: "news",
  total_volume: "1234.5",
  yes_price: "0.62",
  no_price: "0.38",
} as unknown as MarketResponse;

beforeEach(() => {
  socketHandler = null;
  chartProps.length = 0;
});

function sendFrame(yesPrice: number) {
  act(() => {
    socketHandler?.({
      type: "market:price_update",
      market_id: "mkt-1",
      yes_price: yesPrice,
      no_price: 1 - yesPrice,
    });
  });
}

describe("TrendingCarouselItem live price", () => {
  it("shows the REST price before any frame arrives", () => {
    render(<TrendingCarouselItem market={market} />);
    expect(screen.getByText("62%")).toBeInTheDocument();
  });

  it("updates the percentage when a price frame arrives", () => {
    render(<TrendingCarouselItem market={market} />);
    sendFrame(0.71);
    // The bug: the chart moved but this number did not.
    expect(screen.getByText("71%")).toBeInTheDocument();
    expect(screen.queryByText("62%")).not.toBeInTheDocument();
  });

  it("keeps the chart and the number on the same value", () => {
    render(<TrendingCarouselItem market={market} />);
    sendFrame(0.71);

    const last = chartProps.at(-1)!;
    expect(last.value).toBeCloseTo(0.71, 5);
  });

  it("drives the chart's data array live too", () => {
    render(<TrendingCarouselItem market={market} />);
    const seeded = chartProps.at(-1)!.data.length;

    sendFrame(0.71);
    const updated = chartProps.at(-1)!.data;

    expect(updated.length).toBe(seeded + 1);
    expect(updated.at(-1)).toMatchObject({ value: 0.71 });
  });

  it("caps the history so a long-lived tab cannot grow unbounded", () => {
    render(<TrendingCarouselItem market={market} />);
    for (let i = 0; i < 80; i++) sendFrame(0.5 + i / 1000);

    expect(chartProps.at(-1)!.data.length).toBeLessThanOrEqual(60);
  });

  it("never appends a zero for a malformed frame", () => {
    render(<TrendingCarouselItem market={market} />);
    const before = chartProps.at(-1)!.data.length;

    act(() => {
      socketHandler?.({ type: "market:price_update", market_id: "mkt-1" });
    });
    act(() => {
      socketHandler?.({
        type: "market:price_update",
        market_id: "mkt-1",
        yes_price: Number.NaN,
        no_price: 0.5,
      });
    });

    // Unchanged, and the displayed percentage is still the real one.
    expect(chartProps.at(-1)!.data.length).toBe(before);
    expect(screen.getByText("62%")).toBeInTheDocument();
  });

  it("ignores non-price frames", () => {
    render(<TrendingCarouselItem market={market} />);
    const before = chartProps.at(-1)!.data.length;

    act(() => {
      socketHandler?.({ type: "trade:new", outcome: "Yes", price: 0.9 });
    });

    expect(chartProps.at(-1)!.data.length).toBe(before);
    expect(screen.getByText("62%")).toBeInTheDocument();
  });

  it("does not show 0% for a market with an unparseable price", () => {
    const broken = { ...market, yes_price: null } as unknown as MarketResponse;
    render(<TrendingCarouselItem market={broken} />);

    // An even split, not 0 - 0 would be a real, wrong probability. Both the
    // YES and NO tiles read 50%, so query all of them.
    const percents = screen.queryAllByText(/%/).map((el) => el.textContent);
    expect(percents).toEqual(["50%", "50%"]);
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("clamps a frame outside 0..1 instead of rendering it", () => {
    render(<TrendingCarouselItem market={market} />);
    sendFrame(1.4);
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("keeps the accessible label in step with the live number", () => {
    render(<TrendingCarouselItem market={market} />);
    sendFrame(0.71);

    const link = screen.getByRole("listitem");
    expect(link.getAttribute("aria-label")).toContain("YES 71%");
    expect(link.getAttribute("aria-label")).toContain("NO 29%");
  });
});
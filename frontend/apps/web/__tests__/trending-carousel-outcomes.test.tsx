/**
 * Outcome labelling on home-page cards.
 *
 * A market is binary when its outcomes are the YES/NO pair - NOT when it
 * happens to have two of them. Counting outcomes mislabels a two-way named
 * market: "Trump vs Biden" has two outcomes, but showing "Yes 55% / No 45%"
 * labels them with sides that do not exist, and it is not the binary book the
 * AMM prices. Same rule as the market page, so card and detail page agree.
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

let history: unknown = [];
vi.mock("@/hooks/api/use-markets", () => ({
  usePriceHistory: () => ({ data: history }),
}));

const chartProps: { data: Record<string, unknown>[]; value: number }[] = [];
vi.mock("next/dynamic", () => ({
  default: () =>
    function Stub(props: { data: unknown[]; value: number; children?: unknown }) {
      chartProps.push({ data: props.data as never, value: props.value });
      return <div data-testid="sparkline" />;
    },
}));

import TrendingCarouselItem from "@/components/home/trending-carousel-item";

const outcome = (name: string, index: number) => ({
  id: name,
  name,
  outcome_index: index,
});

const base = {
  id: "mkt-1",
  slug: "will-x-happen",
  question: "Will X happen?",
  category: "news",
  total_volume: "1234.5",
  yes_price: "0.62",
  no_price: "0.38",
} as unknown as MarketResponse;

function marketWith(outcomes: { name: string }[] | null) {
  return {
    ...base,
    outcomes: outcomes
      ? outcomes.map((o, i) => outcome(o.name, i))
      : null,
  } as unknown as MarketResponse;
}

function setHistory(samples: unknown) {
  history = samples;
}

beforeEach(() => {
  socketHandler = null;
  history = [];
  chartProps.length = 0;
});

function samples(lines: { name: string; price: number }[], t = 1_700_000_000) {
  return lines.map((l) => ({
    timestamp: new Date(t * 1000).toISOString(),
    outcomes: [{ name: l.name, price: String(l.price) }],
  }));
}

describe("binary market cards", () => {
  it("shows the YES/NO split for a Yes/No market", () => {
    render(
      <TrendingCarouselItem
        market={marketWith([{ name: "Yes" }, { name: "No" }])}
      />
    );
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.getByText("62%")).toBeInTheDocument();
  });

  it("charts a single value line, since NO is the complement of YES", () => {
    render(
      <TrendingCarouselItem
        market={marketWith([{ name: "Yes" }, { name: "No" }])}
      />
    );
    expect(screen.getByTestId("sparkline")).toBeInTheDocument();
  });

  it("falls back to the binary split when the list sends no outcomes", () => {
    // `outcomes` is nullable on the list endpoint. With no names to judge by,
    // yes_price/no_price are the only prices available - an empty outcome list
    // would render a card with no prices at all.
    render(<TrendingCarouselItem market={marketWith(null)} />);
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("62%")).toBeInTheDocument();
  });

  it("treats an empty outcomes array the same as null", () => {
    render(<TrendingCarouselItem market={marketWith([])} />);
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("treats a single named outcome as non-binary", () => {
    // Degenerate, but it has no NO side, so the binary split would be a lie.
    render(
      <TrendingCarouselItem
        market={marketWith([{ name: "Home" }])}
      />
    );
    expect(screen.queryByText("Yes")).not.toBeInTheDocument();
    expect(screen.getByText("Home")).toBeInTheDocument();
  });

  it("matches outcome names case-insensitively", () => {
    render(
      <TrendingCarouselItem
        market={marketWith([{ name: "YES" }, { name: "No" }])}
      />
    );
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });
});

describe("two-outcome named market", () => {
  const trump = marketWith([{ name: "Trump" }, { name: "Biden" }]);

  it("does NOT label a two-way named market as Yes/No", () => {
    // The count-based rule called this binary and invented a NO side.
    render(<TrendingCarouselItem market={trump} />);
    expect(screen.queryByText("Yes")).not.toBeInTheDocument();
    expect(screen.queryByText("No")).not.toBeInTheDocument();
  });

  it("names the actual outcomes with their own prices", () => {
    setHistory(
      samples([
        { name: "Trump", price: 0.55 },
        { name: "Biden", price: 0.45 },
      ])
    );
    render(<TrendingCarouselItem market={trump} />);

    expect(screen.getByText("Trump")).toBeInTheDocument();
    expect(screen.getByText("Biden")).toBeInTheDocument();
    expect(screen.getByText("55%")).toBeInTheDocument();
    expect(screen.getByText("45%")).toBeInTheDocument();
  });

  it("describes the market by outcome in its accessible name", () => {
    setHistory(
      samples([
        { name: "Trump", price: 0.55 },
        { name: "Biden", price: 0.45 },
      ])
    );
    render(<TrendingCarouselItem market={trump} />);

    const label = screen.getByRole("listitem").getAttribute("aria-label")!;
    expect(label).toContain("Trump 55%");
    expect(label).toContain("Biden 45%");
    expect(label).not.toContain("YES");
  });
});

describe("three-or-more outcome markets", () => {
  const threeWay = marketWith([
    { name: "Home" },
    { name: "Draw" },
    { name: "Away" },
  ]);

  it("lists every outcome by name", () => {
    setHistory(
      samples([
        { name: "Home", price: 0.4 },
        { name: "Draw", price: 0.25 },
        { name: "Away", price: 0.35 },
      ])
    );
    render(<TrendingCarouselItem market={threeWay} />);

    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Draw")).toBeInTheDocument();
    expect(screen.getByText("Away")).toBeInTheDocument();
    expect(screen.queryByText("Yes")).not.toBeInTheDocument();
  });

  it("takes each outcome price from the history, not the binary pool", () => {
    setHistory(
      samples([
        { name: "Home", price: 0.4 },
        { name: "Draw", price: 0.25 },
        { name: "Away", price: 0.35 },
      ])
    );
    render(<TrendingCarouselItem market={threeWay} />);

    // yes_price is 0.62 here. Showing that as "Home" would be wrong - the
    // binary pool cannot price three outcomes.
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("35%")).toBeInTheDocument();
    expect(screen.queryByText("62%")).not.toBeInTheDocument();
  });

  it("shows a dash, not 0%, for every outcome the history cannot price", () => {
    // Only Home has a price, so Draw and Away both render as a gap.
    setHistory([samples([{ name: "Home", price: 0.4 }])[0]]);
    render(<TrendingCarouselItem market={threeWay} />);

    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("keeps the coloured series alive when a live frame arrives", () => {
    setHistory(
      samples([
        { name: "Home", price: 0.4 },
        { name: "Draw", price: 0.25 },
        { name: "Away", price: 0.35 },
      ])
    );
    render(<TrendingCarouselItem market={threeWay} />);

    act(() => {
      socketHandler?.({
        type: "market:price_update",
        market_id: "mkt-1",
        outcome_prices: { Home: 0.55, Draw: 0.2, Away: 0.25 },
      });
    });

    // The appended point must carry the per-outcome keys, otherwise every
    // coloured line loses its value at the live tip.
    const last = chartProps.at(-1)!.data.at(-1)!;
    expect(last.Home).toBe(0.55);
    expect(last.Draw).toBe(0.2);
    expect(last.Away).toBe(0.25);
  });

  it("appends nothing when a live frame carries no usable price", () => {
    setHistory(samples([{ name: "Home", price: 0.4 }]));
    render(<TrendingCarouselItem market={threeWay} />);
    const before = chartProps.at(-1)!.data.length;

    act(() => {
      socketHandler?.({ type: "market:price_update", market_id: "mkt-1" });
    });

    expect(chartProps.at(-1)!.data.length).toBe(before);
  });

  it("summarises the overflow when there are more than three outcomes", () => {
    setHistory(
      samples([
        { name: "A", price: 0.4 },
        { name: "B", price: 0.3 },
        { name: "C", price: 0.2 },
        { name: "D", price: 0.1 },
      ])
    );
    render(
      <TrendingCarouselItem
        market={marketWith([{ name: "A" }, { name: "B" }, { name: "C" }, { name: "D" }])}
      />
    );

    expect(screen.getByText("+1 more")).toBeInTheDocument();
  });
});
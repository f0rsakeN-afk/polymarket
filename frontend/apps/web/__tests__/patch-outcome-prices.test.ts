/**
 * A live frame must move the *numbers*, not just the chart lines.
 *
 * On a market with 3+ outcomes the header strip and the order form both read
 * their prices from `buildOutcomePrices(market.outcomes, orderbook)`, which
 * prefers the API price over the orderbook midpoint. `outcomes[].price` was only
 * ever written by the initial REST fetch - and since `useMarket` has a
 * `staleTime` but no `refetchInterval`, nothing ever rewrote it. So the API price
 * always won, and it always won *stale*: every per-outcome number sat frozen
 * while the coloured lines beside it moved.
 */
import { describe, expect, it } from "vitest";
import { patchMarketPrices, type MarketPriceCache } from "@/lib/live-price";

/** A cached 3-outcome market, shaped as `getMarket` returns it. */
function cachedMarket(): MarketPriceCache {
  return {
    id: "mkt-1",
    slug: "who-wins",
    total_volume: "1000.00",
    yes_price: "0.50",
    no_price: "0.50",
    outcomes: [
      { id: "o1", name: "Yes", price: 0.5 },
      { id: "o2", name: "No", price: 0.3 },
      { id: "o3", name: "Maybe", price: 0.2 },
    ],
  };
}

describe("patchMarketPrices with outcome_prices", () => {
  it("updates every cached outcome the frame prices", () => {
    const prev = cachedMarket();
    const next = patchMarketPrices(prev, {
      outcome_prices: { Yes: 0.62, No: 0.25, Maybe: 0.13 },
    })!;

    expect(next.outcomes).toEqual([
      { id: "o1", name: "Yes", price: 0.62 },
      { id: "o2", name: "No", price: 0.25 },
      { id: "o3", name: "Maybe", price: 0.13 },
    ]);
  });

  it("does not mutate the previous cache object", () => {
    const prev = cachedMarket();
    const snapshot = JSON.parse(JSON.stringify(prev.outcomes));

    patchMarketPrices(prev, { outcome_prices: { Yes: 0.9 } });

    expect(prev.outcomes).toEqual(snapshot);
  });

  it("matches outcome names case-insensitively", () => {
    const prev = cachedMarket();
    const next = patchMarketPrices(prev, {
      // The frame carries the canonical DB casing; a client may hold lower-cased.
      outcome_prices: { yes: 0.71 },
    })!;

    expect(next.outcomes![0]!.price).toBe(0.71);
  });

  it("leaves an outcome alone when the frame has no price for it", () => {
    const prev = cachedMarket();
    const next = patchMarketPrices(prev, { outcome_prices: { Yes: 0.62 } })!;

    expect(next.outcomes![0]!.price).toBe(0.62);
    // Untouched outcomes keep their fetched value rather than becoming NaN/0.
    expect(next.outcomes![1]!.price).toBe(0.3);
    expect(next.outcomes![2]!.price).toBe(0.2);
  });

  it("preserves outcome identity fields the frame does not carry", () => {
    const next = patchMarketPrices(cachedMarket(), {
      outcome_prices: { Yes: 0.62 },
    })!;

    expect(next.outcomes![0]).toMatchObject({ id: "o1", name: "Yes" });
  });

  it("is a no-op when nothing changed, returning the same reference", () => {
    const prev = cachedMarket();
    const same = patchMarketPrices(prev, { outcome_prices: { Yes: 0.5 } });

    // Same reference: React Query must not treat a no-op frame as new data and
    // re-render the page for a price that did not move.
    expect(same).toBe(prev);
  });

  it("still patches yes_price/no_price on a binary frame", () => {
    const next = patchMarketPrices(cachedMarket(), {
      yes_price: 0.66,
      no_price: 0.34,
    })!;

    expect(next.yes_price).toBe("0.66");
    expect(next.no_price).toBe("0.34");
    // Binary frames carry no outcome_prices, so the outcome list is untouched.
    expect(next.outcomes).toEqual(cachedMarket().outcomes);
  });

  it("writes prices as strings, matching the API's Decimal serialisation", () => {
    // The API models yes_price/no_price as Decimal -> string. Writing the WS
    // number straight in would change the cache shape under every other reader.
    const next = patchMarketPrices(cachedMarket(), { yes_price: 0.66 })!;
    expect(typeof next.yes_price).toBe("string");
  });

  it("survives a cached market with no outcomes array", () => {
    const prev: MarketPriceCache = { yes_price: "0.50", no_price: "0.50" };
    const next = patchMarketPrices(prev, { outcome_prices: { Yes: 0.62 } });

    expect(next).toBe(prev); // nothing to write, so no new object
  });

  it("ignores a non-finite outcome price instead of writing it", () => {
    const prev = cachedMarket();
    const next = patchMarketPrices(prev, {
      outcome_prices: { Yes: NaN, No: 0.25 },
    })!;

    // NaN would render as "NaN%" in the header - a fabricated value, not a gap.
    expect(next.outcomes![0]!.price).toBe(0.5);
    expect(next.outcomes![1]!.price).toBe(0.25);
  });
});
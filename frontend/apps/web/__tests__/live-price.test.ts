/**
 * The realtime accuracy edge case: "someone buys/sells -> is it reflected
 * immediately, and can the price ever be zero?"
 *
 * A trade must (a) move the chart and (b) move the price the page displays -
 * including the price the order form quotes. Before the fix, (b) never
 * happened: the chart's point list was updated but the cached market was not, so
 * `market.yes_price` stayed on the last HTTP fetch indefinitely (useMarket has
 * staleTime but no refetchInterval, and nothing invalidated it).
 */
import { describe, expect, it } from "vitest";
import {
  buildLivePricePoint,
  patchMarketPrices,
} from "@/lib/live-price";

const NOW = 1_700_000_000;

describe("buildLivePricePoint", () => {
  it("maps a binary frame onto value/Yes/No", () => {
    const point = buildLivePricePoint({ yes_price: 0.62, no_price: 0.38 }, NOW);

    expect(point).not.toBeNull();
    expect(point).toMatchObject({
      time: NOW,
      value: 0.62,
      Yes: 0.62,
      No: 0.38,
    });
  });

  it("keeps a steady price steady (no-change frames repeat the same value)", () => {
    const first = buildLivePricePoint({ yes_price: 0.6, no_price: 0.4 }, NOW);
    const second = buildLivePricePoint({ yes_price: 0.6, no_price: 0.4 }, NOW + 1);

    expect(first!.value).toBe(0.6);
    expect(second!.value).toBe(first!.value);
  });

  it("drops a frame that carries no price instead of plotting zero", () => {
    // This is the "graph dives to zero" path: a point with no `value` renders
    // as 0 and drags the live tip to the floor.
    expect(buildLivePricePoint({}, NOW)).toBeNull();
    expect(buildLivePricePoint({ yes_price: 0.6 }, NOW)).toBeNull();
    expect(buildLivePricePoint({ no_price: 0.4 }, NOW)).toBeNull();
    expect(buildLivePricePoint({ yes_price: 0, no_price: 0 }, NOW)).toEqual({
      time: NOW,
      value: 0,
      Yes: 0,
      No: 0,
    });
  });

  it("rejects non-finite prices rather than charting NaN", () => {
    expect(
      buildLivePricePoint({ yes_price: Number.NaN, no_price: 0.4 }, NOW)
    ).toBeNull();
    expect(
      buildLivePricePoint(
        { yes_price: Number.POSITIVE_INFINITY, no_price: 0.4 },
        NOW
      )
    ).toBeNull();
  });

  it("maps outcome_prices onto per-name keys with the first as `value`", () => {
    const point = buildLivePricePoint(
      { outcome_prices: { Yes: 0.7, No: 0.2, Draw: 0.1 } },
      NOW
    );

    expect(point).toMatchObject({
      time: NOW,
      value: 0.7,
      Yes: 0.7,
      No: 0.2,
      Draw: 0.1,
    });
  });

  it("prefers outcome_prices over the binary yes/no shape", () => {
    // On a 3+ outcome market the binary fields describe a pool that cannot
    // represent the outcomes, so they must not overwrite the per-outcome keys.
    const point = buildLivePricePoint(
      { outcome_prices: { Yes: 0.7, No: 0.2 }, yes_price: 0.5, no_price: 0.5 },
      NOW
    );
    expect(point).toMatchObject({ Yes: 0.7, No: 0.2, value: 0.7 });
  });

  it("drops an empty outcome_prices map rather than reading prices[0] as 0", () => {
    // `Object.values({})[0] ?? 0` used to yield a literal 0 here.
    expect(buildLivePricePoint({ outcome_prices: {} }, NOW)).toBeNull();
  });

  it("falls back to yes/no when outcome_prices is absent", () => {
    const point = buildLivePricePoint({ yes_price: 0.55, no_price: 0.45 }, NOW);
    expect(point).toMatchObject({ value: 0.55, Yes: 0.55, No: 0.45 });
  });
});

describe("patchMarketPrices", () => {
  const cached = {
    slug: "will-x-happen",
    question: "Will X happen?",
    yes_price: "0.50",
    no_price: "0.50",
    total_volume: "1234.5",
  };

  it("updates the cached price so every reader sees the trade at once", () => {
    const next = patchMarketPrices(cached, { yes_price: 0.62, no_price: 0.38 });

    expect(next).not.toBe(cached);
    expect(next).toMatchObject({ yes_price: "0.62", no_price: "0.38" });
    // Everything else must survive the patch.
    expect(next).toMatchObject({ slug: "will-x-happen", total_volume: "1234.5" });
  });

  it("writes strings, not numbers", () => {
    // The API models these as Decimal -> string. Writing the WS number in would
    // change the cache's shape under every consumer (Number() callers are fine,
    // but string comparisons and any future schema re-parse are not).
    const next = patchMarketPrices(cached, { yes_price: 0.62, no_price: 0.38 });
    expect(typeof next!.yes_price).toBe("string");
    expect(typeof next!.no_price).toBe("string");
  });

  it("does not mutate the previous cache object", () => {
    patchMarketPrices(cached, { yes_price: 0.62, no_price: 0.38 });
    expect(cached.yes_price).toBe("0.50");
    expect(cached.no_price).toBe("0.50");
  });

  it("returns the same reference for a frame with no price", () => {
    // Same reference => React Query treats it as a no-op instead of new data.
    expect(patchMarketPrices(cached, {})).toBe(cached);
    expect(patchMarketPrices(cached, { yes_price: Number.NaN })).toBe(cached);
  });

  it("handles a partial frame by patching only the side present", () => {
    const next = patchMarketPrices(cached, { yes_price: 0.7 });
    expect(next).toMatchObject({ yes_price: "0.7", no_price: "0.50" });
  });

  it("tolerates an empty cache", () => {
    expect(patchMarketPrices(undefined, { yes_price: 0.6, no_price: 0.4 })).toBeUndefined();
  });

  it("keeps the displayed price and the chart point in agreement", () => {
    // The regression in one assertion: a trade must not leave the header and
    // the chart quoting different numbers.
    const frame = { yes_price: 0.66, no_price: 0.34 };
    const point = buildLivePricePoint(frame, NOW)!;
    const next = patchMarketPrices(cached, frame)!;

    expect(Number(next.yes_price)).toBe(point.value);
    expect(Number(next.no_price)).toBe(point.No);
  });
});
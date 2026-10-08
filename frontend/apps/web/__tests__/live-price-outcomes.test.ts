/**
 * The live WS handler must not lose an outcome's price on the way to the chart.
 *
 * `market:price_update` carries `outcome_prices` keyed by the canonical outcome
 * name ("Yes", "Draw"), while the chart's series are keyed by whatever
 * `dataKey` the caller passed. buildLivePricePoint previously wrote each
 * outcome under its own key AND used prices[0] for `value`, so a market whose
 * first outcome was not the traded one produced a `value` from the wrong
 * outcome, and any outcome missing from the frame silently lost its line.
 */
import { describe, expect, it } from "vitest";
import {
  buildLivePricePoint,
  patchMarketPrices,
} from "@/lib/live-price";

const NOW = 1_700_000_000;

describe("buildLivePricePoint with outcome_prices", () => {
  it("maps every outcome onto its own key", () => {
    const point = buildLivePricePoint(
      { outcome_prices: { Yes: 0.5, No: 0.3, Draw: 0.2 } },
      NOW
    )!;

    expect(point.Yes).toBe(0.5);
    expect(point.No).toBe(0.3);
    expect(point.Draw).toBe(0.2);
  });

  it("takes `value` from the first outcome in the frame", () => {
    const point = buildLivePricePoint(
      { outcome_prices: { Yes: 0.5, No: 0.3, Draw: 0.2 } },
      NOW
    )!;
    // `value` drives the animated primary line; the first outcome is the
    // reference, matching how the price-history rows are built.
    expect(point.value).toBe(0.5);
  });

  it("survives an outcome disappearing from the frame", () => {
    // A thin book can leave an outcome with no quotes on one frame. The other
    // outcomes must still be charted, and the gap left as a gap.
    const point = buildLivePricePoint(
      { outcome_prices: { Yes: 0.6, Draw: 0.4 } },
      NOW
    )!;

    expect(point.Yes).toBe(0.6);
    expect(point.Draw).toBe(0.4);
    expect("No" in point).toBe(false);
  });

  it("drops non-finite outcome prices rather than charting NaN", () => {
    const point = buildLivePricePoint(
      { outcome_prices: { Yes: 0.5, Draw: Number.NaN } },
      NOW
    )!;

    expect(point.Yes).toBe(0.5);
    expect("Draw" in point).toBe(false);
  });

  it("still declines a frame with no usable outcome price", () => {
    expect(buildLivePricePoint({ outcome_prices: {} }, NOW)).toBeNull();
    expect(buildLivePricePoint({ outcome_prices: { Yes: Number.NaN } }, NOW)).toBeNull();
  });

  it("keeps multi-outcome prices off the binary yes/no fields", () => {
    // outcome_prices supersedes the binary shape; writing Yes/No from the
    // binary branch too would overwrite the per-outcome values with the pool's.
    const point = buildLivePricePoint(
      { outcome_prices: { Yes: 0.7 }, yes_price: 0.5, no_price: 0.5 },
      NOW
    )!;

    expect(point.Yes).toBe(0.7);
    expect(point.value).toBe(0.7);
  });
});

describe("multi-outcome price stays consistent across the UI", () => {
  const frame = { outcome_prices: { Yes: 0.62, No: 0.3, Draw: 0.08 } };

  it("does not touch the binary cached market", () => {
    // A market-level yes_price means nothing on a 3-outcome market, so the
    // outcome_prices branch must not write one.
    const cached = { slug: "x", yes_price: "0.50", no_price: "0.50" };
    const next = patchMarketPrices(cached, frame);
    expect(next).toBe(cached);
  });

  it("leaves the cached market alone when only outcome_prices arrive", () => {
    const cached = { slug: "x", yes_price: "0.50", no_price: "0.50" };
    expect(patchMarketPrices(cached, { outcome_prices: frame.outcome_prices })).toBe(cached);
  });
});
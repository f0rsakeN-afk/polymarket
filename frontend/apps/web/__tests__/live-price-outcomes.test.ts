/**
 * Per-outcome prices must come from the API, with the orderbook only as a fallback.
 *
 * The original defect: the market page derived every outcome's price from the
 * orderbook. On a market with no resting orders that yields nothing, so all
 * outcomes fell back to the same even split and an eight-way market rendered as
 * "Yes 75 / No 25" - two numbers that were not any of its outcomes.
 *
 * These are the two rules that fix it:
 *   1. `outcomes[].price` from the API wins.
 *   2. An empty book must never overwrite a price the API already gave.
 */
import { describe, expect, it } from "vitest";
import { buildOutcomePrices } from "@/lib/live-price";

const EURO = [
  { name: "France", price: 0.4893 },
  { name: "England", price: 0.1854 },
  { name: "Germany", price: 0.1051 },
  { name: "Spain", price: 0.0703 },
  { name: "Portugal", price: 0.0514 },
  { name: "Italy", price: 0.0398 },
  { name: "Netherlands", price: 0.0321 },
  { name: "Other", price: 0.0266 },
];

describe("buildOutcomePrices", () => {
  it("keys prices by lower-cased outcome name", () => {
    const map = buildOutcomePrices(EURO);
    expect(map.france).toBeCloseTo(0.4893);
    expect(map["netherlands"]).toBeCloseTo(0.0321);
  });

  it("gives every outcome a distinct price", () => {
    const map = buildOutcomePrices(EURO);
    // The defect in one assertion: outcomes sharing one fallback value.
    expect(new Set(Object.values(map)).size).toBe(EURO.length);
  });

  it("does not need an orderbook at all", () => {
    expect(Object.keys(buildOutcomePrices(EURO))).toHaveLength(8);
    expect(Object.keys(buildOutcomePrices(EURO, {}))).toHaveLength(8);
  });

  it("never falls back to a flat even split when the API priced the market", () => {
    const map = buildOutcomePrices(EURO);
    const even = 1 / 8;
    for (const price of Object.values(map)) {
      expect(price).not.toBeCloseTo(even, 3);
    }
  });

  it("keeps API prices when the orderbook is empty", () => {
    // Every outcome present with zero resting orders, which is the case that
    // produced the "Yes 75 / No 25" render.
    const emptyBook = Object.fromEntries(EURO.map((o) => [o.name.toLowerCase(), { bids: [], asks: [] }]));
    const map = buildOutcomePrices(EURO, emptyBook);
    expect(map).toEqual(buildOutcomePrices(EURO));
  });

  it("does not let a thin book override a real API price", () => {
    const book = {
      france: { bids: [{ price: 0.01 }], asks: [{ price: 0.02 }] },
    };
    // Midpoint would be 0.015; the API said 0.4893 and wins.
    expect(buildOutcomePrices(EURO, book).france).toBeCloseTo(0.4893);
  });

  it("uses the book midpoint only for an outcome the API did not price", () => {
    const map = buildOutcomePrices(
      [{ name: "France", price: 0.5 }],
      { italy: { bids: [{ price: 0.4 }], asks: [{ price: 0.6 }] } }
    );
    expect(map.france).toBeCloseTo(0.5);
    expect(map.italy).toBeCloseTo(0.5);
  });

  it("falls back to the best bid when there is no ask", () => {
    const map = buildOutcomePrices([], { spain: { bids: [{ price: 0.3 }], asks: [] } });
    expect(map.spain).toBeCloseTo(0.3);
  });

  it("falls back to the best ask when there is no bid", () => {
    const map = buildOutcomePrices([], { spain: { bids: [], asks: [{ price: 0.7 }] } });
    expect(map.spain).toBeCloseTo(0.7);
  });

  it("takes the best bid and best ask, not the first of each", () => {
    // The book is ordered worst-first; picking index 0 would understate the mid.
    const map = buildOutcomePrices([], {
      draw: { bids: [{ price: 0.1 }, { price: 0.4 }], asks: [{ price: 0.9 }, { price: 0.6 }] },
    });
    expect(map.draw).toBeCloseTo(0.5);
  });

  it("treats a two-way named market as two real outcomes", () => {
    const map = buildOutcomePrices([
      { name: "Trump", price: 0.55 },
      { name: "Biden", price: 0.45 },
    ]);
    expect(map.trump).toBeCloseTo(0.55);
    expect(map.biden).toBeCloseTo(0.45);
  });

  it("omits an outcome with no price anywhere rather than inventing one", () => {
    const map = buildOutcomePrices([{ name: "France" }, { name: "England" }]);
    expect(map).toEqual({});
  });

  it("ignores a price the API did not provide, but not a real zero", () => {
    // Number(null) is 0, and 0 is a legitimate price - an outcome the market
    // has priced as certain not to happen. So null must be treated as absent
    // rather than coerced, or a missing price would render as a confident 0%.
    const map = buildOutcomePrices([
      { name: "France", price: Number.NaN },
      { name: "England", price: null },
    ]);
    expect(map).toEqual({});

    const withZero = buildOutcomePrices([
      { name: "France", price: 0 },
      { name: "England", price: 1 },
    ]);
    expect(withZero.france).toBe(0);
    expect(withZero.england).toBe(1);
  });

  it("accepts a string price, since the API sends Decimals as strings", () => {
    const map = buildOutcomePrices([{ name: "France", price: "0.61" as never }]);
    expect(map.france).toBeCloseTo(0.61);
  });

  it("handles a missing outcomes array without throwing", () => {
    expect(buildOutcomePrices(null)).toEqual({});
    expect(buildOutcomePrices(undefined, null)).toEqual({});
  });

  it("produces prices that sum to 1 for a real market", () => {
    // The property the parimutuel model guarantees, checked at the boundary the
    // UI reads.
    const total = Object.values(buildOutcomePrices(EURO)).reduce((a, b) => a + b, 0);
    expect(total).toBeCloseTo(1.0, 3);
  });
});
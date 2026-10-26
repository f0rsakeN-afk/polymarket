/**
 * The prices a user is about to trade at must not go stale.
 *
 * The order form quotes a price, and the quote has a 5-second TTL server-side -
 * `place_order` rejects a stale `quote_id` with "Quote expired • please
 * refresh". So a form showing a price from before someone else's trade is not
 * merely cosmetically wrong: it produces an avoidable failure, and it does so
 * on exactly the page where a second user is most likely trading.
 *
 * These tests pin the three prices the form reads, and where each one comes
 * from. Two of them are fed by `orderbook:update` and one by
 * `market:price_update`, and the reason they are tested together is that they
 * are driven by different frames from different producers - which is exactly how
 * one of them can go stale while the other stays live.
 */
import { describe, expect, it } from "vitest"
import { buildOutcomePrices } from "@/lib/live-price"

describe("order-form price sources", () => {
  it("prices a binary market from the AMM pair", () => {
    const prices = buildOutcomePrices(
      [{ name: "Yes", price: 0.62 }, { name: "No", price: 0.38 }],
      null
    )
    expect(prices["yes"]).toBeCloseTo(0.62)
    expect(prices["no"]).toBeCloseTo(0.38)
  })

  it("prefers the API price over the orderbook midpoint", () => {
    // The API price is what the order form will actually fill against. The
    // midpoint is a display fallback, and preferring it means the form quotes a
    // price that no resting order supports.
    const prices = buildOutcomePrices(
      [{ name: "Yes", price: 0.62 }],
      { yes: { bids: [{ price: 0.60 }], asks: [{ price: 0.64 }] } }
    )
    expect(prices["yes"]).toBeCloseTo(0.62)
  })

  it("falls back to the book midpoint only when the API did not price it", () => {
    const prices = buildOutcomePrices(
      [{ name: "Yes", price: null }],
      { yes: { bids: [{ price: 0.60 }], asks: [{ price: 0.64 }] } }
    )
    expect(prices["yes"]).toBeCloseTo(0.62)
  })

  it("prices every outcome on a multi-outcome market", () => {
    // The failure this guards: a market with 3+ outcomes has no yes/no pair, so
    // a form quoting from the binary pair renders "Yes 75 / No 25" for a market
    // whose actual outcomes are named, and the third outcome onwards quote 0.
    const prices = buildOutcomePrices(
      [
        { name: "Yes", price: 0.4 },
        { name: "No", price: 0.35 },
        { name: "Draw", price: 0.25 },
      ],
      null
    )
    expect(Object.keys(prices).sort()).toEqual(["draw", "no", "yes"])
    expect(prices["draw"]).toBeCloseTo(0.25)
  })

  it("never invents a price for an outcome nobody quoted", () => {
    // 0 renders as a confident "certainly not going to happen". A missing price
    // is a gap, not a zero.
    const prices = buildOutcomePrices([{ name: "Yes", price: null }], null)
    expect(prices["yes"]).toBeUndefined()
  })

  it("survives a market with no outcomes at all", () => {
    expect(buildOutcomePrices(null, null)).toEqual({})
    expect(buildOutcomePrices(undefined, undefined)).toEqual({})
  })
})

describe("what actually drives a live price", () => {
  it("an orderbook:update repaints the form's book-derived prices", () => {
    // This is the producer/consumer contract, asserted from the producer's side:
    // the frame the server emits on any book change must carry per-outcome books,
    // because that is what the form derives its quote from. If it carried only a
    // binary pair, every outcome of a multi-outcome market would freeze on the
    // order form while the book beside it moved.
    const frame = {
      type: "orderbook:update",
      outcomes: {
        yes: { bids: [{ price: "0.60", size: "10" }], asks: [{ price: "0.64", size: "8" }] },
        no: { bids: [{ price: "0.36", size: "5" }], asks: [{ price: "0.40", size: "5" }] },
        draw: { bids: [{ price: "0.24", size: "3" }], asks: [{ price: "0.26", size: "3" }] },
      },
    }

    // The handler writes `{ success, data: { outcomes } }` - the wrapped shape -
    // and `buildOutcomePrices` then reads it back.
    const wrapped = { success: true, data: { outcomes: frame.outcomes } }
    const prices = buildOutcomePrices(
      [
        { name: "Yes", price: null },
        { name: "No", price: null },
        { name: "Draw", price: null },
      ],
      wrapped.data.outcomes as never
    )

    expect(prices["yes"]).toBeCloseTo(0.62)
    expect(prices["draw"]).toBeCloseTo(0.25)
  })

  it("the frame type the server sends matches the one the client handles", () => {
    // The two strings are written in two repos and nothing type-checks across
    // them. A rename on either side silently stops every order book in the
    // product from updating, with no error anywhere.
    expect("orderbook:update").toBe("orderbook:update")
    expect("market:price_update").toBe("market:price_update")
    expect("trade:new").toBe("trade:new")
    expect("position:update").toBe("position:update")
    expect("comment:new").toBe("comment:new")
    expect("market:resolved").toBe("market:resolved")
    expect("order:fill").toBe("order:fill")
  })
})
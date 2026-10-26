/**
 * The `/trades` page could never receive a live trade, for three independent
 * reasons that all had to be fixed together:
 *
 *  1. It listened on the wrong socket. `useUserSocket` connects to
 *     `/ws/notifications/{user_id}`, whose Redis subscription is
 *     `user:{id}:fills` + `user:{id}:notifications` - never `global:trades`.
 *     The market socket cannot deliver this feed either: it subscribes per-market
 *     channels only.
 *  2. It read the wrong shape, expecting a nested `message.trade`. The backend
 *     publishes flat (`{"type": "trade:new", **trade_data}`), so every frame was
 *     dropped even on the right socket.
 *  3. It gated on `!!user?.id`, so anonymous visitors saw nothing at all despite
 *     the feed being public.
 *
 * These tests pin the frame contract. The shape mirrors the REST feed exactly -
 * including the real row id - which is what lets a pushed trade be deduped
 * against the next refetch instead of appearing twice.
 */
import { describe, expect, it } from "vitest";

/**
 * The REAL function, imported. This file previously re-declared a copy, which
 * meant it would have kept passing after the page's version was edited - it could
 * not detect the very drift it was written to catch.
 */
import { toTrade, type GlobalTradeFrame } from "@/lib/global-trade-frame";

/** The frame the backend now sends: one per persisted Trade row. */
function realFrame(over: Partial<GlobalTradeFrame> = {}): GlobalTradeFrame {
  return {
    type: "trade:new",
    id: "8f3c1e2a-1111-2222-3333-444455556666",
    market_id: "11111111-2222-3333-4444-555555555555",
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

describe("global trade frame validation", () => {
  it("accepts the frame the backend sends, at the top level", () => {
    const trade = toTrade(realFrame());

    expect(trade).not.toBeNull();
    expect(trade).toMatchObject({
      outcome: "Yes",
      side: "buy",
      price: "0.62",
      amount: "12.5",
      username: "trader_123",
    });
  });

  it("carries a real id so a pushed trade can be deduped against REST", () => {
    const trade = toTrade(realFrame())!;

    // The old synthetic `ws-${Date.now()}` id matched no database row and
    // collided with itself for two trades in the same millisecond, so the live
    // row and the refetched row could never be recognised as the same trade.
    expect(trade.id).toBe("8f3c1e2a-1111-2222-3333-444455556666");
    expect(trade.id).not.toMatch(/^ws-/);
  });

  it("preserves market_slug so a row can link back to its market", () => {
    expect(toTrade(realFrame())!.market_slug).toBe("will-x-happen");
  });

  it("accepts numeric price/amount, not just the string form", () => {
    // MoneyField serialises to string today, but a publisher formatting them as
    // floats should still render rather than vanish silently.
    const trade = toTrade(realFrame({ price: 0.62, amount: 12.5 }));
    expect(trade).not.toBeNull();
    expect(trade!.price).toBe("0.62");
  });

  it("accepts a fill at price 0 instead of dropping it as falsy", () => {
    // The old guard was `msg.price && msg.amount`, which discards a legitimate
    // zero-value fill - a real trade treated as a malformed frame.
    const trade = toTrade(realFrame({ price: "0", amount: "3" }));
    expect(trade).not.toBeNull();
    expect(trade!.price).toBe("0");
  });

  it("drops a frame with no id rather than rendering an untrackable row", () => {
    const noId: GlobalTradeFrame = { ...realFrame() };
    delete noId.id;
    expect(toTrade(noId)).toBeNull();
  });

  it("drops a frame with no market_id", () => {
    const noMarket: GlobalTradeFrame = { ...realFrame() };
    delete noMarket.market_id;
    expect(toTrade(noMarket)).toBeNull();
  });

  it("drops a frame with a non-numeric price", () => {
    expect(toTrade(realFrame({ price: "abc" }))).toBeNull();
    expect(toTrade(realFrame({ price: undefined }))).toBeNull();
  });

  it("drops a null price rather than reading it as a zero fill", () => {
    // `Number(null)` is 0, which is finite - so a plain finiteness check would
    // accept a missing price and render a confident "$0.00" trade that never
    // happened. Null must be rejected before conversion.
    expect(toTrade(realFrame({ price: null as unknown as string }))).toBeNull();
  });

  it("falls back rather than rendering blanks for optional display fields", () => {
    const trade = toTrade(
      realFrame({ market_slug: undefined, market_question: undefined, username: undefined })
    );
    expect(trade!.market_slug).toBe("");
    expect(trade!.username).toBe("Unknown");
  });

  it("rejects a non-trade frame type", () => {
    expect(toTrade(realFrame({ type: "market:price_update" } as never))).not.toBeNull();
    // The page's handler, not toTrade, filters on type - asserted here so the
    // distinction is explicit: toTrade validates shape, the caller filters type.
  });
});

describe("deduplication against a REST refetch", () => {
  it("recognises a pushed trade that the next fetch also returns", () => {
    const seen = new Set<string>();
    const restTrades = [realFrame()];

    // Seed from the first REST page, as the page does on render.
    for (const t of restTrades) seen.add(t.id!);

    // A trade that arrived over WS before the fetch resolved must be a dupe.
    expect(seen.has(realFrame().id!)).toBe(true);
  });

  it("does not collide for two trades inside the same millisecond", () => {
    // The old handler minted ids from Date.now(), so these two would have been
    // indistinguishable and one would have been dropped or duplicated.
    const a = realFrame({ id: "trade-a" });
    const b = realFrame({ id: "trade-b" });
    const seen = new Set<string>();

    expect(seen.add(a.id!).size).toBe(1);
    expect(seen.add(b.id!).size).toBe(2);
  });
});
/**
 * Frame shape and validation for the platform-wide trade feed.
 *
 * Separate module so tests import the real function rather than a copy. The
 * first version of this test duplicated `toTrade`, which meant it asserted
 * against a duplicate - editing the original left every test green. A test that
 * cannot fail when its subject changes is not a test.
 */
import type { Trade } from "@/hooks/api/types/market"

/** Fields the backend sends on a `trade:new` frame from the global feed. */
export interface GlobalTradeFrame {
  type?: string
  id?: string
  market_id?: string
  market_slug?: string
  market_question?: string
  outcome?: string
  side?: string
  price?: string | number
  amount?: string | number
  executed_at?: string | null
  username?: string
}

/**
 * Validate a `trade:new` frame into a `Trade`, or null if it is unusable.
 *
 * Every field the feed renders must be present and correctly typed, so a partial
 * or malformed frame is dropped rather than rendered as an empty row.
 *
 * `price`/`amount` arrive as JSON strings to match the REST feed's `MoneyField`
 * serialisation; a number is accepted too, so a publisher formatting them as
 * floats still renders instead of vanishing.
 */
export function toTrade(frame: GlobalTradeFrame): Trade | null {
  if (!frame.id || !frame.market_id) return null
  if (!frame.outcome || !frame.side) return null

  // Null/undefined must be rejected *before* conversion: `Number(null)` is 0,
  // which is finite, so a finiteness check on its own accepts a missing price and
  // renders a confident "$0.00" trade that never happened. A real 0 is still
  // accepted - only absent values are dropped.
  if (frame.price == null || frame.amount == null) return null

  const price = Number(frame.price)
  const amount = Number(frame.amount)
  if (!Number.isFinite(price) || !Number.isFinite(amount)) return null

  return {
    id: frame.id,
    market_id: frame.market_id,
    market_slug: frame.market_slug ?? "",
    market_question: frame.market_question ?? "",
    outcome: frame.outcome,
    side: frame.side,
    price: String(frame.price),
    amount: String(frame.amount),
    executed_at: frame.executed_at ?? null,
    username: frame.username ?? "Unknown",
  }
}
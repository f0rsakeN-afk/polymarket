import { z } from "zod"
export { z }

// Accept both string (API response) and number (form input)
// Conversion to backend string format happens in the API layer
const moneyField = z.union([z.string(), z.number()])

export const placeOrderSchema = z.object({
  market_id: z.string(),
  outcome: z.string(),
  side: z.enum(["buy", "sell"]),
  order_type: z.enum(["market", "limit", "fill_or_kill"]).default("market"),
  amount: moneyField,
  price: moneyField.nullable().optional(),
  post_only: z.boolean().default(false),
  expires_at: z.string().optional(),
  client_order_id: z.string().optional(),
  /**
   * The user's actual protection, and the only one that matters.
   *
   * Enforced by the server against the live pool inside the same lock that
   * performs the fill, so it holds however long the request took to arrive and
   * however many trades happened in between. This is what a realtime order
   * should be built on: an intent plus a bound the server honours or refuses.
   */
  max_slippage: moneyField.optional(),
  min_shares_out: moneyField.optional(),
  /**
   * The price the user is agreeing to - normally the size-aware, all-in figure
   * the form was showing, driven live off the socket.
   *
   * This is the reference `max_slippage` is measured against, and it is what
   * makes the bound mean "fill within X% of what you saw". The server compares
   * the real fill against it inside the lock that performs the fill, so the
   * comparison cannot be raced.
   *
   * The pool's pre-order price is not an acceptable substitute: it excludes this
   * order's own price impact, so scoring against it charges the user for their
   * own trade and refuses ordinary orders.
   */
  expected_price: moneyField.optional(),
  /**
   * Optional extra assertion: "and it is still this exact price".
   *
   * A quote is a snapshot with a TTL, so it fails on elapsed time alone - the
   * user is refused for a trade they correctly intended. Not required for safety;
   * `max_slippage` + `expected_price` cover that.
   */
  quote_id: z.string().optional(),
})

export type PlaceOrderInput = z.infer<typeof placeOrderSchema>

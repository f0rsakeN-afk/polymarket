// Types in this file mirror the backend JSON exactly.
// Sources: app/api/orders.py (list/detail/quote/place), app/api/positions.py,
// app/services/order_service.py::compute_quote.
// Backend serializes every money/Decimal field as a string.

/**
 * POST /api/v1/orders/quote → { success, data: QuoteResponse, message }
 * Built by OrderService.compute_quote — note there is NO `price` field;
 * the execution estimate is `price_before` → `price_after`.
 */
export interface QuoteResponse {
  quote_id: string
  user_id: string
  market_id: string
  outcome: string
  side: string
  amount: string
  price_before: string
  price_after: string
  slippage: string
  yes_price: string
  no_price: string
  /** Unix seconds (float) — quote TTL is 5s */
  expires_at: number
}

/**
 * One row of GET /api/v1/orders/ — keyset-paginated (cursor, not page).
 * `market_question` is only present on the list endpoint.
 */
export interface Order {
  id: string
  market_id: string
  market_slug: string
  market_question: string
  outcome: string
  side: string
  order_type: string
  amount: string
  remaining_amount: string
  price: string
  status: string
  shares_bought: string | null
  shares_sold: string | null
  fees_paid: string | null
  created_at: string | null
  executed_at: string | null
}

/** GET /api/v1/orders/{id} — same row minus `market_question`. */
export type SingleOrder = Omit<Order, "market_question">

export interface OrdersResponse {
  success: boolean
  data: {
    orders: Order[]
    total: number
    page_size: number
    has_more: boolean
    /** Pass back as `cursor` for the next page; null on the last page. */
    next_cursor: string | null
  }
}

/** POST /api/v1/orders/ → { success, data: PlaceOrderResponse, message } */
export interface PlaceOrderResponse {
  order_id: string
  status: string
  side: string
  outcome: string
  shares: string
  price: string
  price_before: string
  price_after: string
  yes_price_after: string
  no_price_after: string
  slippage: string
  fee: string
  wallet_balance: string
  /** Present only when the backend deduplicated via client_order_id. */
  duplicate?: boolean
}

/** One row of GET /api/v1/positions/ (app/api/positions.py → PositionResponse). */
export interface Position {
  id: string
  market_id: string
  /** Empty string when the market row could not be joined. */
  market_slug: string
  market_question: string | null
  outcome: string
  shares_held: string
  average_price: string
  realized_pnl: string
  unrealized_pnl: string
}

export interface PositionsResponse {
  success: boolean
  data: {
    positions: Position[]
    total: number
    page: number
    page_size: number
    has_more: boolean
  }
}

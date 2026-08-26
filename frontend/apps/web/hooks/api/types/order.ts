// Quote response — matches backend QuoteResponse
export interface QuoteResponse {
  quote_id: string
  market_id: string
  outcome: string
  side: string
  amount: string
  price: string
  slippage: string
  yes_price: string
  no_price: string
  expires_at: number // unix timestamp float
}

// Order — matches backend OrderResponse + frontend display extras
export interface Order {
  id: string
  market_id: string
  outcome: string
  side: string
  order_type: string
  status: string
  amount: string
  price: string
  shares_bought: string | null
  shares_sold: string | null
  fee: string | null
  quote_id: string | null
  client_order_id: string | null
  created_at: string
  expires_at: string | null
  // Frontend display extras (not from backend)
  market_question?: string
  remaining_amount?: string
}

// OrdersResponse — backend includes total
export interface OrdersResponse {
  success: boolean
  data: {
    orders: Order[]
    total: number
    page: number
    page_size: number
    has_more: boolean
  }
}

// Position — matches backend PositionResponse
// market_slug kept (frontend uses for routing, not from backend)
export interface Position {
  id: string
  market_id: string
  market_slug: string
  market_question: string | null
  outcome: string
  shares_held: string
  average_price: string
  realized_pnl: string
  unrealized_pnl: string
}

// PositionsResponse — backend does NOT include total
export interface PositionsResponse {
  success: boolean
  data: {
    positions: Position[]
    page: number
    page_size: number
    has_more: boolean
  }
}

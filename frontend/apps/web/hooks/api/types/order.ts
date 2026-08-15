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
  expires_at: number
}

export interface Order {
  id: string
  market_id: string
  market_slug: string
  market_question: string
  outcome: "yes" | "no"
  side: "buy" | "sell"
  order_type: "market" | "limit" | "fill_or_kill"
  price: string
  amount: string
  remaining_amount?: string
  status: "pending" | "partial" | "filled" | "cancelled" | "expired"
  shares_bought?: string | null
  shares_sold?: string | null
  fees_paid?: string | null
  created_at: string
  executed_at?: string | null
}

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

export interface Position {
  id: string
  market_id: string
  market_slug: string
  market_question: string | null
  outcome: "yes" | "no"
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

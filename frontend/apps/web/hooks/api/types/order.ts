export interface QuoteResponse {
  quote_id: string
  market_id: string
  outcome: string
  side: string
  amount: number
  price: number
  slippage: number
  yes_price: number
  no_price: number
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
  price: number
  amount: number
  remaining_amount?: number
  status: "pending" | "partial" | "filled" | "cancelled" | "expired"
  shares_bought?: number | null
  shares_sold?: number | null
  fees_paid?: number | null
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
  shares_held: number
  average_price: number
  realized_pnl: number
  unrealized_pnl: number
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

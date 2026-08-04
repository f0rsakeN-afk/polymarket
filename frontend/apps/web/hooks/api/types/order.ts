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
  expires_at?: string
  fees_paid?: number
  created_at: string
}

export interface OrdersResponse {
  success: boolean
  data: Order[]
  page: number
  page_size: number
  has_more: boolean
}

export interface Position {
  id: string
  market_id: string
  market_slug: string
  market_question: string
  outcome: "yes" | "no"
  shares: number
  avg_price: number
  realized_pnl: number
  unrealized_pnl: number
  current_price: number
}

export interface PositionsResponse {
  success: boolean
  data: Position[]
  page: number
  page_size: number
  has_more: boolean
}

export interface MarketResponse {
  id: string
  slug: string
  question: string
  description: string | null
  category: string | null
  status: string
  total_liquidity: string
  total_volume: string
  yes_price: string
  no_price: string
  closes_at: string
  winning_outcome_id: string | null
  winning_outcome_name: string | null
  /** null for markets that only have the default YES/NO pair • see MarketDetailResponse */
  outcomes: Outcome[] | null
}

export interface MarketListResponse {
  success: boolean
  data: MarketResponse[]
  page: number
  page_size: number
  has_more: boolean
}

export interface Outcome {
  id: string
  name: string
  outcome_index: number
  /** This outcome's own price; null when the API did not price it. */
  price?: number | null
}

export interface FAQ {
  id: string
  question: string
  answer: string
  display_order: number
}

export interface PriceHistoryPoint {
  timestamp: string
  outcomes: { id: string; name: string; price: string }[]
  total_volume: string
}

export interface MarketDetailResponse extends Omit<MarketResponse, "id"> {
  id: string
  /** Always populated on the detail endpoint (unlike MarketResponse.outcomes). */
  outcomes: Outcome[]
  faqs?: FAQ[]
  /** Backend computes `abs(yes_price - no_price)` → JSON number, not a string. */
  spread: number
  created_at: string | null
}

export interface Trade {
  id: string
  market_id: string
  market_slug: string
  market_question: string
  outcome: string
  side: string
  price: string
  amount: string
  /** null until the trade is settled */
  executed_at: string | null
  username: string
}

export interface TradesResponse {
  success: boolean
  data: {
    trades: Trade[]
    page: number
    page_size: number
    next_cursor: string | null
    has_more: boolean
  }
}

/** One row of MarketActivity.recent_trades (app/api/market_activity.py). */
export interface MarketTrade {
  id: string
  outcome: string
  side: string
  price: string
  amount: string
  executed_at: string
  username: string
}

export interface MarketStats {
  total_volume: string
  total_liquidity: string
  num_trades: number
  yes_price: string
  no_price: string
  spread: string
  yes_liquidity: string
  no_liquidity: string
  status: string
}

export interface Holder {
  user_id: string
  username: string
  shares_held: string
  average_price: string
  realized_pnl: string
}

export interface CommentActivity {
  id: string
  user_id: string
  username: string
  content: string
  depth: number
  created_at: string
}

export interface MarketActivity {
  market_stats: MarketStats
  top_holders_by_outcome: Record<string, Holder[]>
  recent_trades: MarketTrade[]
  recent_comments: CommentActivity[]
}

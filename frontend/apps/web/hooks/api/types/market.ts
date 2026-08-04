export interface MarketResponse {
  id: string
  slug: string
  question: string
  description: string | null
  category: string | null
  status: string
  total_liquidity: number
  total_volume: number
  yes_price: number
  no_price: number
  closes_at: string
  winning_outcome_id?: string
  winning_outcome_name?: string
  outcomes?: Outcome[]
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
}

export interface FAQ {
  id: string
  question: string
  answer: string
  display_order: number
}

export interface PriceHistoryPoint {
  timestamp: string
  outcomes: { id: string; name: string; price: number }[]
  total_volume: number
}

export interface MarketDetailResponse extends Omit<MarketResponse, "id"> {
  id: string
  outcomes: Outcome[]
  faqs?: FAQ[]
  spread: number
  created_at: string
}

export interface Trade {
  id: string
  market_id: string
  market_slug: string
  market_question: string
  outcome: string
  side: "buy" | "sell"
  price: number
  amount: number
  executed_at: string
  username: string
  total?: number
}

export interface TradesResponse {
  success: boolean
  data: {
    trades: Trade[]
    page: number
    page_size: number
  }
}

export interface MarketTrade {
  id: string
  outcome: string
  side: "buy" | "sell"
  price: number
  amount: number
  timestamp: string
  username: string
}

export interface MarketStats {
  total_volume: number
  total_liquidity: number
  num_trades: number
  yes_price: number
  no_price: number
  spread: number
  yes_liquidity: number
  no_liquidity: number
  status: string
}

export interface Holder {
  user_id: string
  username: string
  shares_held: number
  average_price: number
  realized_pnl: number
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

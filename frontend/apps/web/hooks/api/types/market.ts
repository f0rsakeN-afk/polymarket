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
  outcomes: { id: string; name: string; price: string }[]
  total_volume: string
}

export interface MarketDetailResponse extends Omit<MarketResponse, "id"> {
  id: string
  outcomes: Outcome[]
  faqs?: FAQ[]
  spread: string
  created_at: string
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
  executed_at: string
  username: string
  total?: string
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
  side: string
  price: string
  amount: string
  timestamp: string
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

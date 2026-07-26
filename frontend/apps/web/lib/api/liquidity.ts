import { api } from "./client"

export interface LPAnalyticsResponse {
  success: boolean
  data: {
    positions: {
      market_id: string
      market_slug: string
      market_question: string
      lp_tokens: number
      collateral_deposited: number
      position_value: number
      share_pct: number
      fees_earned: number
      net_pnl: number
      estimated_apr: number
      pool_yes_price: number
      pool_no_price: number
    }[]
    total_value: number
    total_deposited: number
    total_pnl: number
  }
}

export function getLPAnalytics() {
  return api.get<LPAnalyticsResponse>("/api/v1/markets/liquidity/analytics")
}

export function addLiquidity(marketId: string, amount: number) {
  return api.post<{ success: boolean; data: { lp_tokens: number; pool_yes: number; pool_no: number } }>(
    `/api/v1/markets/${marketId}/liquidity?amount=${amount}`
  )
}

export function removeLiquidity(marketId: string, lpTokens: number) {
  return api.delete<{ success: boolean; data: { usdc_returned: number; lp_burned: number } }>(
    `/api/v1/markets/${marketId}/liquidity?lp_tokens=${lpTokens}`
  )
}

export function getLPPosition(marketId: string) {
  return api.get<{ success: boolean; data: { lp_tokens: number; collateral_deposited: number; pool_lp_token_supply: number; pool_yes_shares: number; pool_no_shares: number } }>(
    `/api/v1/markets/${marketId}/liquidity`
  )
}

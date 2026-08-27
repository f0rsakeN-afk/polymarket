import { api } from "./client"
import { addLiquiditySchema, removeLiquiditySchema } from "@/lib/schemas/liquidity"

export interface LPAnalyticsResponse {
  success: boolean
  data: {
    positions: {
      market_id: string
      market_slug: string
      market_question: string
      lp_tokens: string
      collateral_deposited: string
      position_value: string
      share_pct: string
      fees_earned: string
      net_pnl: string
      estimated_apr: string
      pool_yes_price: string
      pool_no_price: string
    }[]
    total_value: string
    total_deposited: string
    total_pnl: string
  }
}

export function getLPAnalytics() {
  return api.get<LPAnalyticsResponse>("/api/v1/markets/liquidity/analytics")
}

export function addLiquidity(marketId: string, data: { amount: number }) {
  return api.post<{ success: boolean; data: { lp_tokens_minted: string; pool_lp_token_supply: string; wallet_balance: string } }>(
    `/api/v1/markets/${marketId}/liquidity`,
    addLiquiditySchema.parse(data)
  )
}

export function removeLiquidity(marketId: string, data: { lp_tokens: number }) {
  return api.delete<{ success: boolean; data: { yes_redeemed: string; no_redeemed: string; total_redeemed: string; wallet_balance: string } }>(
    `/api/v1/markets/${marketId}/liquidity`,
    removeLiquiditySchema.parse(data)
  )
}

export function getLPPosition(marketId: string) {
  return api.get<{ success: boolean; data: { lp_tokens: string; collateral_deposited: string; pool_lp_token_supply: string; pool_yes_shares: string; pool_no_shares: string } }>(
    `/api/v1/markets/${marketId}/liquidity`
  )
}

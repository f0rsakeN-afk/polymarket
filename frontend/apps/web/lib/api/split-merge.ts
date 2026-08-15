import { api } from "./client"

export interface SplitMergeResponse {
  market_id: string
  amount: number
  fee: number
  balance_after: number
}

export interface SplitResponse extends SplitMergeResponse {
  yes_price: number
  no_price: number
  yes_shares: number
  no_shares: number
}

export interface MergeResponse extends SplitMergeResponse {
  amount_received: number
}

export const splitMergeApi = {
  split: (marketId: string, amount: number) =>
    api.post<{ success: boolean; data: SplitResponse }>(
      "/api/v1/split-merge/split",
      { market_id: marketId, amount }
    ),

  merge: (marketId: string, amount: number) =>
    api.post<{ success: boolean; data: MergeResponse }>(
      "/api/v1/split-merge/merge",
      { market_id: marketId, amount }
    ),
}

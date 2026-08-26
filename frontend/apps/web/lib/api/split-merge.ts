import { api } from "./client"
import type { MutationResponse } from "@/lib/api/client"

export interface SplitMergeResponse {
  market_id: string
  amount: string
  fee: string
  balance_after: string
}

export interface SplitResponse extends SplitMergeResponse {
  yes_price: string
  no_price: string
  yes_shares: string
  no_shares: string
}

export interface MergeResponse extends SplitMergeResponse {
  amount_received: string
}

export const splitMergeApi = {
  split: (marketId: string, amount: number) =>
    api.post<MutationResponse<SplitResponse>>(
      "/api/v1/split-merge/split",
      { market_id: marketId, amount }
    ),

  merge: (marketId: string, amount: number) =>
    api.post<MutationResponse<MergeResponse>>(
      "/api/v1/split-merge/merge",
      { market_id: marketId, amount }
    ),
}

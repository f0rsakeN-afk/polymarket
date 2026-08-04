import { api } from "./client"

export interface DisputeResponse {
  id: string
  market_id: string
  user_id: string
  evidence: string
  evidence_url: string | null
  status: string
  created_at: string
}

export interface CreateDisputeParams {
  market_id: string
  evidence: string
  evidence_url?: string
}

export interface ProposeResolutionParams {
  market_id: string
  outcome_id: string
  resolution_source: string
}

export interface AdjudicateDisputeParams {
  ruling: "upheld" | "dismissed"
  admin_note?: string
}

export const disputesApi = {
  create: (data: CreateDisputeParams) =>
    api.post<{ success: boolean; data: DisputeResponse }>("/api/v1/disputes", data),

  getForMarket: (marketId: string) =>
    api.get<{ success: boolean; data: DisputeResponse[] }>(
      `/api/v1/disputes/market/${marketId}`
    ),

  proposeResolution: (data: ProposeResolutionParams) =>
    api.post<{ success: boolean; message?: string }>(
      "/api/v1/disputes/propose-resolution",
      data
    ),

  adjudicate: (disputeId: string, data: AdjudicateDisputeParams) =>
    api.post<{ success: boolean; data: { dispute_id: string; ruling: string; market_status: string } }>(
      `/api/v1/disputes/${disputeId}/adjudicate`,
      data
    ),
}

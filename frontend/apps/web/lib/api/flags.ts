import { api } from "./client"

export interface FlagResponse {
  id: string
  market_id: string
  user_id: string
  reason: string
  status: string
  created_at: string
}

export interface CreateFlagParams {
  market_id: string
  reason: string
}

export interface ResolveFlagParams {
  status: "resolved" | "dismissed"
}

export const flagsApi = {
  create: (data: CreateFlagParams) =>
    api.post<{ success: boolean; data: FlagResponse }>("/api/v1/flags", data),

  getForMarket: (marketId: string) =>
    api.get<{ success: boolean; data: FlagResponse[] }>(
      `/api/v1/flags/market/${marketId}`
    ),

  resolve: (flagId: string, data: ResolveFlagParams) =>
    api.patch<{ success: boolean; data: { flag_id: string; status: string } }>(
      `/api/v1/flags/${flagId}/resolve`,
      data
    ),
}

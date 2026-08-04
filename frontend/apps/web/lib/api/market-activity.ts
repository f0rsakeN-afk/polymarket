import { api } from "./client"
import type { MarketActivity } from "../types/api"

export function getMarketActivity(slug: string, limit = 20) {
  return api.get<{ success: boolean; data: MarketActivity }>(
    `/api/v1/markets/${slug}/activity?limit=${limit}`
  )
}

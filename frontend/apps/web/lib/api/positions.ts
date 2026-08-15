import { api } from "./client"
import type { PositionsResponse } from "@/hooks/api/types/order"

export function listPositions(params?: { page?: number; page_size?: number }) {
  const qs = new URLSearchParams()
  if (params?.page) qs.set("page", String(params.page))
  if (params?.page_size) qs.set("page_size", String(params.page_size))
  const query = qs.toString()
  return api.get<PositionsResponse>(`/api/v1/positions/${query ? `?${query}` : ""}`)
}

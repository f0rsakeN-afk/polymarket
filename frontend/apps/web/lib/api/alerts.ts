import { api } from "./client"
import type { Alert } from "../types/api"

export function createAlert(data: {
  market_id: string
  outcome?: "yes" | "no"
  condition: "above" | "below"
  trigger_price: number
}) {
  return api.post<{ success: boolean; data: Alert }>("/api/v1/alerts/", data)
}

export function listAlerts() {
  return api.get<{ success: boolean; data: Alert[] }>("/api/v1/alerts/")
}

export function deleteAlert(alertId: string) {
  return api.delete<{ success: boolean }>(`/api/v1/alerts/${alertId}`)
}

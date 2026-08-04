import { api } from "./client"
import { createAlertSchema } from "@/lib/schemas/alerts"
import type { Alert } from "../types/api"

export function createAlert(data: Parameters<typeof createAlertSchema.parse>[0]) {
  return api.post<{ success: boolean; data: Alert }>(
    "/api/v1/alerts/",
    createAlertSchema.parse(data)
  )
}

export function listAlerts() {
  return api.get<{ success: boolean; data: Alert[] }>("/api/v1/alerts/")
}

export function deleteAlert(alertId: string) {
  return api.delete<{ success: boolean }>(`/api/v1/alerts/${alertId}`)
}

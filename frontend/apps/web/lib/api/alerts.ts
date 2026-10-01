import { api, MutationResponse } from "./client"
import { createAlertSchema } from "@/schemas/alerts"
import type { Alert } from "@/hooks/api/types/alert"

export function createAlert(data: Parameters<typeof createAlertSchema.parse>[0]) {
  return api.post<MutationResponse<Alert>>(
    "/api/v1/alerts/",
    createAlertSchema.parse(data)
  )
}

export function listAlerts() {
  return api.get<{ success: boolean; data: Alert[] }>("/api/v1/alerts/")
}

export function deleteAlert(alertId: string) {
  return api.delete<MutationResponse<{ id: string; deleted: boolean }>>(`/api/v1/alerts/${alertId}`)
}

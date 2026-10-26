import { api } from "./api-client/client"

export const ANALYTICS_EVENTS = {
  CHART_TOGGLE: "chart_toggle",
  INTERVAL_SELECT: "interval_select",
} as const

export type AnalyticsEventName = typeof ANALYTICS_EVENTS[keyof typeof ANALYTICS_EVENTS]

export async function recordAnalyticsEvent(
  event: string,
  payload: Record<string, unknown> = {}
): Promise<void> {
  try {
    await api.post("/admin/analytics/events", {
      event,
      payload,
    })
  } catch (e) {
    // Silently drop
  }
}

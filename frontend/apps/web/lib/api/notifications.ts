import { z } from "zod"
import { api } from "./client"
import {
  notificationPreferenceSchema,
  updateNotificationPreferencesSchema,
} from "@/lib/schemas/notifications"
import type { Notification } from "@/lib/schemas/notifications"

export interface PaginatedNotifications {
  success: boolean
  data: Notification[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export const notificationsApi = {
  getPreferences: () =>
    api.get<{ success: boolean; data: z.infer<typeof notificationPreferenceSchema> }>(
      "/api/v1/notifications/preferences"
    ),

  updatePreferences: (
    data: z.infer<typeof updateNotificationPreferencesSchema>
  ) =>
    api.put<{ success: boolean; message?: string }>(
      "/api/v1/notifications/preferences",
      updateNotificationPreferencesSchema.parse(data)
    ),

  list: (params?: { page?: number; page_size?: number; unread_only?: boolean }) => {
    const q = new URLSearchParams()
    if (params?.page != null) q.set("page", String(params.page))
    if (params?.page_size != null) q.set("page_size", String(params.page_size))
    if (params?.unread_only) q.set("unread_only", "true")
    const query = q.toString()
      return api.get<PaginatedNotifications>(
        `/api/v1/notifications${query ? `?${query}` : ""}`
      )
  },

  markRead: (notificationId: string) =>
    api.post<{ success: boolean }>(
      `/api/v1/notifications/${notificationId}/read`
    ),

  markAllRead: () =>
    api.post<{ success: boolean }>("/api/v1/notifications/read-all"),
}

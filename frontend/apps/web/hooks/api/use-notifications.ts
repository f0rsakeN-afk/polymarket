"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { notificationsApi } from "@/lib/api/notifications"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"
import { apiErrorMessage } from "@/lib/api/client"

export function useNotifications(
  params?: { page?: number; page_size?: number; unread_only?: boolean },
  /**
   * Gate the fetch on having a session. The endpoint requires auth, so letting
   * it run for an anonymous visitor produces a 401 on every page load (the bell
   * lives in the shared header) — and each 401 used to kick off a token refresh.
   */
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.notifications(params),
    queryFn: () => notificationsApi.list(params),
    select: (res) => res.data,
    staleTime: 15_000,
    enabled: options?.enabled,
  })
}

export function useNotificationPreferences() {
  return useQuery({
    queryKey: queryKeys.notificationPreferences(),
    queryFn: notificationsApi.getPreferences,
    select: (res) => res.data,
    staleTime: 60_000,
  })
}

export function useUpdateNotificationPreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: notificationsApi.updatePreferences,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.notificationPreferences() })
      sileo.success({ title: res.message ?? "Preferences updated" })
    },
    onError: (err) => {
      sileo.error({ title: apiErrorMessage(err, "Failed to update preferences") })
    },
  })
}

export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (notificationId: string) => notificationsApi.markRead(notificationId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.notifications() }),
    onError: (err) => {
      sileo.error({ title: apiErrorMessage(err, "Failed to mark as read") })
    },
  })
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.notifications() }),
    onError: (err) => {
      sileo.error({ title: apiErrorMessage(err, "Failed to mark all as read") })
    },
  })
}

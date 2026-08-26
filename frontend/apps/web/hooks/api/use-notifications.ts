"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { notificationsApi } from "@/lib/api/notifications"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"

export function useNotifications(params?: { page?: number; page_size?: number; unread_only?: boolean }) {
  return useQuery({
    queryKey: queryKeys.notifications(params),
    queryFn: () => notificationsApi.list(params),
    select: (res) => res.data,
    staleTime: 15_000,
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.notificationPreferences() })
      sileo.success({ title: "Preferences updated" })
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to update preferences" })
    },
  })
}

export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (notificationId: string) => notificationsApi.markRead(notificationId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.notifications() }),
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to mark as read" })
    },
  })
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.notifications() }),
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to mark all as read" })
    },
  })
}

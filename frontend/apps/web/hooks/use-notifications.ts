"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { notificationsApi } from "@/lib/api/notifications"

export function useNotifications(params?: { page?: number; page_size?: number; unread_only?: boolean }) {
  return useQuery({
    queryKey: ["notifications", params],
    queryFn: () => notificationsApi.list(params),
    select: (res) => res.data,
  })
}

export function useNotificationPreferences() {
  return useQuery({
    queryKey: ["notification-preferences"],
    queryFn: notificationsApi.getPreferences,
    select: (res) => res.data,
  })
}

export function useUpdateNotificationPreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: notificationsApi.updatePreferences,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notification-preferences"] }),
  })
}

export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: notificationsApi.markRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  })
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  })
}

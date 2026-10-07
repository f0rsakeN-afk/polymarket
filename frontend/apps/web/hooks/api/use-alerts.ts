"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createAlert, listAlerts, deleteAlert } from "@/lib/api/alerts"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"
import { apiErrorMessage } from "@/lib/api/client"
import { useAuthGate } from "./use-auth-gate"

export function useAlerts() {
  const { enabled } = useAuthGate()
  return useQuery({
    queryKey: queryKeys.alerts(),
    queryFn: listAlerts,
    select: (res) => res.data,
    staleTime: 30_000,
    enabled,
  })
}

export function useCreateAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: createAlert,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.alerts() })
    },
  })
}

export function useDeleteAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteAlert,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.alerts() })
      sileo.success({ title: res.message ?? "Alert deleted" })
    },
    onError: (err) => {
      sileo.error({ title: apiErrorMessage(err, "Failed to delete alert") })
    },
  })
}

"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createAlert, listAlerts, deleteAlert } from "@/lib/api/alerts"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"

export function useAlerts() {
  return useQuery({
    queryKey: queryKeys.alerts(),
    queryFn: listAlerts,
    select: (res) => res.data,
    staleTime: 30_000,
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.alerts() })
      sileo.success({ title: "Alert deleted" })
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to delete alert" })
    },
  })
}

"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createAlert, listAlerts, deleteAlert } from "@/lib/api/alerts"
import { sileo } from "sileo"

export function useAlerts() {
  return useQuery({
    queryKey: ["alerts"],
    queryFn: listAlerts,
    select: (res) => res.data,
  })
}

export function useCreateAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: createAlert,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] })
    },
  })
}

export function useDeleteAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteAlert,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alerts"] })
      sileo.success({ title: "Alert deleted" })
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to delete alert" })
    },
  })
}

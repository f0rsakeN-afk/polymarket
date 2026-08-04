"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createAlert, listAlerts, deleteAlert } from "@/lib/api/alerts"

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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  })
}

export function useDeleteAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteAlert,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  })
}

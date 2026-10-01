"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { flagsApi } from "@/lib/api/flags"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"
import type { CreateFlagParams, ResolveFlagParams } from "@/lib/api/flags"
import { apiErrorMessage } from "@/lib/api/client"

export function useFlagsForMarket(marketId: string) {
  return useQuery({
    queryKey: queryKeys.flags(marketId),
    queryFn: () => flagsApi.getForMarket(marketId).then((r) => r.data),
    enabled: !!marketId,
    staleTime: 30_000,
  })
}

export function useCreateFlag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: CreateFlagParams) => flagsApi.create(data),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.flags() })
      sileo.success({ title: res.message ?? "Market flagged" })
    },
    onError: (err) => {
      sileo.error({ title: apiErrorMessage(err, "Failed to flag market") })
    },
  })
}

export function useResolveFlag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ flagId, data }: { flagId: string; data: ResolveFlagParams }) =>
      flagsApi.resolve(flagId, data),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.flags() })
      sileo.success({ title: res.message ?? "Flag resolved" })
    },
    onError: (err) => {
      sileo.error({ title: apiErrorMessage(err, "Failed to resolve flag") })
    },
  })
}

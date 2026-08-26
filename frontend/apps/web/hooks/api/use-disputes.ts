"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { disputesApi } from "@/lib/api/disputes"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"
import type {
  CreateDisputeParams,
  ProposeResolutionParams,
  AdjudicateDisputeParams,
} from "@/lib/api/disputes"

export function useDisputesForMarket(marketId: string) {
  return useQuery({
    queryKey: queryKeys.disputes(marketId),
    queryFn: () => disputesApi.getForMarket(marketId).then((r) => r.data),
    enabled: !!marketId,
    staleTime: 30_000,
  })
}

export function useCreateDispute() {
  return useMutation({
    mutationFn: (data: CreateDisputeParams) => disputesApi.create(data),
    onSuccess: () => {
      sileo.success({ title: "Dispute filed" })
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to file dispute" })
    },
  })
}

export function useProposeResolution() {
  return useMutation({
    mutationFn: (data: ProposeResolutionParams) => disputesApi.proposeResolution(data),
    onSuccess: () => {
      sileo.success({ title: "Resolution proposed" })
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to propose resolution" })
    },
  })
}

export function useAdjudicateDispute() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ disputeId, data }: { disputeId: string; data: AdjudicateDisputeParams }) =>
      disputesApi.adjudicate(disputeId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["disputes"] })
      sileo.success({ title: "Dispute adjudicated" })
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to adjudicate dispute" })
    },
  })
}

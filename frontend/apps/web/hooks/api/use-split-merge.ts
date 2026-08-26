"use client"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { splitMergeApi } from "@/lib/api/split-merge"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"

export function useSplit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ marketId, amount }: { marketId: string; amount: number }) =>
      splitMergeApi.split(marketId, amount),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
      sileo.success({ title: "Shares split", description: "USDC converted to YES/NO shares" })
    },
    onError: (err) => {
      sileo.error({ title: "Split failed", description: err instanceof Error ? err.message : "Unknown error" })
    },
  })
}

export function useMerge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ marketId, amount }: { marketId: string; amount: number }) =>
      splitMergeApi.merge(marketId, amount),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
      sileo.success({ title: "Shares merged", description: "YES/NO shares converted to USDC" })
    },
    onError: (err) => {
      sileo.error({ title: "Merge failed", description: err instanceof Error ? err.message : "Unknown error" })
    },
  })
}

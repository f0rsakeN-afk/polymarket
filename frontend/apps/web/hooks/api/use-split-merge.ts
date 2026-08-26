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
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
      sileo.success({ title: res.message ?? "Liquidity split successfully" })
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Split failed" })
    },
  })
}

export function useMerge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ marketId, amount }: { marketId: string; amount: number }) =>
      splitMergeApi.merge(marketId, amount),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.positions() })
      sileo.success({ title: res.message ?? "Liquidity merged successfully" })
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Merge failed" })
    },
  })
}

"use client"

import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getWallet, deposit, withdraw, listTransactions } from "@/lib/api/wallet"
import { queryKeys } from "@/lib/api/queryKeys"
import type { Wallet, Transaction } from "@/hooks/api/types/wallet"

export function useWallet() {
  return useQuery({
    queryKey: queryKeys.wallet(),
    queryFn: () => getWallet().then((r) => r.data as Wallet),
    staleTime: 10_000,
  })
}

export function useTransactions() {
  return useInfiniteQuery({
    queryKey: queryKeys.transactions(),
    queryFn: ({ pageParam }) => listTransactions({ page: pageParam, page_size: 20 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) => {
      const txs = (lastPage as { data?: { transactions?: unknown[] } }).data?.transactions ?? []
      return txs.length === 20 ? lastPageParam + 1 : undefined
    },
    select: (data) => ({
      transactions: data.pages.flatMap(
        (p) => ((p as { data?: { transactions?: Transaction[] } }).data?.transactions ?? []) as Transaction[]
      ),
      hasMore:
        ((data.pages[data.pages.length - 1] as { data?: { transactions?: unknown[] } } | undefined)
          ?.data?.transactions?.length ?? 0) === 20,
    }),
    staleTime: 10_000,
  })
}

export function useDeposit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deposit,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.transactions() })
    },
  })
}

export function useWithdraw() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: withdraw,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.transactions() })
    },
  })
}

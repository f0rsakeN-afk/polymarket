"use client"

import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getWallet, deposit, withdraw, listTransactions } from "@/lib/api/wallet"
import type { Wallet, Transaction } from "@/lib/types/api"

export function useWallet() {
  return useQuery({
    queryKey: ["wallet"] as const,
    queryFn: () => getWallet(),
    select: (data) => data as Wallet,
  })
}

export function useTransactions() {
  return useInfiniteQuery({
    queryKey: ["transactions"] as const,
    queryFn: ({ pageParam }) => listTransactions({ page: pageParam, page_size: 20 }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.has_more ? lastPageParam + 1 : undefined,
    select: (data) => ({
      transactions: data.pages.flatMap((p) => p.data) as Transaction[],
      hasMore: data.pages[data.pages.length - 1]?.has_more ?? false,
    }),
  })
}

export function useDeposit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deposit,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wallet"] }),
  })
}

export function useWithdraw() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: withdraw,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wallet"] }),
  })
}

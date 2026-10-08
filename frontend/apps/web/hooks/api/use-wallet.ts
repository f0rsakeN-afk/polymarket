"use client"

import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getWallet, deposit, withdraw, listTransactions } from "@/lib/api/wallet"
import { queryKeys } from "@/lib/api/queryKeys"
import { sileo } from "sileo"
import { apiErrorMessage } from "@/lib/api/client"
import { useAuthGate, useLoadingWithGate } from "./use-auth-gate"

export function useWallet() {
  const { enabled, isAuthLoading } = useAuthGate()
  const query = useQuery({
    queryKey: queryKeys.wallet(),
    queryFn: () => getWallet().then((r) => r.data),
    staleTime: 10_000,
    enabled,
  })
  return { ...query, isLoading: useLoadingWithGate(query.isLoading, isAuthLoading, enabled) }
}

export function useTransactions() {
  const { enabled } = useAuthGate()
  // GET /api/v1/wallet/transactions is offset-paginated only (no
  // `next_cursor`/`has_more`) • a full page is the only "more" signal.
  const PAGE_SIZE = 20
  return useInfiniteQuery({
    queryKey: queryKeys.transactions(),
    queryFn: ({ pageParam }) => listTransactions({ page: pageParam, page_size: PAGE_SIZE }),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _, lastPageParam) =>
      lastPage.data.transactions.length === PAGE_SIZE ? lastPageParam + 1 : undefined,
    select: (data) => ({
      transactions: data.pages.flatMap((p) => p.data.transactions),
      hasMore:
        (data.pages[data.pages.length - 1]?.data.transactions.length ?? 0) === PAGE_SIZE,
    }),
    staleTime: 10_000,
    enabled,
  })
}

export function useDeposit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deposit,
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Deposit initiated", description: "Complete payment to add funds." })
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.transactions() })
    },
    onError: (err) => {
      sileo.error({ title: apiErrorMessage(err, "Deposit failed") })
    },
  })
}

export function useWithdraw() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: withdraw,
    onSuccess: (res) => {
      sileo.success({ title: res.message ?? "Withdrawal submitted", description: "Funds will arrive after blockchain confirmation." })
      qc.invalidateQueries({ queryKey: queryKeys.wallet() })
      qc.invalidateQueries({ queryKey: queryKeys.transactions() })
    },
    onError: (err) => {
      sileo.error({ title: apiErrorMessage(err, "Withdrawal failed") })
    },
  })
}

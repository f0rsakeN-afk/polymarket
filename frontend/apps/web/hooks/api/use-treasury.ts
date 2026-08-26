"use client"

import { useQuery } from "@tanstack/react-query"
import { getTreasury, getTreasuryLogs } from "@/lib/api/treasury"
import { queryKeys } from "@/lib/api/queryKeys"

export function useTreasury() {
  return useQuery({
    queryKey: queryKeys.treasury(),
    queryFn: () => getTreasury().then((r) => r.data),
  })
}

export function useTreasuryLogs(params?: { page?: number; page_size?: number; event?: string }) {
  return useQuery({
    queryKey: queryKeys.treasuryLogs(params),
    queryFn: () => getTreasuryLogs(params).then((r) => r.data),
  })
}

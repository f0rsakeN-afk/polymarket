"use client"

import { useQuery } from "@tanstack/react-query"
import { getReferralCode, getReferralStats } from "@/lib/api/referrals"
import { queryKeys } from "@/lib/api/queryKeys"

export function useReferralCode() {
  return useQuery({
    queryKey: queryKeys.referralCode(),
    queryFn: getReferralCode,
    select: (res) => res.data,
    staleTime: 60_000,
  })
}

export function useReferralStats() {
  return useQuery({
    queryKey: queryKeys.referralStats(),
    queryFn: getReferralStats,
    select: (res) => res.data,
    staleTime: 60_000,
  })
}

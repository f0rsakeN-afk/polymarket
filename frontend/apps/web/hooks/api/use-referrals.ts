"use client"

import { useQuery } from "@tanstack/react-query"
import { getReferralCode, getReferralStats } from "@/lib/api/referrals"

export function useReferralCode() {
  return useQuery({
    queryKey: ["referral-code"],
    queryFn: getReferralCode,
    select: (res) => res.data,
  })
}

export function useReferralStats() {
  return useQuery({
    queryKey: ["referral-stats"],
    queryFn: getReferralStats,
    select: (res) => res.data,
  })
}

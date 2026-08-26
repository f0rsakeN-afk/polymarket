"use client"

import { useQuery } from "@tanstack/react-query"
import { authApi } from "@/lib/api/auth"

const ME_QUERY_KEY = ["me"] as const

export function useCurrentUser() {
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: () => authApi.me().then((r) => r.data),
    retry: false,
    // Always refetch to get the authoritative answer from the server.
    // staleTime: 0 ensures the previous user data (e.g. after logout or
    // cookie change) is not shown while a fresh fetch is in flight.
    staleTime: 0,
  })
}

"use client"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useRef } from "react"
import { AuthProvider } from "@/hooks/use-auth-context"
import { MarketSocketProvider } from "@/hooks/use-market-socket"

export function Providers({ children }: { children: React.ReactNode }) {
  const queryClientRef = useRef<QueryClient | null>(null)
  if (!queryClientRef.current) {
    queryClientRef.current = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 30_000,
          gcTime: 5 * 60_000,
          retry: 1,
          refetchOnWindowFocus: false,
        },
      },
    })
  }
  // ponytail: QueryClient is created once, ref stable — no stale closure risk.
  // WebSocket subscriptions are managed by useUserSocket/useMarketSocket
  // which hold their own connection singletons, so clearing the QueryClient
  // on unmount is unnecessary and was causing a stale closure bug in the
  // cleanup function that recreated it every render.
  const queryClient = queryClientRef.current

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MarketSocketProvider>{children}</MarketSocketProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}

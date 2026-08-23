"use client"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { AuthProvider } from "@/hooks/use-auth-context"
import { MarketSocketProvider } from "@/hooks/use-market-socket"

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  )
  useEffect(() => {
    return () => {
      queryClient.clear()
    }
  }, [queryClient])

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MarketSocketProvider>{children}</MarketSocketProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
}

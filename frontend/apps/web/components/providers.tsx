"use client"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ReactQueryDevtools } from "@tanstack/react-query-devtools"
import { useState } from "react"
import { AuthProvider } from "@/hooks/use-auth-context"
import { MarketSocketProvider } from "@/hooks/use-market-socket"
import { RealtimePrefsProvider } from "@/lib/realtime-prefs"
import { PriceAnnouncerProvider } from "@/lib/price-announcer"

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

  return (
    <QueryClientProvider client={queryClient}>
      <ReactQueryDevtools initialIsOpen={false} client={queryClient} />
      <AuthProvider>
        {/* Above the socket provider so the announcer sits outside every route.

            The live region has to outlive route changes: a region that unmounts
            with the page loses the announcement it was in the middle of. */}
        <RealtimePrefsProvider>
          <PriceAnnouncerProvider>
            <MarketSocketProvider>{children}</MarketSocketProvider>
          </PriceAnnouncerProvider>
        </RealtimePrefsProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}

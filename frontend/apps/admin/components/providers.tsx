"use client"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState } from "react"
import { Toaster } from "sileo"

import "sileo/styles.css"

import { configureAuthRouting } from "@workspace/api-client/client"

/**
 * Route policy, declared at module scope.
 *
 * Every admin route needs a session, so the shared default — an empty public
 * list — is already correct here. Declared explicitly anyway: "we rely on the
 * default" is one refactor away from "nobody configured this", and the failure
 * mode is an operator whose session expired being left on a dead page with no
 * sign-in link and nothing to click.
 *
 * Module scope rather than an effect, so the very first request already carries
 * the right policy — and the first request is usually the one that discovers the
 * session is gone.
 */
configureAuthRouting({ publicPaths: [], loginPath: "/login" })

/**
 * The admin app's providers.
 *
 * No websocket provider and no realtime preferences: this app has no live market
 * data. That is not a saving to boast about, it is the shape of the surface -
 * an operator reading a dispute queue does not need a socket, and shipping one
 * would be a connection per operator doing nothing.
 *
 * `staleTime` is shorter than the consumer app's. Admin data is the kind someone
 * acts on immediately - a ban, a ruling - so a value that was correct thirty
 * seconds ago is the kind that causes a wrong decision.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            gcTime: 5 * 60_000,
            retry: 1,
            refetchOnWindowFocus: true,
          },
        },
      })
  )

  return (
    <QueryClientProvider client={queryClient}>
      <Toaster />
      {children}
    </QueryClientProvider>
  )
}
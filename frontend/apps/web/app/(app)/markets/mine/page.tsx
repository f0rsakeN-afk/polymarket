import type { Metadata } from "next"

import MyMarketsClient from "./MyMarketsClient"

export const metadata: Metadata = {
  // Per-user, and behind auth. Same reasoning as /portfolio and /orders.
  robots: { index: false, follow: false },
}

export default function MyMarketsPage() {
  return (
    <div className="container mx-auto max-w-5xl px-4 py-8">
      <MyMarketsClient />
    </div>
  )
}

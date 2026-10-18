import type { Metadata } from "next"

import { CreateMarketForm } from "@/components/markets/create-market-form"

/**
 * Not indexed, and not in the sitemap.
 *
 * It is behind auth and it creates a moderation queue entry, not a page anyone
 * arrives at by searching. Indexing a form that renders nothing without a
 * session just puts an empty page in a search engine.
 */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
}

export default function NewMarketPage() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-8 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Propose a market</h1>
        <p className="text-sm text-muted-foreground">
          Anyone can propose one. A moderator checks it before it becomes tradable.
        </p>
      </header>
      <CreateMarketForm />
    </div>
  )
}

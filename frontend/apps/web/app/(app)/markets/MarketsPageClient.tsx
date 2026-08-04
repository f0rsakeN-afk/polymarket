"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { MarketList } from "@/components/markets/market-list"
import { useMarkets } from "@/hooks/api/use-markets"
import { SkeletonMarketGrid } from "@/components/shared/skeletons"
import { cn } from "@workspace/ui/lib/utils"
import { SearchIcon } from "lucide-react"

const CATEGORIES = ["All", "Crypto", "Politics", "Finance", "Science", "Sports", "Other"]

export function MarketsPageClient() {
  const [category, setCategory] = useState<string>("All")
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setQuery(search)
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [search])

  const activeCategory = category === "All" ? undefined : category
  const { data: marketsData, isLoading: marketsLoading, fetchNextPage: fetchMarketsNextPage, hasNextPage: marketsHasMore } = useMarkets({
    q: query || undefined,
    category: activeCategory,
  })

  const handleLoadMoreMarkets = useCallback(() => {
    fetchMarketsNextPage()
  }, [fetchMarketsNextPage])

  return (
    <div className="container mx-auto max-w-7xl px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Markets</h1>
        <p className="mt-1 text-muted-foreground text-sm">
          Browse and trade on prediction markets
        </p>
      </div>

      {/* Search */}
      <div className="relative">
        <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search markets..."
          className="w-full h-9 pl-9 pr-4 rounded-lg border border-border bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        />
      </div>

      {/* Category tabs */}
      <div className="flex items-center gap-1 border-b border-border overflow-x-auto scrollbar-hide">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={cn(
              "px-4 py-2 text-xs font-medium whitespace-nowrap border-b-2 -mb-px transition-colors",
              category === cat
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      <MarketList
        markets={marketsData?.markets ?? []}
        loading={marketsLoading}
        hasMore={marketsHasMore ?? false}
        onLoadMore={handleLoadMoreMarkets}
      />
    </div>
  )
}
